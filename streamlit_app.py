# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
import numpy as np
from datetime import time
from dateutil import tz
try:
    from streamlit_searchbox import st_searchbox  # dropdown live, stile meteoblue
    HAS_SEARCHBOX = True
except Exception:
    HAS_SEARCHBOX = False

# ------------------------ PAGE & THEME (light, ma accenti forti) ------------------------
ACCENT = "#0ea5b7"   # turchese Telemark
TEXT_DARK = "#0f172a"
MUTED = "#64748b"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --accent: {ACCENT};
}}
header {{ visibility: hidden; }}
h1,h2,h3,h4,h5 {{ color:{TEXT_DARK}; }}
.block-container{{ padding-top:0.5rem; }}
.badge {{
  display:inline-block;padding:6px 10px;border-radius:999px;
  border:1px solid #e5e7eb;color:{MUTED};font-size:.8rem;
}}
.brand {{ display:flex; gap:10px; align-items:center; border:1px solid #e5e7eb; border-radius:14px;
         padding:10px 12px; background:#fff; box-shadow:0 6px 18px rgba(15,23,42,.06); }}
.brand img {{ height:22px; }}
.kpi {{ display:flex; gap:8px; align-items:center; background:rgba(14,165,183,.06);
       border:1px dashed rgba(14,165,183,.45); padding:10px 12px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:{MUTED}; }}
.kpi .val {{ font-size:1rem; font-weight:800; color:{TEXT_DARK}; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Blocchi A/B/C · 8 marchi sciolina · Strutture Wintersteiger · Angoli (SIDE)</span>", unsafe_allow_html=True)

# ------------------------ UTILS ------------------------
def flag_emoji(cc: str) -> str:
    try:
        cc = (cc or "").upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(item: dict) -> str:
    """Costruisce un nome breve in stile Meteoblue (Città, Regione · CC)."""
    addr = item.get("address", {}) or {}
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or item.get("name") or ""
    region = addr.get("state") or addr.get("county") or addr.get("region") or ""
    cc = addr.get("country_code","") or ""
    parts = [p for p in [city, region] if p]
    base = ", ".join(parts[:2])
    return f"{flag_emoji(cc)}  {base}" if base else item.get("display_name","")

def nominatim_search(q: str):
    """Chiamata ad ogni tasto, restituisce 10 suggerimenti concisi."""
    if not q or len(q) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 10, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        for it in r.json():
            label = concise_label(it)
            lat = float(it.get("lat", 0)); lon = float(it.get("lon", 0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_map[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

# ------------------------ RICERCA LOCALITÀ ------------------------
st.markdown("#### 1) Cerca località")
if HAS_SEARCHBOX:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (es. Champoluc, Cervinia, Sestriere)",
        clear_on_submit=False,
        default=None,
    )
else:
    # fallback semplice se il componente non è installato
    selected = None
    st.info("Per la ricerca live installa `streamlit-searchbox` nei requirements. Uso input base temporaneo.")
    q = st.text_input("Località", "Champoluc")
    for s in nominatim_search(q):
        st.write(s)

if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc (Ramey)"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

# fallback
lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc (Ramey)")

hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ BLOCCHI A/B/C ------------------------
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

# ------------------------ METEO & MODELLI ------------------------
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
    # localizza a orario locale senza selettore
    localtz = tz.gettz("Europe/Rome")
    t = pd.to_datetime(res["time"]).dt.tz_localize(localtz, nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=localtz).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ------------------------ WAX BANDS (8 marchi) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("Ultra/Alpha Mix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Universal Cold",-12,-6), ("Universal Medium",-7,-2), ("Universal Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]
BRAND_BANDS = [
    ("Swix"      ,"#ef4444", SWIX),
    ("Toko"      ,"#f59e0b", TOKO),
    ("Vola"      ,"#3b82f6", VOLA),
    ("Rode"      ,"#22c55e", RODE),
    ("Holmenkol" ,"#06b6d4", HOLM),
    ("Maplus"    ,"#f97316", MAPL),
    ("Start"     ,"#eab308", START),
    ("Skigo"     ,"#a855f7", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ------------------------ STRUTTURE & ANGOLI (stile Wintersteiger) ------------------------
def tune_for(t_surf, discipline):
    # SIDE (gradi) + BASE (gradi) e famiglia struttura
    if t_surf <= -10:
        fam = ("linear","Lineare fine (freddo/secco)")
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        fam = ("cross","Incrociata universale")
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        fam = ("diagV","Chevron/Diagonale (umido)")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    """Preview grafica: soletta grigio chiaro + gole scure, passi regolari."""
    fig = plt.figure(figsize=(3.6, 2.1), dpi=180)
    ax = plt.gca(); ax.set_facecolor("#d9dadb")
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    groove = "#2b2b2b"

    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=groove, linewidth=2.6, solid_capstyle="round")
    elif kind == "cross":
        # due passate 45° e -45° con stesso passo
        for x in range(-20, 120, 10):
            ax.plot([x, x+60], [6, 54], color=groove, linewidth=2.2, alpha=0.95)
        for x in range(20, 160, 10):
            ax.plot([x, x-60], [6, 54], color=groove, linewidth=2.2, alpha=0.95)
    elif kind == "diagV":
        # chevron centrato: due famiglie convergenti
        for x in range(-10, 120, 8):
            ax.plot([x, 50], [6, 30], color=groove, linewidth=2.6, alpha=0.95)
            ax.plot([x, 50], [54, 30], color=groove, linewidth=2.6, alpha=0.95)
    else:
        # diagonale semplice (fallback)
        for x in range(-20, 120, 8):
            ax.plot([x, x+50], [6, 54], color=groove, linewidth=3.0)

    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ RUN ------------------------
st.markdown("#### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{label}** caricati.")
        st.dataframe(res, use_container_width=True)

        # grafici rapidi
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
            st.markdown(f"<div class='kpi'><span class='lab'>T_surf medio {L}</span><span class='val'>{t_med:.1f}°C</span></div>", unsafe_allow_html=True)

            # 8 marchi – 2 righe da 4
            cols = st.columns(4); cols2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85;color:{MUTED}'>{brand}</div>"
                    f"<div style='font-weight:800;color:{TEXT_DARK}'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85;color:{MUTED}'>{brand}</div>"
                    f"<div style='font-weight:800;color:{TEXT_DARK}'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # struttura + angoli
            fam, side, base = tune_for(t_med, "GS")  # riferimento discipline
            st.markdown(f"**Struttura consigliata:** {fam[1]}  ·  **Lamina SIDE:** {side:.1f}°  ·  **BASE:** {base:.1f}°")
            draw_structure(fam[0], fam[1])

            # tabella discipline personalizzate
            disc = st.multiselect(f"Discipline (Blocco {L})", ["SL","GS","SG","DH"], default=["SL","GS"], key=f"disc_{L}")
            rows = []
            for d in disc:
                fam_d, side_d, base_d = tune_for(t_med, d)
                rows.append([d, fam_d[1], f"{side_d:.1f}°", f"{base_d:.1f}°"])
            if rows:
                st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))
    except Exception as e:
        st.error(f"Errore: {e}")
