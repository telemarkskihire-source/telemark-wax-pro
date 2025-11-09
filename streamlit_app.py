# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
import numpy as np
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox  # dropdown live, tipo Meteoblue

# =========================
# PAGE STYLE (WHITE THEME)
# =========================
ACCENT = "#0ea5b7"  # turchese Telemark
TEXT_DARK = "#0f172a"
MUTED = "#475569"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --accent: {ACCENT};
}}
/* bianco pulito */
[data-testid="stAppViewContainer"] > .main {{
  background: #ffffff;
}}
.block-container {{
  padding-top: 0.8rem;
}}
h1,h2,h3,h4,h5, label {{
  color: {TEXT_DARK};
}}
p,span,div {{
  color: {TEXT_DARK};
}}
/* badge pill */
.badge {{
  display:inline-block; border:1px solid #e2e8f0; background:#f8fafc;
  padding:6px 10px; border-radius:999px; font-size:.80rem; color:{MUTED};
}}
/* card */
.card {{
  background:#ffffff; border:1px solid #e5e7eb; border-radius:16px; padding:14px;
  box-shadow: 0 8px 22px rgba(15,23,42,.06);
}}
/* brand chip */
.brand {{
  display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:12px;
  background:#ffffff; border:1px solid #e5e7eb;
}}
.brand img {{ height:22px; }}
/* primary buttons */
.stButton > button[kind="primary"] {{
  background: var(--accent);
  color: #002b30;
  border: none; font-weight: 700; border-radius: 12px;
}}
/* small caption */
small, .caption {{
  color:{MUTED};
}}
/* slim search */
input[type="text"] {{
  border-radius: 10px !important;
}}
</style>
""", unsafe_allow_html=True)

st.markdown("# Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca rapida tipo Meteoblue · Blocchi A/B/C · 8 marchi sciolina · Strutture (stile Wintersteiger)</span>", unsafe_allow_html=True)

# =========================
# UTILS
# =========================
ROME = tz.gettz("Europe/Rome")

def flag_emoji(country_code: str) -> str:
    try:
        cc = (country_code or "").upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(item: dict) -> str:
    """Crea una label breve tipo Meteoblue: Città · Regione · 🇮🇹"""
    addr = item.get("address", {}) or {}
    city = addr.get("city") or addr.get("town") or addr.get("village") or ""
    region = addr.get("state") or addr.get("county") or ""
    cc = addr.get("country_code", "") or ""
    parts = [p for p in [city, region] if p]
    short = " · ".join(parts) if parts else (item.get("display_name","").split(",")[0])
    return f"{flag_emoji(cc)}  {short}"

# Nominatim search (chiamato ad OGNI carattere dalla searchbox)
def nominatim_search(q: str):
    if not q or len(q) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 10, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=7
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

# =========================
# 1) RICERCA LOCALITÀ
# =========================
st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (es. Champoluc, Cervinia, Sestriere)",
    clear_on_submit=False,  # non cancella testo; aggiorna live come Meteoblue
    default=None
)

# decodifica in lat/lon/label
if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc (Ramey)"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc (Ramey)")

# =========================
# 2) FINESTRE A/B/C
# =========================
st.subheader("2) Finestre orarie (oggi)")
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

# =========================
# 3) DATI METEO & MODELLO
# =========================
def fetch_open_meteo(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Rome",
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
    df["time"] = pd.to_datetime(df["time"])  # naive
    now0 = pd.Timestamp.now(tz=ROME).floor("H").tz_convert(None)  # confronti naive
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
    t = pd.to_datetime(res["time"]).dt.tz_localize(ROME, nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=ROME).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# =========================
# WAX BANDS (8 MARCHE)
# =========================
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

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# =========================
# STRUTTURE (stile Wintersteiger)
# =========================
# preset: 'linear_fine', 'cross_45', 'chevron_v', 'diagonal'
STRUCTURE_PRESETS = [
    ("Lineare fine (freddo/secco)", "linear_fine"),
    ("Incrociata 45°/45° (universale)", "cross_45"),
    ("Chevron / V-drain (umido)", "chevron_v"),
    ("Diagonale (scarico)", "diagonal"),
]

def draw_structure(kind: str, title: str):
    """
    Anteprima pulita, base chiara e gole scure, ritmo regolare:
    - linear_fine: righe verticali vicine
    - cross_45: incrocio 45°/45°
    - chevron_v: V ripetute (scarico centrale)
    - diagonal: linee parallele inclinate
    """
    fig = plt.figure(figsize=(3.6, 2.2), dpi=175)
    ax = plt.gca()
    ax.set_facecolor("#e7e9ee")  # soletta chiara
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    groove = "#2b2b2b"

    if kind == "linear_fine":
        for x in range(8, 98, 4):
            ax.plot([x, x], [6, 54], color=groove, linewidth=2.0, solid_capstyle="round")
    elif kind == "cross_45":
        for x in range(-20, 140, 10):
            ax.plot([x, x+55], [6, 54], color=groove, linewidth=2.2, alpha=0.95)
        for x in range(-20, 140, 10):
            ax.plot([x+55, x], [6, 54], color=groove, linewidth=2.2, alpha=0.95)
    elif kind == "chevron_v":
        # V ripetute con vertice centrale a y=30
        centers = np.linspace(0, 100, 12)
        for c in centers:
            ax.plot([c-8, c], [12, 30], color=groove, linewidth=2.6, alpha=0.95)
            ax.plot([c+8, c], [12, 30], color=groove, linewidth=2.6, alpha=0.95)
            ax.plot([c-8, c], [48, 30], color=groove, linewidth=2.6, alpha=0.95)
            ax.plot([c+8, c], [48, 30], color=groove, linewidth=2.6, alpha=0.95)
    elif kind == "diagonal":
        for x in range(-30, 130, 8):
            ax.plot([x, x+60], [6, 54], color=groove, linewidth=3.0, alpha=0.95)
    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

def recommended_structure_family(t_surf: float):
    if t_surf <= -10:
        return STRUCTURE_PRESETS[0]  # linear_fine
    elif t_surf <= -3:
        return STRUCTURE_PRESETS[1]  # cross_45
    else:
        # umido/caldo → scarico
        return STRUCTURE_PRESETS[2]  # chevron_v

def edge_setup(t_surf: float, discipline: str):
    # SIDE/BASE raccomandati (valori tipici)
    if t_surf <= -10:
        base = 0.5; side = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}[discipline]
    elif t_surf <= -3:
        base = 0.7; side = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}[discipline]
    else:
        base = 0.8 if t_surf <= 0.5 else 1.0
        side = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}[discipline]
    return side, base

# =========================
# AZIONE
# =========================
st.subheader("3) Scarica previsioni e calcola")
go = st.button("Scarica per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        st.success(f"Dati per **{label}** caricati.")
        st.dataframe(res, use_container_width=True)

        # grafici semplici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T_surf"); plt.plot(t,res["T_top5"],label="T_top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV risultato", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # Blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"## Blocco {L}")
            W = window_slice(res, s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # 8 brand cards
            rows1 = st.columns(4); rows2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                rows1[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div class='caption'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                rows2[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div class='caption'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # Struttura consigliata (Wintersteiger-like)
            title, code = recommended_structure_family(t_med)
            st.markdown(f"**Struttura consigliata:** {title}")
            draw_structure(code, title)

            # Setup lamine per specialità (tutte visibili senza toggle)
            st.markdown("**Angoli lamine suggeriti (SIDE / BASE):**")
            table = []
            for d in ["SL","GS","SG","DH"]:
                side, base = edge_setup(t_med, d)
                table.append([d, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(table, columns=["Disciplina","SIDE (°)","BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
