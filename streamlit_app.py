# streamlit_app.py  — Telemark · Pro Wax & Tune (dark)
# Requisiti: streamlit, pandas, numpy, requests, python-dateutil, streamlit-searchbox (opzionale)
import os, math, base64, json, time as _time
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
from dateutil import tz

# ----------------------------- UI / THEME -----------------------------------
PRIMARY = "#06b6d4"    # ciano acceso
ACCENT  = "#f97316"    # arancio acceso
OK      = "#22c55e"
WARN    = "#f59e0b"
ERR     = "#ef4444"
MUTED   = "#9ca3af"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")

st.markdown(f"""
<style>
:root {{
  --primary: {PRIMARY};
  --accent:  {ACCENT};
}}
/* tema scuro pulito */
html, body, [data-testid="stAppViewContainer"] {{
  background: #0b0e14;
}}
h1,h2,h3,h4,h5 {{
  color: #ffffff;
  letter-spacing: .2px;
}}
p, label, .st-emotion-cache-17eq0hr, .st-emotion-cache-1cypcdb {{
  color: #e5e7eb!important;
}}
.small-muted {{ color:{MUTED}; font-size:.85rem }}
.badge {{
  display:inline-flex; gap:.5rem; align-items:center;
  background: #111827; border:1px solid #1f2937; color:#e5e7eb;
  padding:.35rem .6rem; border-radius:12px; font-weight:600;
}}
.pill {{
  display:inline-flex; padding:.15rem .45rem; border-radius:999px;
  font-size:.75rem; border:1px solid #374151;
}}
.hero {{
  background: radial-gradient(1100px 280px at 10% 0%, #0b0e14 0%, #111827 70%, #0b0e14 100%);
  border:1px solid #1f2937; border-radius:16px; padding:18px 16px; margin-bottom:6px;
}}
.banner {{
  background: #0b1220; border:1px solid #1f2a44; border-radius:14px; padding:10px 12px;
}}
.kpi {{
  display:flex; gap:.6rem; align-items:center; background:#0d1322; border:1px solid #1b2542;
  border-radius:12px; padding:.6rem .8rem; color:#e5e7eb; font-weight:600;
}}
.kpi .dot {{ width:10px; height:10px; border-radius:50% }}
hr {{ border:none; border-top:1px solid #1f2937; margin:.75rem 0 }}
.stDataFrame [data-testid="StyledTableContainer"] {{ border-radius:12px; overflow:hidden; }}
.st-emotion-cache-1xarl3l, .st-emotion-cache-qcpnpn {{ color:#e5e7eb!important; }}
.stSlider > div[data-baseweb="slider"] > div {{ color:#e5e7eb!important; }}
.stButton>button {{
  background: {ACCENT}; border:0; color:white; font-weight:700;
  transition: transform .06s ease; border-radius:12px; padding:.6rem 1rem;
}}
.stButton>button:hover {{ transform: translateY(-1px); filter:brightness(1.05)}}
.brand {{
  display:flex;align-items:center;gap:.6rem;background:#0b1220;border:1px solid #1b2542;
  border-radius:12px;padding:.5rem .7rem
}}
.brand img {{ height:22px }}
</style>
""", unsafe_allow_html=True)

# ----------------------------- HELPERS --------------------------------------
def flag(cc:str)->str:
    try:
        c = cc.upper(); return chr(127397+ord(c[0])) + chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

def nominatim_search(q:str, country:str|None):
    if not q or len(q)<2: return []
    params = {"q": q, "format":"json", "limit": 10, "addressdetails":1}
    if country and len(country)==2: params["countrycodes"] = country.lower()
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params=params, headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
    r.raise_for_status()
    out = []
    st.session_state._opts = {}
    for it in r.json():
        addr = it.get("address",{}) or {}
        lab = f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
        lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        st.session_state._opts[key] = {"lat":lat,"lon":lon,"label":lab,"addr":addr}
        out.append(key)
    return out

def get_elev(lat:float, lon:float)->float|None:
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); js = r.json()
        if js and "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except: pass
    return None

# ----------------------------- DATA SOURCES ---------------------------------
def fetch_open_meteo(lat, lon, tzname, start_day:date, hours:int):
    """Open-Meteo hourly forecast with dew point (for RH), snowfall, etc."""
    # ensure start is today midnight in tz
    tzinfo = tz.gettz(tzname) or timezone.utc
    start_dt = datetime.combine(start_day, time(0,0)).replace(tzinfo=tzinfo)
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,relative_humidity_2m,weathercode,is_day",
            "start_hour": start_dt.strftime("%Y-%m-%dT%H:%M"),
            "forecast_hours": hours
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

def fetch_noaa_obs(lat, lon, start_iso, end_iso, token:str):
    """
    NOAA CDO (GHCND) nearby station daily obs: snowfall (SNOW), snow depth (SNWD), precip (PRCP), TMAX/TMIN.
    We use it to weight confidence when recent obs contradict forecast.
    """
    try:
        # nearest station within 25km
        stations = requests.get(
            "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations",
            params={"datatypeid":"SNWD", "limit":3, "sortfield":"mindate",
                    "extent": f"{lat-0.25},{lon-0.25},{lat+0.25},{lon+0.25}"},
            headers={"token": token}, timeout=12
        ); stations.raise_for_status()
        sid = stations.json().get("results",[{}])[0].get("id",None)
        if not sid: return pd.DataFrame()
        resp = requests.get(
            "https://www.ncdc.noaa.gov/cdo-web/api/v2/data",
            params={"datasetid":"GHCND","stationid":sid,"startdate":start_iso,"enddate":end_iso,
                    "datatypeid":"PRCP,SNWD,SNOW,TMAX,TMIN", "units":"metric", "limit":1000},
            headers={"token": token}, timeout=12
        )
        resp.raise_for_status()
        rows = resp.json().get("results",[])
        if not rows: return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df.pivot_table(index="date", columns="datatype", values="value", aggfunc="mean").reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(None).dt.date
        return df
    except Exception:
        return pd.DataFrame()

# ----------------------------- SNOW PHYSICS ---------------------------------
def rh_from_T_Td(T, Td):
    """Relative humidity (%) from T (°C) and Td (°C) via Magnus formula."""
    # Avoid NaNs
    T = np.array(T, dtype=float); Td = np.array(Td, dtype=float)
    a, b = 17.625, 243.04
    es  = 6.1094*np.exp((a*T)/(b+T))
    e   = 6.1094*np.exp((a*Td)/(b+Td))
    RH  = np.clip(100.0*e/np.maximum(es,1e-6), 0, 100)
    return RH

def classify_precip(row):
    """Type from rain/snowfall and code."""
    rain = float(row.get("rain",0) or 0)
    snow = float(row.get("snowfall",0) or 0)
    code = int(row.get("weathercode",0) or 0)
    if (snow>0 and rain>0) or code in {66,67,68,69,79}: return "mixed"
    if snow>0 or code in {71,73,75,77,85,86}: return "snow"
    if rain>0 or code in {51,53,55,61,63,65,80,81,82}: return "rain"
    return "none"

def snow_surface_temperature(T2m, Td, cloud, wind, prp_type, snowfall):
    """
    Heuristic energy balance for surface skin:
    - Wet / precip or near 0°C -> clamp to 0
    - Otherwise radiative-cooling under clear sky and weak wind
    """
    T2m = float(T2m); Td=float(Td); cloud=float(cloud); wind=float(wind)
    wet = (prp_type in ("rain","mixed")) or (T2m > -0.5 and snowfall>0)
    if wet: return 0.0
    # radiative deficit: stronger cooling with clear sky, low RH, low wind
    rh = rh_from_T_Td(T2m, Td)
    clear = 1.0 - cloud/100.0
    rad_cool = 2.0 + 5.0*clear + 0.02*(100-rh) - 0.4*min(wind,6.0)
    Ts = T2m - np.clip(rad_cool, 0.7, 7.0)
    # sunny daytime on cold dry snow: small compensation
    return float(Ts)

def top_layer_temperature(prev_Ttop, Ts, wind, snowfall, sunup):
    """
    0–5 mm top-layer relaxation toward Ts with time constant dependent on wind/snow.
    """
    tau = 5.0  # default hours
    if wind >= 6 or snowfall > 0: tau = 2.5
    if (not sunup) and wind < 2:  tau = 7.5
    alpha = 1.0 - math.exp(-1.0/tau)
    if prev_Ttop is None: return min(0.0, Ts)
    return float(prev_Ttop + alpha*(Ts - prev_Ttop))

def snow_consistency(Ts, Ttop, snowfall_mmph, rh, wind):
    """
    Classify snow grains / wetness:
    - fresh/new, packed, transformed, wet/very-wet, icy.
    """
    wetness = 0.0
    if Ts >= -0.3 or Ttop >= -0.3: wetness += 0.6
    if rh >= 95 and Ts > -1.0:      wetness += 0.2
    if snowfall_mmph >= 0.3:        wetness = max(wetness-0.3, 0.0)  # new snow offsets wetness
    if wind >= 10:                  wetness = max(wetness-0.1, 0.0)
    # map to label
    if snowfall_mmph >= 0.3 and Ts <= -0.3: return "neve nuova", 0.75
    if wetness >= 0.9: return "molto bagnata", 0.6
    if 0.55 <= wetness < 0.9: return "bagnata/primaverile", 0.65
    if -2.5 <= Ts < -0.3: return "compatta/trasformata", 0.7
    if Ts < -2.5: return "fredda/secca", 0.7
    return "granulosa/variabile", 0.55

def glide_index(Ts, Ttop, snow_type, prp_type, wind):
    """
    Indice di scorrevolezza 0–100:
    - penalizzato da neve fresca a T<<0 (alta micro-aspereza)
    - massimo vicino a 0°C con umidità e acqua libera moderata
    - penalità per vento forte (inquinamento/raffreddamento)
    """
    base = 50.0
    # gain per vicinanza allo zero
    near0 = np.exp(-((Ttop - (-0.2))**2)/2.2) * 35.0   # picco intorno -0.2°C
    base += near0
    # penalità neve nuova/fredda
    if snow_type in ("neve nuova","fredda/secca"): base -= 12
    if snow_type == "bagnata/primaverile": base += 6
    if prp_type == "rain": base -= 4
    base -= np.clip(max(0, wind-8)*0.8, 0, 10)
    return float(np.clip(base, 5, 98))

# ----------------------------- WAX BRANDS ------------------------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix","assets/brands/swix.png",SWIX),("Toko","assets/brands/toko.png",TOKO),
          ("Vola","assets/brands/vola.png",VOLA),("Rode","assets/brands/rode.png",RODE),
          ("Holmenkol","assets/brands/holmenkol.png",HOLM),("Maplus","assets/brands/maplus.png",MAPL),
          ("Start","assets/brands/start.png",START),("Skigo","assets/brands/skigo.png",SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ----------------------------- APP ------------------------------------------
st.markdown("<div class='hero'><div class='badge'>❄️ Telemark · Pro Wax & Tune</div><div class='small-muted'>Analisi neve pro con previsioni meteo e raccomandazioni tuning</div></div>", unsafe_allow_html=True)

# --- Ricerca località con prefiltro Paese ---
st.subheader("1) Località")
cA, cB = st.columns([1,3])
with cA:
    country = st.text_input("Paese (codice ISO-2, es. IT, FR, CH)", value=st.session_state.get("country","IT"))
    st.session_state["country"] = country.strip().upper()[:2] if country else ""
with cB:
    q = st.text_input("Cerca località (premi Invio)", placeholder="Champoluc, Plateau Rosa, Cervinia…")
    selected = None
    if q:
        try:
            options = nominatim_search(q, st.session_state.get("country",""))
            selected = options[0] if options else None
        except Exception:
            selected = None

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
label = st.session_state.get("label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    if info:
        lat, lon, label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["label"]=label

elev = get_elev(lat,lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='banner'>📍 <b>{label}</b>{alt_txt}</div>", unsafe_allow_html=True)

# --- Finestre e giorno ---
st.subheader("2) Finestre & giorno")
c1,c2,c3,c4 = st.columns(4)
with c1:
    A_s = st.time_input("Inizio A", value=time(9,0))
    A_e = st.time_input("Fine A",   value=time(11,0))
with c2:
    B_s = st.time_input("Inizio B", value=time(11,0))
    B_e = st.time_input("Fine B",   value=time(13,0))
with c3:
    C_s = st.time_input("Inizio C", value=time(13,0))
    C_e = st.time_input("Fine C",   value=time(16,0))
with c4:
    target_day = st.date_input("Giorno", value=date.today())
# orizzonte ore (max 168); lo usiamo anche per tagliare al giorno scelto
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)

# --- Meteo & calcolo ---
st.subheader("3) Meteo & Analisi neve")
if st.button("Scarica & calcola", type="primary", use_container_width=True):
    try:
        tzname = "Europe/Rome"  # fisso: togliamo timezone toggle
        meta = fetch_open_meteo(lat, lon, tzname, target_day, hours)
        H = pd.DataFrame(meta["hourly"])
        H["time"] = pd.to_datetime(H["time"])  # tz-naive già allineate al tz richiesto
        # taglio all'orizzonte richiesto
        now_ref = pd.Timestamp(datetime.combine(target_day, time(0,0)))
        H = H[H["time"] >= now_ref].head(hours).reset_index(drop=True)

        # umidità: usa quella di OM se presente; altrimenti calcola da T e Td
        if "relative_humidity_2m" in H.columns and H["relative_humidity_2m"].notna().any():
            RH = H["relative_humidity_2m"].astype(float).clip(0,100).values
        else:
            RH = rh_from_T_Td(H["temperature_2m"].astype(float), H["dew_point_2m"].astype(float))
        # preprocess
        df = pd.DataFrame({
            "time": H["time"],
            "T2m": H["temperature_2m"].astype(float).values,
            "Td": H["dew_point_2m"].astype(float).values,
            "RH": RH,
            "cloud": H["cloudcover"].astype(float).values,
            "wind": (H["windspeed_10m"].astype(float)/3.6).values, # m/s
            "rain": H.get("rain", pd.Series([0]*len(H))).astype(float).values,
            "snowfall": H.get("snowfall", pd.Series([0]*len(H))).astype(float).values,
            "is_day": H.get("is_day", pd.Series([1]*len(H))).astype(int).values,
            "weathercode": H.get("weathercode", pd.Series([0]*len(H))).astype(int).values,
            "precipitation": H.get("precipitation", pd.Series([0]*len(H))).astype(float).values
        })

        # class precip
        df["prp_type"] = [classify_precip(r) for r in df.to_dict("records")]

        # surface & top layer temps
        Ts = []
        Ttop = []
        prev_top = None
        for i,row in df.iterrows():
            ts = snow_surface_temperature(row.T2m, row.Td, row.cloud, row.wind, row.prp_type, row.snowfall)
            Ts.append(ts)
            top = top_layer_temperature(prev_top, ts, row.wind, row.snowfall, bool(row.is_day))
            Ttop.append(top); prev_top = top
        df["T_surf"] = np.array(Ts)
        df["T_top5mm"] = np.array(Ttop)

        # snow type & confidence
        s_types, confs, glide = [], [], []
        for i,row in df.iterrows():
            stype, base_conf = snow_consistency(row.T_surf, row.T_top5mm, row.snowfall, row.RH, row.wind)
            s_types.append(stype)
            # blend con dati NOAA ultimi 3 giorni (se disponibili)
            noaa_token = os.environ.get("NOAA_TOKEN","").strip()
            extra_boost = 0.0
            if noaa_token and i==0:  # chiama una volta per pagina
                endD = date.today(); startD = endD - timedelta(days=3)
                NOAA = fetch_noaa_obs(lat, lon, startD.isoformat(), endD.isoformat(), noaa_token)
                if not NOAA.empty:
                    # se SNWD>0 ma forecast 'rain', abbassiamo conf; se SNOW>0 recente, alziamo conf su "neve nuova"
                    last = NOAA.sort_values("date").iloc[-1]
                    if (last.get("SNOW",0) or 0) > 3: extra_boost += 0.1
                    if (last.get("SNWD",0) or 0) > 15 and row.prp_type=="rain": extra_boost -= 0.15
            conf = np.clip(base_conf + extra_boost, 0.45, 0.9)
            confs.append(conf)
            glide.append(glide_index(row.T_surf, row.T_top5mm, stype, row.prp_type, row.wind))
        df["snow_type"] = s_types
        df["confidence"] = confs
        df["glide_index"] = glide

        # vista tabellare (pulita)
        nice = df.copy()
        nice.rename(columns={
            "time":"Ora", "T2m":"T aria (°C)", "Td":"Td (°C)", "RH":"UR (%)",
            "cloud":"Nubi (%)", "wind":"Vento (m/s)","precipitation":"Prp (mm/h)",
            "snowfall":"Neve (mm/h)", "prp_type":"Tipo prp", "T_surf":"T superficie (°C)",
            "T_top5mm":"T top 5mm (°C)", "snow_type":"Neve", "confidence":"Affidabilità",
            "glide_index":"Indice di scorrevolezza"
        }, inplace=True)
        show_cols = ["Ora","T aria (°C)","Td (°C)","UR (%)","Nubi (%)","Vento (m/s)","Prp (mm/h)","Neve (mm/h)",
                     "Tipo prp","T superficie (°C)","T top 5mm (°C)","Neve","Indice di scorrevolezza","Affidabilità"]
        st.dataframe(nice[show_cols].style
                     .format({"T aria (°C)":"{:.1f}","Td (°C)":"{:.1f}","UR (%)":"{:.0f}",
                              "Nubi (%)":"{:.0f}","Vento (m/s)":"{:.1f}","Prp (mm/h)":"{:.1f}",
                              "Neve (mm/h)":"{:.1f}","T superficie (°C)":"{:.1f}","T top 5mm (°C)":"{:.1f}",
                              "Indice di scorrevolezza":"{:.0f}","Affidabilità":"{:.0%}"}),
                     use_container_width=True, height=420)

        # blocchi A/B/C
        st.markdown("----")
        blocks = {"A":(A_s,A_e),"B":(B_s,B_e),"C":(C_s,C_e)}
        def slice_block(s,e):
            mask = (df["time"].dt.time>=s) & (df["time"].dt.time<=e)
            sub = df[mask]
            return sub if not sub.empty else df.head(6)

        for L,(s,e) in blocks.items():
            sub = slice_block(s,e)
            tmed = float(sub["T_surf"].mean())
            gmed = float(sub["glide_index"].mean())
            snow_mode = sub["snow_type"].mode().iat[0] if not sub.empty else "n/d"
            conf = float(sub["confidence"].mean())
            # banner risultato
            col1,col2,col3,col4 = st.columns([2,1,1,1])
            with col1:
                st.markdown(f"### Blocco {L}")
                st.markdown(f"<div class='kpi'><div class='dot' style='background:{OK}'></div>Condizione: <b>{snow_mode}</b> · T_surf med.: <b>{tmed:.1f}°C</b></div>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"<div class='kpi'><div class='dot' style='background:{ACCENT}'></div>Scorrevolezza<br><b>{gmed:.0f}/100</b></div>", unsafe_allow_html=True)
            with col3:
                st.markdown(f"<div class='kpi'><div class='dot' style='background:{PRIMARY}'></div>Affidabilità<br><b>{conf:.0%}</b></div>", unsafe_allow_html=True)
            with col4:
                st.markdown(f"<div class='kpi'><div class='dot' style='background:#eab308'></div>Ore dati<br><b>{len(sub)}</b></div>", unsafe_allow_html=True)

            # Raccomandazioni sciolina per marchi (in due righe)
            brands1 = st.columns(4); brands2 = st.columns(4)
            rows = [brands1, brands2]
            Tref = tmed
            for i,(name,logo,bands) in enumerate(BRANDS):
                rec = pick_wax(bands, Tref)
                container = rows[i//4][i%4]
                # logo se presente
                if os.path.exists(logo):
                    b64 = base64.b64encode(open(logo,"rb").read()).decode("utf-8")
                    html_logo = f"<img src='data:image/png;base64,{b64}'/>"
                else:
                    html_logo = f"<div style='font-weight:700'>{name}</div>"
                container.markdown(f"<div class='brand'>{html_logo}<div><div class='small-muted'>{name}</div><div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True)

            # Struttura: solo nomi (come richiesto)
            def structure_name(t):
                if t<=-10: return "Linear Fine (S1)"
                if t<=-3:  return "Cross Hatch (S1) / Thumb Print (S2)"
                return "Wave (S2) / Diagonal (S1)"
            st.markdown(f"<span class='pill'>Struttura consigliata: <b>&nbsp;{structure_name(Tref)}&nbsp;</b></span>", unsafe_allow_html=True)
            st.markdown("")

        # download CSV
        st.download_button("Scarica CSV completo", data=df.to_csv(index=False), file_name="telemark_meteo_neve.csv", mime="text/csv", use_container_width=True)

    except Exception as e:
        st.error(f"Errore: {e}")
