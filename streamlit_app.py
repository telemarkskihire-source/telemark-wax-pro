# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz

# ---------------------- PAGE / THEME (sfondo bianco, elementi in evidenza) ----------------------
ACCENT = "#0ea5b7"   # turchese Telemark
TEXT_DARK = "#111827"
SUBTLE = "#6b7280"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(
    f"""
    <style>
      .brand-chip {{
        display:flex; align-items:center; gap:.6rem; padding:.5rem .7rem; border-radius:.8rem;
        border:1px solid #e5e7eb; background:#fff; box-shadow:0 6px 18px rgba(0,0,0,.06);
      }}
      .brand-chip img {{ height:22px }}
      .pill {{
        display:inline-block; padding:.20rem .6rem; border-radius:999px; border:1px solid #e5e7eb; color:{SUBTLE}; font-size:.78rem;
      }}
      .section-card {{
        background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:14px;
      }}
      h1,h2,h3,h4, label, .stSelectbox label, .stMultiSelect label {{ color:{TEXT_DARK} }}
      .accent {{ color:{ACCENT}; font-weight:700 }}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("### Telemark · Pro Wax & Tune")
st.write(
    f"<span class='pill'>Ricerca tipo Meteoblue</span> "
    f"<span class='pill'>Blocchi A/B/C</span> "
    f"<span class='pill'>Struttura + Angoli (SIDE/BASE)</span> "
    f"<span class='pill'>Marchi sciolina</span>", unsafe_allow_html=True
)

# ---------------------- UTILS ----------------------
def flag_emoji(cc: str) -> str:
    try:
        cc = (cc or "").upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(item: dict) -> str:
    """Compatta tipo meteoblue: Città, Regione, Paese (breve) + bandierina."""
    name = item.get("name") or item.get("display_name","").split(",")[0]
    addr = item.get("address", {}) or {}
    admin = addr.get("state") or addr.get("region") or addr.get("county") or ""
    country = addr.get("country","")
    cc = addr.get("country_code","")
    parts = [p for p in [name, admin, country] if p]
    s = ", ".join(parts[:2] + ([parts[-1]] if len(parts)>2 else []))
    if len(s) > 64:
        s = s[:61] + "…"
    return f"{flag_emoji(cc)}  {s}"

# Live suggestions ad ogni carattere (senza librerie esterne)
def nominatim_suggest(q: str):
    if not q or len(q) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 10, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=8
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        for item in r.json():
            lat = float(item.get("lat", 0)); lon = float(item.get("lon", 0))
            label = concise_label({
                "name": item.get("name") or item.get("display_name","").split(",")[0],
                "address": item.get("address", {})
            })
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_map[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

def svg_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='8' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ---------------------- 1) RICERCA LOCALITÀ (meteoblue-like) ----------------------
st.markdown("#### 1) Cerca località")
q = st.text_input("Località", placeholder="Digita e scegli… (es. Champoluc, Cervinia, Sestriere)", label_visibility="visible", key="q")
suggestions = nominatim_suggest(q)

sel_key = None
if suggestions:
    # un radio compatto che si aggiorna a ogni battuta: “sembra” un dropdown
    sel_key = st.radio("Suggerimenti", suggestions, index=0, label_visibility="collapsed")
    st.caption("Suggerimenti aggiornati in tempo reale")

if sel_key and "|||" in sel_key:
    lat, lon, label = st.session_state._geo_map.get(sel_key, (45.831, 7.730, "Champoluc (Ramey)"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc (Ramey)")

# ---------------------- 2) FINETRE ORARIE ----------------------
st.markdown("#### 2) Finestre orarie A · B · C (oggi)")
c1, c2, c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9, 0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11, 0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11, 0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13, 0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13, 0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16, 0), key="C_e")

hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ---------------------- 3) DATI METEO + SNOW TEMP ----------------------
def fetch_open_meteo(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).round(3)
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["td"] = df["dew_point_2m"].astype(float)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1
    tw = (df["T2m"] + df["td"]) / 2.0
    wet = (rain | (df["T2m"]>0) | (sunup & (df["cloud"]<0.3) & (df["T2m"]>=-3))
           | (snow & (df["T2m"]>=-1)) | (snow & tw.ge(-0.5).fillna(False)))
    T_surf = pd.Series(index=df.index, dtype=float); T_surf.loc[wet] = 0.0
    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1); windc = df["wind"].clip(upper=6.0)
    drad = (1.5 + 3.0*clear - 0.3*windc).clip(0.5, 4.5)
    T_surf.loc[dry] = df["T2m"][dry] - drad[dry]
    sunny_cold = sunup & dry & df["T2m"].between(-10,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (df["T2m"] + 0.5*(1.0 - df["cloud"]))[sunny_cold],
        pd.Series(-0.5, index=df.index)[sunny_cold]
    ], axis=1).min(axis=1)
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])
    df["T_surf"] = T_surf; df["T_top5"] = T_top5; return df

def window_slice(res, s, e):
    t = pd.to_datetime(res["time"])
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now().date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ---------------------- WAX BANDS (4 brand “core”, estensibile) ----------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
BRANDS = [("Swix","#ef4444",SWIX), ("Toko","#f59e0b",TOKO), ("Vola","#3b82f6",VOLA), ("Rode","#22c55e",RODE)]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ---------------------- STRUTTURE & ANGOLI (stile Wintersteiger) ----------------------
def tune_for(t_surf, discipline):
    if t_surf <= -10:
        fam = ("linear","Lineare fine (freddo/secco)")
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        fam = ("cross","Incrociata universale (media)")
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        fam = ("V","Scarico a V / diagonale (umido/caldo)")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    # look pulito in stile “scheda Wintersteiger”
    fig = plt.figure(figsize=(3.6, 2.1), dpi=190)
    ax = plt.gca(); ax.set_facecolor("#e5e7eb")  # grigio chiaro soletta
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    color = "#2b2b2b"
    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=color, linewidth=2.4, solid_capstyle="round")
    elif kind == "cross":
        for x in range(-10, 120, 10):
            ax.plot([x, x+50], [6, 54], color=color, linewidth=2.0)
        for x in range(10, 110, 10):
            ax.plot([x, x-50], [6, 54], color=color, linewidth=2.0)
    elif kind == "V":
        for x in range(-10, 120, 8):
            ax.plot([x, 50], [6, 30], color=color, linewidth=2.4)
            ax.plot([x, 50], [54, 30], color=color, linewidth=2.4)
    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

# ---------------------- RUN ----------------------
st.markdown("#### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{label}** caricati.")

        with st.expander("Anteprima dati (T2m, T_surf, T_top5, prp …)"):
            st.dataframe(res, use_container_width=True)

        # grafici sintetici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T_surf"); plt.plot(t,res["T_top5"],label="T_top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV risultato", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}:** <span class='accent'>{t_med:.1f}°C</span>", unsafe_allow_html=True)

            # Marchi sciolina (chips a colori)
            cols = st.columns(len(BRANDS))
            for i,(brand,col,bands) in enumerate(BRANDS):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='brand-chip'><img src='{svg_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.78rem;color:{SUBTLE}'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            fam, side, base = tune_for(t_med, "GS")  # riferimento
            st.markdown(f"**Struttura consigliata:** {fam[1]} · **Lamina SIDE:** {side:.1f}° · **BASE:** {base:.1f}°")
            draw_structure(fam[0], fam[1])

            # Discipline: tutte già presenti, modificabili
            disc = st.multiselect(f"Discipline (Blocco {L})", ["SL","GS","SG","DH"], default=["SL","GS","SG","DH"], key=f"disc_{L}")
            rows = []
            for d in disc:
                fam_d, side_d, base_d = tune_for(t_med, d)
                rows.append([d, fam_d[1], f"{side_d:.1f}°", f"{base_d:.1f}°"])
            if rows:
                st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
