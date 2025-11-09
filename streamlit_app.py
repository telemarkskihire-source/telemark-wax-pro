# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ========================= THEME / STYLE (DARK) =========================
PRIMARY   = "#0ee7ff"  # turchese acceso
ACCENT    = "#a3e635"  # lime per accent/kpi
ACCENT_2  = "#f472b6"  # magenta per note
BG        = "#0b132b"  # sfondo
PANEL     = "#111827"  # card scura
TEXT      = "#e5f4ff"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg: {BG};
  --panel: {PANEL};
  --text: {TEXT};
  --primary: {PRIMARY};
  --accent: {ACCENT};
  --accent2: {ACCENT_2};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: linear-gradient(180deg, var(--bg) 0%, #0b1222 100%);
}}
.block-container {{ padding-top: .8rem; }}
h1,h2,h3,h4,h5, p, span, label, div {{ color: var(--text); }}
.card {{
  background: var(--panel);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 16px; padding: 14px;
  box-shadow: 0 12px 30px rgba(0,0,0,.35);
}}
.badge {{
  display:inline-block; border-radius:999px; padding:.28rem .6rem;
  border:1px solid rgba(255,255,255,.18);
  background: rgba(255,255,255,.06);
  color: var(--text); font-size:.78rem; opacity:.9;
}}
.kpi {{
  display:flex; gap:.6rem; align-items:center;
  background: rgba(14,231,255,.08);
  border:1px dashed rgba(14,231,255,.45);
  padding:.6rem .8rem; border-radius:12px;
}}
.kpi b {{ color: var(--primary); }}
.brands {{ display:grid; grid-template-columns: repeat(4,1fr); gap:.6rem; }}
.brand {{
  display:flex; gap:.6rem; align-items:center;
  background: rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.08);
  border-radius:12px; padding:.55rem .7rem;
}}
.brand .name {{ font-size:.8rem; opacity:.85; }}
.brand .rec  {{ font-weight:800; }}
hr.div {{ border:none; border-top:1px solid rgba(255,255,255,.12); margin:.6rem 0 1rem; }}
.small {{ font-size:.84rem; opacity:.9; color:#cbd5e1; }}
.em   {{ color: var(--accent2); font-weight:700; }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Altitudine · Finestre A/B/C · 8 marchi · Strutture (nomi) · Angoli</span>", unsafe_allow_html=True)

# ========================= HELPERS =========================
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # nome breve + admin1 + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

@st.cache_data(show_spinner=False, ttl=3600)
def nominatim(q:str):
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
                     headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
    r.raise_for_status()
    return r.json()

def nominatim_search(q:str):
    if not q or len(q)<2: return []
    try:
        js = nominatim(q)
        st.session_state._options = {}
        out = []
        for it in js:
            addr = it.get("address",{}) or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag(cc)}  {label_short}"
            lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
            out.append(key)
        return out
    except:
        return []

@st.cache_data(show_spinner=False, ttl=3600)
def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except:
        pass
    return None

@st.cache_data(show_spinner=True, ttl=900)
def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":"Europe/Rome",
            "hourly":"temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status()
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
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["Ora"]     = df["time"].dt.strftime("%Y-%m-%d %H:%M")
    out["T aria (°C)"] = df["temperature_2m"].astype(float).round(1)
    out["T rugiada (°C)"] = df["dew_point_2m"].astype(float).round(1)
    out["Nuvolosità (%)"] = df["cloudcover"].astype(float).clip(0,100).round(0).astype(int)
    out["Vento (m/s)"]    = (df["windspeed_10m"].astype(float)/3.6).round(2)
    out["Giorno(1/0)"]    = df["is_day"].astype(int)
    out["Prec (mm/h)"]    = df["precipitation"].astype(float).round(2)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["Tipo precipit."] = _prp_type(extra)
    out["td_raw"] = df["dew_point_2m"].astype(float)
    out["T2m_raw"] = df["temperature_2m"].astype(float)
    out["cloud_raw"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind_raw"] = (df["windspeed_10m"].astype(float)/3.6)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    D = df.copy()
    # ricostruisco colonne tecniche
    T2m  = D["T2m_raw"]; td = D["td_raw"]; cloud = D["cloud_raw"]; wind = D["wind_raw"]
    prp_type = D["Tipo precipit."].str.lower()
    sunup = D["Giorno(1/0)"].astype(int)==1
    tw = (T2m + td)/2.0
    wet = (prp_type.isin(["rain","mixed"]) | (T2m>0) |
           (sunup & (cloud<0.3) & (T2m>=-3)) |
           (prp_type.eq("snow") & (T2m>=-1)) |
           (prp_type.eq("snow") & tw.ge(-0.5).fillna(False))
    )
    T_surf = pd.Series(index=D.index, dtype=float); T_surf.loc[wet] = 0.0
    dry = ~wet
    clear = (1.0 - cloud).clip(0,1); windc = wind.clip(upper=6.0)
    drad = (1.5 + 3.0*clear - 0.3*windc).clip(0.5, 4.5)
    T_surf.loc[dry] = T2m[dry] - drad[dry]
    sunny_cold = sunup & dry & T2m.between(-10,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (T2m + 0.5*(1.0 - cloud))[sunny_cold],
        pd.Series(-0.5, index=D.index)[sunny_cold]
    ], axis=1).min(axis=1)
    T_top5 = pd.Series(index=D.index, dtype=float)
    tau = pd.Series(6.0, index=D.index, dtype=float)
    tau.loc[prp_type.isin(["rain","mixed"]) | (wind>=6)] = 3.0
    tau.loc[(~sunup) & (wind<2) & (cloud<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(D)>0:
        T_top5.iloc[0] = min(T2m.iloc[0], 0.0)
        for i in range(1,len(D)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])
    D["T neve (superf.) °C"] = T_surf.round(1)
    D["T neve (5mm) °C"]     = T_top5.round(1)
    # pulizia colonne per vista
    view = D[["Ora","T aria (°C)","T neve (superf.) °C","T neve (5mm) °C",
              "Prec (mm/h)","Tipo precipit.","Vento (m/s)","Nuvolosità (%)","Giorno(1/0)"]].copy()
    return view

def window_slice(res_df, s, e):
    t = pd.to_datetime(res_df["Ora"])
    D = res_df.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz("Europe/Rome")).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ========================= WAX BRANDS =========================
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [
    ("Swix",      "#ef4444", SWIX),
    ("Toko",      "#f59e0b", TOKO),
    ("Vola",      "#3b82f6", VOLA),
    ("Rode",      "#22c55e", RODE),
    ("Holmenkol", "#06b6d4", HOLM),
    ("Maplus",    "#f97316", MAPL),
    ("Start",     "#eab308", START),
    ("Skigo",     "#a855f7", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ========================= STRUCTURE (NOMI SOLI) =========================
# Manteniamo nomi richiesti: Linear Fine / Thumb Print / Wave / Cross Hatch
def structure_family(t_surf: float):
    if t_surf <= -10:
        return "Linear Fine (freddo/secco)"
    elif t_surf <= -3:
        return "Cross Hatch (universale)"
    elif t_surf <= -1:
        return "Wave (universale)"
    else:
        return "Thumb Print (umido/caldo)"

def tune_for(t_surf, discipline):
    # Angolo SIDE “da gara” + BASE in funzione delle condizioni
    if t_surf <= -10:
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return structure_family(t_surf), side_map.get(discipline, 88.0), base

def brand_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'>\
<rect width='160' height='36' rx='8' fill='{color}'/>\
<text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    b64 = base64.b64encode(svg.encode()).decode()
    return f"<img src='data:image/svg+xml;base64,{b64}'/>"

# ========================= UI — 1) RICERCA =========================
st.markdown("### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi… es. Champoluc, Plateau Rosa, Cervinia",
    clear_on_submit=False,
    default=None
)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><div>Località:</div><b>{place_label}</b><div>{alt_txt}</div></div>", unsafe_allow_html=True)

# ========================= 2) Finestre A/B/C =========================
st.markdown("### 2) Finestre orarie A · B · C (oggi)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ========================= 3) METEO + RACCOMANDAZIONI =========================
st.markdown("### 3) Scarica dati meteo & calcola")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        view = compute_snow_temperature(src, dt_hours=1.0)

        # ---- TABELLONE PULITO ----
        st.markdown("<div class='card'><b>Dati previsionali (puliti)</b></div>", unsafe_allow_html=True)
        st.dataframe(
            view.rename(columns={
                "Giorno(1/0)":"Giorno (1 sì)",
            }),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ora": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm", help="ora locale"),
                "T aria (°C)": st.column_config.NumberColumn(format="%.1f", help="Aria a 2m"),
                "T neve (superf.) °C": st.column_config.NumberColumn(format="%.1f", help="Stima superficie neve"),
                "T neve (5mm) °C": st.column_config.NumberColumn(format="%.1f", help="Top ~5 mm"),
                "Prec (mm/h)": st.column_config.NumberColumn(format="%.2f"),
                "Vento (m/s)": st.column_config.NumberColumn(format="%.2f"),
                "Nuvolosità (%)": st.column_config.NumberColumn(format="%d"),
            }
        )

        # ---- GRAFICI COMPATTI ----
        t = pd.to_datetime(view["Ora"])
        fig1 = plt.figure(figsize=(7,2.6))
        plt.plot(t, view["T aria (°C)"], label="T aria")
        plt.plot(t, view["T neve (superf.) °C"], label="T neve surf.")
        plt.plot(t, view["T neve (5mm) °C"], label="T neve 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(7,2.2))
        plt.bar(t, view["Prec (mm/h)"])
        plt.title("Precipitazioni"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        st.download_button(
            "Scarica CSV",
            data=view.to_csv(index=False),
            file_name="forecast_with_snowT.csv",
            mime="text/csv"
        )

        # ---- BLOCCHI A/B/C ----
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"<hr class='div'/><h4>Blocco {L}</h4>", unsafe_allow_html=True)
            W = window_slice(view, s, e)
            t_med = float(W["T neve (superf.) °C"].mean())
            st.markdown(f"<div class='kpi'>T_surf medio **{L}**: <b>{t_med:.1f}°C</b></div>", unsafe_allow_html=True)

            # Marchi (8) in due righe
            st.markdown("<div class='brands'>", unsafe_allow_html=True)
            for (name,color,bands) in BRANDS:
                rec = pick(bands, t_med)
                st.markdown(
                    f"<div class='brand'>{brand_badge(name.upper(), color)}"
                    f"<div><div class='name'>{name}</div>"
                    f"<div class='rec'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            st.markdown("</div>", unsafe_allow_html=True)

            # Struttura (solo nome) + angoli per discipline
            fam = structure_family(t_med)
            st.markdown(f"**Struttura consigliata (famiglia):** <span class='em'>{fam}</span>", unsafe_allow_html=True)

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam_d, side, base = tune_for(t_med, d)
                rows.append([d, fam_d, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
