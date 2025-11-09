# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math, datetime as dt
from datetime import time, date
from dateutil import tz
from streamlit_searchbox import st_searchbox
import matplotlib.pyplot as plt

# ------------------------ THEME (dark) ------------------------
PRIMARY = "#10bfcf"; BG = "#0b1020"; CARD = "#0f172a"; TEXT = "#eaf2ff"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --primary:{PRIMARY}; --text:{TEXT}; --card:{CARD}; }}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% -10%, #0d1b2a 0%, {BG} 45%, #0a0f1c 100%);
}}
.block-container {{ padding-top: 0.6rem; }}
* {{ color:{TEXT}; }}
h1,h2,h3,h4,h5,label {{ color:{TEXT}; }}
.card {{ background:{CARD}; border:1px solid rgba(255,255,255,.1); border-radius:16px; padding:14px; box-shadow:0 8px 24px rgba(0,0,0,.35); }}
.brand {{ display:flex; align-items:center; gap:.6rem; padding:.6rem .75rem; background:rgba(255,255,255,.04);
         border:1px solid rgba(255,255,255,.08); border-radius:12px; }}
.brand img {{ height:22px; }}
.badge {{ display:inline-block; padding:.25rem .6rem; border-radius:999px; background:rgba(16,191,207,.18); border:1px solid rgba(16,191,207,.45);
         font-size:.78rem }}
.kpi {{ display:flex; gap:.6rem; align-items:center; background:rgba(16,191,207,.06); border:1px dashed rgba(16,191,207,.45);
       padding:.5rem .7rem; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; opacity:.8 }}
.kpi .val {{ font-weight:800 }}
.hr {{ height:1px; background:linear-gradient(90deg, transparent, rgba(255,255,255,.2), transparent); margin:.8rem 0; }}
.cond {{ background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:.6rem .8rem; }}
.small {{ opacity:.8; font-size:.86rem }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

# concise place label + country code
def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or addr.get("municipality") or "")
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    if not name:  # fallback from display_name first comma piece
        name = (fallback.split(",")[0] if fallback else "")
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts) if parts else (fallback.split(",")[0] if fallback else "Località")
    if cc: short += f" — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: 
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.0"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._options = {}
        out = []
        for item in r.json():
            addr = item.get("address",{}) or {}
            label_short = concise_label(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{flag_emoji(cc)} {label_short}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"addr":addr,"label":f"{flag_emoji(cc)} {label_short}"}
            out.append(key)
        return out
    except:
        return []

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

# ------------------------ INPUTS: PLACE + DATE + WINDOWS ------------------------
st.markdown("#### 1) Località & giorno")
colp, cold = st.columns([2,1])
with colp:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (Champoluc, Plateau Rosa, Sestriere, Zermatt…) — suggerimenti live",
        clear_on_submit=False,
        default=None
    )
with cold:
    day = st.date_input("Giorno previsioni", value=date.today(), min_value=date.today()-dt.timedelta(days=0),
                        max_value=date.today()+dt.timedelta(days=6))

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        st.session_state["sel_lat"] = info["lat"]
        st.session_state["sel_lon"] = info["lon"]
        st.session_state["sel_label"] = info["label"]
lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
place_label = st.session_state.get("sel_label","🇮🇹 Champoluc — IT")
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><div class='lab'>Località</div><div class='val'>{place_label}</div><div class='lab'>{alt_txt}</div></div>", unsafe_allow_html=True)

st.markdown("#### 2) Finestre orarie A · B · C (per il giorno selezionato)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione (orizzonte)", 12, 168, 72, 12)

# ------------------------ DATA PIPELINE ------------------------
def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": "temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
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
    df["time"] = pd.to_datetime(df["time"])  # naive local time (per timezone param)
    now0 = pd.Timestamp.now().floor("H")
    # prendiamo dal “now” in poi, ma mostreremo solo il giorno scelto per i blocchi
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    # relative humidity might be named 'relative_humidity_2m' or 'relativehumidity_2m' depending on API
    rh_name = "relative_humidity_2m" if "relative_humidity_2m" in df.columns else "relativehumidity_2m"
    if rh_name in df.columns:
        out["RH"] = df[rh_name].astype(float)
    else:
        # fallback approximate RH from T and Td
        # RH ~ 100 * exp((17.625*Td/(243.04+Td)) - (17.625*T/(243.04+T)))
        T = out["T2m"].clip(-40, 40); Td = out["td"].clip(-40, 40)
        out["RH"] = 100*np.exp((17.625*Td/(243.04+Td)) - (17.625*T/(243.04+T)))

    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["snowfall"] = df["snowfall"].astype(float)
    out["rain"]     = df["rain"].astype(float)
    return out

# --- Better snow surface/top few mm temperature heuristic ---
def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    T = df["T2m"].astype(float)
    Td = df["td"].astype(float)
    RH = df["RH"].clip(0,100)
    cloud = df["cloud"]; wind = df["wind"]; sunup = df["sunup"].astype(int)==1
    prp = df["prp_mmph"]; snow = df["snowfall"]; rain = df["rain"]
    ptype = df["prp_type"].str.lower()

    # radiative-cooling factor (more when clear/dry/light wind/night)
    rad_cool = (1.2 + 2.8*(1-cloud) + 0.6*(1 - RH/100)).clip(0.5, 4.6)
    wind_term = (0.25*wind).clip(0, 1.8)

    # baseline target surface temperature without phase-change effects
    T_target = T - rad_cool + (sunup.astype(float))*0.7*cloud  # sun raises it modestly if cloudy low

    # precipitation phase effects: push toward 0°C when liquid or near-melting snow
    wet_mask = (rain>0.05) | ((snow>0) & (T>-2) & (Td>-4))
    T_target = np.where(wet_mask, np.minimum(T_target, 0.0 + 0.2*(rain>0)), T_target)

    # relaxation to target with timescale depending on wind/precip/cloud
    tau = np.full(len(df), 6.0)  # hours
    tau = np.where((rain>0.05) | (snow>0.1) | (wind>6), 2.5, tau)
    tau = np.where((~sunup) & (wind<2) & (cloud<0.3), 8.0, tau)
    alpha = 1.0 - np.exp(-dt_hours / np.maximum(tau, 0.5))

    # evolve surface (skin) and top-5mm (a little inertia)
    T_surf = np.zeros(len(df)); T_top5 = np.zeros(len(df))
    T_surf[0] = min(T.iloc[0], 0.0) if wet_mask.iloc[0] else T_target.iloc[0]
    T_top5[0] = 0.6*T_surf[0] + 0.4*min(T.iloc[0], 0.0)

    for i in range(1, len(df)):
        T_surf[i] = T_surf[i-1] + alpha[i]*(T_target.iloc[i] - T_surf[i-1])
        # if actively wet, clamp toward 0 but not fixed at 0
        if wet_mask.iloc[i]:
            T_surf[i] = min(T_surf[i], 0.0 + 0.1*(rain.iloc[i]>0))
        # top 5 mm follows slower
        alpha5 = min(0.6*alpha[i], 0.35)
        T_top5[i] = T_top5[i-1] + alpha5*(T_surf[i] - T_top5[i-1])

    out = df.copy()
    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    return out

def window_slice(res, tzname, day_sel: date, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==day_sel) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D[(D["dt"].dt.date==day_sel)].head(7)

# ------------------------ CLASSIFIERS ------------------------
def snow_condition_row(row):
    t = row["T_surf"]; rh = row["RH"]; prp = row["prp_mmph"]; snow = row["snowfall"]; rain = row["rain"]; cloud = row["cloud"]
    # very simple but readable taxonomy
    if snow > 0.2 and t < -1.0:
        return "Neve nuova fredda"
    if snow > 0.2 and t >= -1.0 and t <= 0.3:
        return "Neve nuova umida"
    if prp > 0.3 and rain > 0:
        return "Bagnata / pioggia"
    if t <= -7:
        return "Molto fredda e secca"
    if -7 < t <= -3:
        return "Fredda e asciutta"
    if -3 < t < -0.3:
        return "Compatta / trasformata"
    if -0.3 <= t <= 0.2:
        return "Umida prossima a 0°"
    if t > 0.2:
        return "Molle / primaverile"
    return "Variabile"

def reliability_score(df_slice, horizon_hours):
    # più affidabile: poco prp, poco vento, vicino nel tempo
    if df_slice.empty: return 40
    var_t = float(df_slice["T2m"].std() or 0)
    var_p = float(df_slice["prp_mmph"].std() or 0)
    wind_m = float(df_slice["wind"].mean() or 0)
    prp_m = float(df_slice["prp_mmph"].mean() or 0)
    base = 85
    base -= min(var_t*6, 20)
    base -= min(var_p*8, 20)
    base -= min(wind_m*2.5, 15)
    base -= min(max(horizon_hours-24,0)/2.0, 15)
    base -= 10 if prp_m>0.5 else 0
    return int(np.clip(base, 35, 95))

def glide_index(df_slice):
    # 0–100 (più alto = più scorrevole)
    # euristica: migliore tra -9° e -1.5°, non bagnato, poco prp; penalizza vento alto, RH altissima con T>0
    if df_slice.empty: return 50
    t = float(df_slice["T_surf"].mean())
    prp = float(df_slice["prp_mmph"].mean())
    wind = float(df_slice["wind"].mean())
    rh = float(df_slice["RH"].mean())

    # temperature bell-shaped
    peak = -4.5
    width = 5.0
    temp_score = 100*np.exp(-((t-peak)**2)/(2*width**2))
    temp_score = np.clip(temp_score, 25, 100)

    prp_pen = np.clip(prp*18, 0, 25)
    wind_pen = np.clip((wind-4)*4, 0, 18)
    wet_pen = 18 if (t>-0.2 and rh>92 and prp>0.1) else 0

    score = temp_score - prp_pen - wind_pen - wet_pen
    return int(np.clip(score, 5, 98))

# ------------------------ WAX BANDS (8 brands) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
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

# ------------------------ STRUCTURE & EDGES (names only) ------------------------
# Manteniamo i nomi chiesti: Linear Fine (S1) · Thumb Print (S2) · Wave (S2) · Cross Hatch (S1)
def structure_for(t_surf):
    if t_surf <= -10:   return "Linear Fine (S1)"
    if t_surf <= -3:    return "Cross Hatch (S1) / Wave (S2) leggera"
    if t_surf <= -0.5:  return "Wave (S2) / Thumb Print (S2) moderata"
    if t_surf <= 0.5:   return "Thumb Print (S2)"
    return "Thumb Print (S2) / Wave (S2) marcata"

def edges_for(t_surf, discipline):
    # SIDE angles requested: show 88.5/88/87.5/87 depending on discipline & temp
    if t_surf <= -10:
        base = 0.5; sides = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}
    elif t_surf <= -3:
        base = 0.7; sides = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}
    else:
        base = 0.8 if t_surf<=0.5 else 1.0
        sides = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}
    return sides.get(discipline,88.0), base

# ------------------------ RUN ------------------------
st.markdown("#### 3) Dati meteo & calcolo")
go = st.button("Scarica/aggiorna previsioni", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        # Vista tabellare pulita
        show = res.copy()
        show["time"] = pd.to_datetime(show["time"])
        cols = ["time","T2m","td","RH","T_surf","T_top5","prp_mmph","snowfall","rain","cloud","wind","prp_type","sunup"]
        show = show[cols]
        show = show.rename(columns={
            "time":"Ora locale","T2m":"T aria (°C)","td":"T rugiada (°C)","RH":"UR (%)",
            "T_surf":"T superficie (°C)","T_top5":"T top 5mm (°C)","prp_mmph":"Prp (mm/h)",
            "snowfall":"Neve (mm/h)","rain":"Pioggia (mm/h)","cloud":"Nuvolosità (0–1)","wind":"Vento 10m (m/s)",
            "prp_type":"Tipo prp","sunup":"Giorno(1)/Notte(0)"
        })
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("**Tabella previsioni (pulita)**")
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Grafici essenziali
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T superficie"); plt.plot(t,res["T_top5"],label="T top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # Blocchi A/B/C con banner condizione + affidabilità + indice scorrevolezza
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"### Blocco {L} — {day.strftime('%a %d %b')}")
            W = window_slice(res, "Europe/Rome", day, s, e)
            if W.empty:
                st.info("Nessun dato per la finestra scelta.")
                continue

            t_med = float(W["T_surf"].mean())
            humidity = float(W["RH"].mean())
            prp_m = float(W["prp_mmph"].mean())
            cond = snow_condition_row(W.iloc[int(len(W)/2)])
            rel = reliability_score(W, horizon_hours=(pd.to_datetime(W["time"]).max() - pd.Timestamp.now()).total_seconds()/3600.0)
            glide = glide_index(W)

            st.markdown(
                f"<div class='cond'><b>Condizione:</b> {cond} · "
                f"<b>T_surf medio:</b> {t_med:.1f}°C · <b>UR media:</b> {humidity:.0f}% · "
                f"<b>Prp media:</b> {prp_m:.2f} mm/h · "
                f"<b>Indice di scorrevolezza:</b> {glide}/100 · <b>Affidabilità:</b> {rel}%</div>",
                unsafe_allow_html=True
            )

            # WAX (8 brands)
            st.markdown("<div class='hr'></div>", unsafe_allow_html=True)
            st.markdown("**Sciolina consigliata (per T_surf medio):**")
            row1 = st.columns(4); row2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                row1[i].markdown(f"<div class='brand'><div style='font-weight:800;color:{PRIMARY}'>{brand}</div><div>{rec}</div></div>", unsafe_allow_html=True)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                row2[i].markdown(f"<div class='brand'><div style='font-weight:800;color:{PRIMARY}'>{brand}</div><div>{rec}</div></div>", unsafe_allow_html=True)

            # Struttura (names only) + Angoli per discipline
            st.markdown("<div class='hr'></div>", unsafe_allow_html=True)
            st.markdown(f"**Struttura consigliata:** {structure_for(t_med)}")
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = edges_for(t_med, d)
                rows.append([d, f"{side:.1f}°", f"{base:.1f}°"])
            df_edges = pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"])
            st.dataframe(df_edges, use_container_width=True, hide_index=True)

        # download CSV
        st.download_button("Scarica CSV completo", data=res.to_csv(index=False),
                           file_name="forecast_with_snowT.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
