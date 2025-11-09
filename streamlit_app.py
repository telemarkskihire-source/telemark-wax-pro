# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz

# ------------------------ THEME (su sfondo bianco) ------------------------
ACCENT = "#10bfcf"
TEXT_DARK = "#0f172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
h1,h2,h3,h4,h5, label {{ color:{TEXT_DARK}; }}
.small {{ font-size:.85rem; opacity:.75 }}
.badge {{ display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid #e5e7eb; }}
.card {{
  background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:16px;
  box-shadow:0 4px 18px rgba(0,0,0,.06);
}}
.brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px;
         background:#fafafa; border:1px solid #eee; }}
.brand img {{ height:22px; }}
.kpi {{ display:flex; gap:10px; align-items:center; background:rgba(16,191,207,.06);
       border:1px dashed rgba(16,191,207,.45); padding:10px 12px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:#64748b; }}
.kpi .val {{ font-size:1rem; font-weight:800; color:#0f172a; }}
.suggest-item {{
  width:100%; text-align:left; padding:8px 10px; border-radius:10px; border:1px solid #e5e7eb;
  background:#fff;
}}
.suggest-item:hover {{ border-color:{ACCENT}; background:#ecfeff; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Blocchi A/B/C · Sciolina + Struttura + Angoli (SIDE)</span>", unsafe_allow_html=True)

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = (country_code or "").upper()
        if len(cc) != 2: return "🏳️"
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def short_label(item: dict) -> str:
    addr = item.get("address", {}) or {}
    # prendo preferibilmente: city/town/village + state (o county) + country
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or item.get("name") or ""
    reg  = addr.get("state") or addr.get("county") or ""
    ctry = addr.get("country") or ""
    parts = [p for p in [city, reg, ctry] if p]
    return ", ".join(parts)[:80]

# ricerca “live” senza librerie extra
def search_places(q: str):
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
        return r.json()
    except Exception:
        return []

# ------------------------ 1) RICERCA LOCALITÀ ------------------------
st.markdown("#### 1) Cerca località")
if "query" not in st.session_state: st.session_state.query = ""
if "suggestions" not in st.session_state: st.session_state.suggestions = []
if "sel" not in st.session_state:
    st.session_state.sel = {"lat": 45.831, "lon": 7.730, "label": "🇮🇹 Champoluc, Valle d’Aosta, Italy"}

def do_search():
    q = st.session_state.query
    st.session_state.suggestions = search_places(q)

st.text_input("Digita e scegli… (es. Champoluc, Cervinia, Sestriere)", key="query", on_change=do_search)
# aggiorna suggerimenti ad ogni modifica (oltre a on_change, utile su mobile)
if st.session_state.query and len(st.session_state.query) >= 2:
    st.session_state.suggestions = search_places(st.session_state.query)

# lista suggerimenti stile dropdown
if st.session_state.suggestions:
    cols = st.columns([1,1,1,1,1,1,1,1])  # per stringere visivamente
    with st.container():
        for i, it in enumerate(st.session_state.suggestions[:8]):
            addr = it.get("address", {}) or {}
            cc   = addr.get("country_code", "")
            label_short = short_label(it)
            lab = f"{flag_emoji(cc)}  {label_short}"
            if st.button(lab, key=f"sug{i}", use_container_width=True):
                st.session_state.sel = {
                    "lat": float(it.get("lat", 45.831)),
                    "lon": float(it.get("lon", 7.730)),
                    "label": f"{flag_emoji(cc)}  {label_short}"
                }
                st.session_state.suggestions = []

sel_lat = st.session_state.sel["lat"]
sel_lon = st.session_state.sel["lon"]
sel_label = st.session_state.sel["label"]

st.markdown(f"<div class='kpi'><span class='lab'>Selezione</span><span class='val'>{sel_label}</span></div>", unsafe_allow_html=True)

# ------------------------ 2) FINESTRE A/B/C ------------------------
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

hours = st.slider("Ore previsione da scaricare", 12, 168, 72, 12)

# ------------------------ 3) DATI METEO & T NEVE ------------------------
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
    # timezone già “auto”, quindi consideriamo l’ora locale della località
    t = pd.to_datetime(res["time"])
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now().date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ------------------------ WAX BANDS (4 marchi principali) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
BRANDS = [("Swix","#ef4444",SWIX),("Toko","#f59e0b",TOKO),("Vola","#3b82f6",VOLA),("Rode","#22c55e",RODE)]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='150' height='34'><rect width='150' height='34' rx='6' fill='{color}'/><text x='12' y='23' font-size='14' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ STRUTTURE STILE WINTERSTEIGER ------------------------
def draw_structure(kind: str, title: str):
    """
    linear  : linee parallele verticali (freddo/secco)
    arc     : archi/onde simmetriche (universale)
    drain   : diagonali di scarico (umido/caldo)
    """
    fig = plt.figure(figsize=(3.4, 2.0), dpi=180)
    ax = plt.gca(); ax.set_facecolor("#d8d8d8")
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    groove = "#2b2b2b"

    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=groove, linewidth=2.6, solid_capstyle="round")

    elif kind == "arc":
        xs = np.linspace(5, 95, 9)
        for x in xs:
            y = 30 + 20*np.cos(np.linspace(-np.pi, np.pi, 120))
            ax.plot(np.full_like(y, x), y, color=groove, linewidth=2.2)

    elif kind == "drain":
        for x in range(-10, 120, 8):
            ax.plot([x, x+60], [6, 54], color=groove, linewidth=2.8, solid_capstyle="round")

    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

def tune_for(t_surf, discipline):
    # Mappa struttura + angoli SIDE/BASE (SIDE espresso come 88–87.x come chiesto)
    if t_surf <= -10:
        fam = ("linear", "Freddo/Secco · Lineare fine")
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        fam = ("arc", "Universale · Onda/Arco")
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        fam = ("drain", "Caldo/Umido · Scarico diagonale")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

# ------------------------ RUN ------------------------
st.markdown("#### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(sel_lat, sel_lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{sel_label}** caricati.")

        # grafici rapidi
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve superficie"); plt.plot(t,res["T_top5"],label="T neve 0–5mm")
        plt.legend(); plt.title("Temperature (°C)"); plt.xlabel("Ora"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); st.pyplot(fig2)
        st.download_button("Scarica CSV risultato", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # wax cards
            cols = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRANDS):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div class='small'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # struttura + angoli (tabella per tutte le discipline)
            fam, side_gs, base_gs = tune_for(t_med, "GS")
            st.markdown(f"**Struttura consigliata:** {fam[1]}  ·  **Esempio (GS) SIDE:** {side_gs:.1f}°  ·  **BASE:** {base_gs:.1f}°")
            if fam[0] == "linear":
                draw_structure("linear", "Lineare fine (freddo/secco)")
            elif fam[0] == "arc":
                draw_structure("arc", "Onda/Arco (universale)")
            else:
                draw_structure("drain", "Scarico diagonale (umido)")

            rows = []
            for d in ["SL","GS","SG","DH"]:
                fam_d, side_d, base_d = tune_for(t_med, d)
                rows.append([d, fam_d[1], f"{side_d:.1f}°", f"{base_d:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
