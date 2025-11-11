# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark, cached, robust fetch, i18n, units toggle, lead-time, alerts, PDF report, map, validation

import os, math, base64, requests, pandas as pd, numpy as np, io, time, json
import streamlit as st
from datetime import datetime, date, time as dtime, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox
import matplotlib
matplotlib.use("Agg")  # <-- backend sicuro per Streamlit
import matplotlib.pyplot as plt

# ---------------------- THEME (dark) ----------------------
PRIMARY = "#06b6d4"; ACCENT  = "#f97316"; OK = "#10b981"; WARN = "#f59e0b"; ERR = "#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: 0.6rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing: .2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{ display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }}
.card {{ background: var(--panel); border:1px solid var(--line); border-radius:12px; padding: .9rem .95rem; }}
.banner {{ border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0; padding:.75rem .9rem; border-radius:10px; font-size:.98rem; }}
.brand {{ display:flex; align-items:flex-start; gap:.65rem; background:#0e141d; border:1px solid #1e2a3a; border-radius:10px; padding:.75rem .8rem; width:100% }}
.brand h4 {{ margin:0 0 .25rem 0; font-size:1rem; color:#fff }}
.brand .muted {{ color:#a9bacb }}
.brand .sub {{ color:#93b2c6; font-size:.85rem }}
.brand .logo {{ flex:0 0 auto; display:flex; align-items:center; justify-content:center; width:54px; height:54px; background:#0b121a; border:1px solid #1e2a3a; border-radius:10px; overflow:hidden }}
.brand .logo img {{ max-width:52px; max-height:52px; display:block }}
.grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:.6rem; }}
.tune ul {{ margin:.5px 0 0 1rem; padding:0; }}
.small {{ font-size:.85rem; color:#cbd5e1 }}
.badge-red {{ border-left:6px solid {ERR}; background:#2a1518; color:#fee2e2; padding:.6rem .8rem; border-radius:10px; }}
/* Assicura che i controlli Leaflet restino cliccabili sopra i layer */
.leaflet-control {{ z-index: 1000 !important; }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# ---------------------- I18N + UNITS ----------------------
L = {
    "it": {
        "country":"Nazione (prefiltro ricerca)",
        "search_ph":"Cerca… es. Champoluc, Plateau Rosa",
        "ref_day":"Giorno di riferimento",
        "alt_lbl":"Altitudine pista/garà (m)",
        "blocks":"1) Finestre orarie A · B · C",
        "start":"Inizio", "end":"Fine",
        "horizon":"2) Orizzonte previsionale",
        "tip":"Suggerimento: < 48h → stime più affidabili",
        "fetch":"Scarica/aggiorna previsioni",
        "temp":"Temperature",
        "prec":"Precipitazione (mm/h)",
        "radhum":"Radiazione stimata & Umidità",
        "cond":"Condizioni previste:",
        "none":"—","rain":"pioggia","snow":"neve","mixed":"mista",
        "struct":"Struttura consigliata:",
        "waxes":"Scioline suggerite:",
        "nodata":"Nessun dato nella finestra scelta.",
        "t_air":"T aria (°C)","td":"Td (°C)","rh":"UR (%)","tw":"Tw (°C)",
        "we":"Vento eff (m/s)","cloud":"Nuvolosità (%)","sw":"SW↓ (W/m²)",
        "prp":"Prp (mm/h)","ptype":"Tipo prp",
        "t_surf":"T neve surf (°C)","t_top5":"T top5mm (°C)","lw":"H₂O liquida (%)",
        "speed":"Indice scorrevolezza","hour":"Ora","lead":"⟲ lead time (h)",
        "download_csv":"Scarica CSV completo",
        "reset":"Reset",
        "last_upd":"Ultimo aggiornamento",
        "status_title":"Download & calcolo",
        "invalid_win":"La finestra {lbl} ha orari invertiti (inizio ≥ fine). Correggi per continuare.",
        "low_alt":"Quota pista molto bassa (< 300 m): controlla che sia corretta.",
        "alert":"Attenzione: condizioni molto umide/calde in finestra {lbl}. Preferire forma liquida/topcoat.",
        "offset":"Calibrazione pista (offset termico °C)",
        "speed_chart":"Indice scorrevolezza (mini)",
        "lang":"Lingua","unit":"Unità","unit_c":"°C / m/s","unit_f":"°F / km/h",
        "map":"Mappa (selezione)",
        "base_solid":"Base solida",
        "topcoat_lbl":"Topcoat",
        "debug":"Mostra debug"
    },
    "en": {
        "country":"Country (search prefilter)",
        "search_ph":"Search… e.g. Champoluc, Plateau Rosa",
        "ref_day":"Reference day",
        "alt_lbl":"Slope/race altitude (m)",
        "blocks":"1) Time windows A · B · C",
        "start":"Start", "end":"End",
        "horizon":"2) Forecast horizon",
        "tip":"Tip: < 48h → more reliable",
        "fetch":"Fetch/update forecast",
        "temp":"Temperatures",
        "prec":"Precipitation (mm/h)",
        "radhum":"Estimated radiation & Humidity",
        "cond":"Expected conditions:",
        "none":"—","rain":"rain","snow":"snow","mixed":"mixed",
        "struct":"Recommended structure:",
        "waxes":"Suggested waxes:",
        "nodata":"No data in selected window.",
        "t_air":"Air T (°C)","td":"Td (°C)","rh":"RH (%)","tw":"Wet-bulb (°C)",
        "we":"Eff. wind (m/s)","cloud":"Cloudiness (%)","sw":"SW↓ (W/m²)",
        "prp":"Prp (mm/h)","ptype":"Prp type",
        "t_surf":"Snow T surf (°C)","t_top5":"Top 5mm (°C)","lw":"Liquid water (%)",
        "speed":"Speed index","hour":"Hour","lead":"⟲ lead time (h)",
        "download_csv":"Download full CSV",
        "reset":"Reset",
        "last_upd":"Last update",
        "status_title":"Download & compute",
        "invalid_win":"Window {lbl} has inverted times (start ≥ end). Fix to continue.",
        "low_alt":"Very low slope altitude (< 300 m): double-check.",
        "alert":"Warning: very warm/humid conditions in {lbl}. Prefer liquid/topcoat.",
        "offset":"Track calibration (thermal offset °C)",
        "speed_chart":"Speed index (mini)",
        "lang":"Language","unit":"Units","unit_c":"°C / m/s","unit_f":"°F / km/h",
        "map":"Map (selection)",
        "base_solid":"Base solid",
        "topcoat_lbl":"Topcoat",
        "debug":"Show debug"
    }
}

# UI state: language & units
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang=="IT" else L["en"]
units = st.sidebar.radio(T["unit"], [T["unit_c"], T["unit_f"]], index=0, horizontal=False)
use_fahrenheit = (units==T["unit_f"])
show_debug = st.sidebar.checkbox(T["debug"], value=False)

# ---------------------- UTILS ----------------------
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

def c_to_f(x): return x*9/5+32
def ms_to_kmh(x): return x*3.6

def rh_from_t_td(Tv, Td):
    Tv = np.array(Tv, dtype=float); Td = np.array(Td, dtype=float)
    a,b = 17.625, 243.04
    es  = 6.1094 * np.exp((a*Tv)/(b+Tv))
    e   = 6.1094 * np.exp((a*Td)/(b+Td))
    RH  = 100.0 * (e / es)
    return np.clip(RH, 1, 100)

def wetbulb_stull(Tv, RH):
    RH = np.clip(RH, 1, 100)
    Tw = Tv * np.arctan(0.151977 * (RH + 8.313659)**0.5) + np.arctan(Tv + RH) - np.arctan(RH - 1.676331) + 0.00391838 * (RH**1.5) * np.arctan(0.023101*RH) - 4.686035
    return Tw

def solar_declination(day_of_year):
    return 23.45 * math.pi/180 * math.sin(2*math.pi*(284+day_of_year)/365)

def solar_geometry(lat, lon, ts_utc):
    latr = math.radians(lat)
    frac_day = (ts_utc.hour + ts_utc.minute/60) + lon/15
    H = math.radians(15*(frac_day - 12))
    delta = solar_declination(ts_utc.timetuple().tm_yday)
    cosz = math.sin(latr)*math.sin(delta) + math.cos(latr)*math.cos(delta)*math.cos(H)
    return max(0.0, cosz)

def clear_sky_ghi(lat, lon, ts_utc):
    S0 = 1361.0
    cosz = solar_geometry(lat, lon, ts_utc)
    ghi_clear = S0 * cosz * 0.75
    return max(0.0, ghi_clear)

def effective_wind(w):
    w = np.clip(w, 0, 8.0)
    return 8.0 * (np.log1p(w) / np.log1p(8.0))

# ---------------------- Helpers: robust fetch with retry ----------------------
UA = {"User-Agent":"telemark-wax-pro/1.0"}
def _retry(func, attempts=2, sleep=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i==attempts-1: raise
            time.sleep(sleep*(1.5**i))

# ---------------------- SEARCH with COUNTRY prefilter ----------------------
COUNTRIES = {"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
col_top = st.columns([2,1,1,1])
with col_top[1]:
    sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
    iso2 = COUNTRIES[sel_country]
with col_top[2]:
    offset = st.slider(T["offset"], -1.5, 1.5, 0.0, 0.1, key="cal_offset")
with col_top[3]:
    if st.button(T["reset"], use_container_width=True):
        for k in ["A_s","A_e","B_s","B_e","C_s","C_e","place","lat","lon","place_label","hours","country_sel","cal_offset","ref_day","alt_m"]:
            if k in st.session_state: del st.session_state[k]
        st.rerun()

with col_top[0]:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            def go():
                return requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q":q, "format":"json", "limit":12, "addressdetails":1, "countrycodes": iso2.lower()},
                    headers=UA, timeout=8
                )
            r = _retry(go); r.raise_for_status()
            st.session_state._options = {}
            out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab = concise_label(addr, it.get("display_name",""))
                cc = addr.get("country_code","")
                lab = f"{flag(cc)}  {lab}"
                lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
                key = f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key] = {"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            return out
        except:
            return []

    selected = st_searchbox(nominatim_search, key="place", placeholder=T["search_ph"], clear_on_submit=False, default=None)

# ---------------------- Cached services ----------------------
@st.cache_data(ttl=60*10, show_spinner=False)
def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone="UTC",
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7,
        ),
        headers=UA, timeout=30
    )
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=24*3600, show_spinner=False)
def get_elev(lat,lon):
    rr = requests.get("https://api.open-meteo.com/v1/elevation", params={"latitude":lat, "longitude":lon}, headers=UA, timeout=8)
    rr.raise_for_status(); js = rr.json()
    return float(js["elevation"][0]) if js and "elevation" in js else None

@st.cache_data(ttl=12*3600, show_spinner=False)
def detect_timezone(lat, lon):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude":lat,"longitude":lon,"hourly":"temperature_2m","forecast_days":1,"timezone":"auto"}, headers=UA, timeout=10)
    r.raise_for_status()
    return r.json().get("timezone","Europe/Rome")

# ---------------------- NOAA (optional robust bias) ----------------------
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_nearby_station(lat, lon, radius_m=25000, limit=3):
    if not NOAA_TOKEN: return []
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/stations",
        params={"datasetid":"GHCND","limit":limit,"sortfield":"distance","latitude":lat,"longitude":lon,"radius":radius_m},
        headers={"token": NOAA_TOKEN, **UA}, timeout=10)
    j = r.json()
    return (j.get("results") or [])

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_normals_dly(station_id):
    if not NOAA_TOKEN: return {}
    params = {"datasetid":"NORMAL_DLY","stationid":station_id,"datatypeid":["DLY-TAVG-NORMAL","DLY-PRCP-PCTALL-GE001HI"],"startdate":"2010-01-01","enddate":"2010-12-31","limit":1000}
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/data", params=params, headers={"token": NOAA_TOKEN, **UA}, timeout=12)
    j = r.json()
    vals = j.get("results") or []
    out = {}
    for rec in vals:
        dt = rec.get("date",""); mmdd = dt[5:10]
        dtype = rec.get("datatype"); val = rec.get("value")
        if val is None: continue
        out.setdefault(dtype, {})[mmdd] = val
    return out

def noaa_bias_correction(df, lat, lon):
    if not NOAA_TOKEN: return df
    try:
        stns = _noaa_nearby_station(lat, lon)
        if not stns: return df
        sid = stns[0]["id"]
        normals = _noaa_normals_dly(sid)
        df2 = df.copy()
        if not normals:
            df2["T2m"] = df2["T2m"] + np.sign(0 - df2["T2m"])*0.3
            df2["RH"]  = np.where(np.isnan(df2["RH"]), 70.0, df2["RH"])
            df2["RH"]  = df2["RH"] + (70 - df2["RH"])*0.03
            return df2
        now = datetime.utcnow().date(); mmdd = now.strftime("%m-%d")
        tnorm_raw = normals.get("DLY-TAVG-NORMAL", {}).get(mmdd, None)
        tnorm = float(tnorm_raw)/10.0 if tnorm_raw is not None else None
        prp_pct = normals.get("DLY-PRCP-PCTALL-GE001HI", {}).get(mmdd, None)
        if prp_pct is not None: prp_pct = float(prp_pct)
        if tnorm is not None:
            med_model = float(np.nanmedian(df2["T2m"].values))
            bias = tnorm - med_model
            adj = np.clip(0.5*bias, -1.2, 1.2)
            df2["T2m"] = df2["T2m"] + adj
            df2["td"]  = df2["td"]  + adj
        df2["RH"]  = np.where(np.isnan(df2["RH"]), 70.0, df2["RH"])
        df2["RH"]  = np.clip(df2["RH"] + (70 - df2["RH"])*0.03, 1, 100)
        if prp_pct is not None and prp_pct >= 60:
            df2["prp_mmph"] *= 1.10
            df2["rain"]     *= 1.10
            df2["snowfall"] *= 1.10
        return df2
    except Exception:
        return df

# ---------------------- DATE & WINDOWS + DOWNSCALING ALT ----------------------
def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"], utc=True)  # tz-aware UTC
    now0 = pd.Timestamp.now(tz="UTC").floor("H")
    df = df[df["time"] >= now0].head(int(hours)).reset_index(drop=True)

    out = pd.DataFrame()
    out["time_utc"] = df["time"]
    out["T2m"] = df["temperature_2m"].astype(float)
    out["RH"] = df["relative_humidity_2m"].astype(float) if "relative_humidity_2m" in df else np.full(len(df), np.nan)
    out["td"] = (df["dew_point_2m"].astype(float) if "dew_point_2m" in df else out["T2m"].astype(float))
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1) if "cloudcover" in df else np.zeros(len(df))
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6) if "windspeed_10m" in df else np.zeros(len(df))  # m/s
    out["sunup"] = df["is_day"].astype(int) if "is_day" in df else np.zeros(len(df), dtype=int)
    out["prp_mmph"] = df["precipitation"].astype(float) if "precipitation" in df else np.zeros(len(df))
    out["rain"] = df["rain"].astype(float) if "rain" in df else np.zeros(len(df))
    out["snowfall"] = df["snowfall"].astype(float) if "snowfall" in df else np.zeros(len(df))
    out["wcode"] = df["weathercode"].astype(int) if "weathercode" in df else np.zeros(len(df), dtype=int)
    out["lead_h"] = ((out["time_utc"] - now0).dt.total_seconds()/3600.0).round(1)
    return out

def prp_type_row(row):
    if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

def lapse_correction(Tv, base_alt, target_alt, lapse=-6.5):
    dz = (target_alt - (base_alt or target_alt))
    return Tv + (lapse/1000.0) * dz

def enrich_meteo_quickwins(df, lat, lon, base_alt, target_alt):
    X = df.copy()
    if X["RH"].isna().any():
        X.loc[:, "RH"] = rh_from_t_td(X["T2m"], X["td"])
    X["Tw"] = wetbulb_stull(X["T2m"], X["RH"])
    X["wind_eff"] = effective_wind(X["wind"])
    sw_list = []
    for ts in X["time_utc"]:
        sw_clear = clear_sky_ghi(lat, lon, ts.to_pydatetime())
        sw_list.append(sw_clear)
    X["SW_clear"] = sw_list
    X["SW_down"] = X["SW_clear"] * (1 - 0.75*(X["cloud"]**3))
    snow_mask = X["snowfall"] > 0.5
    last_snow_idx = -1; age_hours = []
    for i, s in enumerate(snow_mask):
        if s: last_snow_idx = i
        age_hours.append(999 if last_snow_idx<0 else (i-last_snow_idx))
    X["snow_age_h"] = age_hours
    alb = 0.85 - 0.30 * np.clip(X["snow_age_h"]/48.0, 0, 1)
    hot = X["T2m"] > 0
    alb = np.where(hot, alb - 0.05, alb)
    X["albedo"] = np.clip(alb, 0.45, 0.90)
    if target_alt and base_alt:
        X["T2m"] = lapse_correction(X["T2m"], base_alt, target_alt)
        X["td"]  = lapse_correction(X["td"],  base_alt, target_alt)
        X["RH"]  = rh_from_t_td(X["T2m"], X["td"])
        X["Tw"]  = wetbulb_stull(X["T2m"], X["RH"])
    return X

def snow_temperature_model(X: pd.DataFrame, dt_hours=1.0):
    X = X.copy()
    X["ptyp"] = X.apply(prp_type_row, axis=1)
    wet = ((X["ptyp"].isin(["rain","mixed"])) |
           ( (X["ptyp"]=="snow") & (X["T2m"]>-0.5) & (X["RH"]>90) ) |
           ( (X["SW_down"]>250) & (X["T2m"]>-1.0) ) | (X["T2m"]>0.5))
    conv = 0.20 * X["wind_eff"]
    rad_cool = (0.8 * (1.0 - X["cloud"]))
    sw_gain = (X["SW_down"] * (1 - X["albedo"])) / 200.0
    T_surf = X["T2m"] - conv - rad_cool + sw_gain
    T_surf = np.where(wet, np.minimum(T_surf, 0.0), T_surf)
    sun_boost_mask = (X["SW_down"]>350) & (X["T2m"]<0)
    T_surf = np.where(sun_boost_mask, np.maximum(T_surf, X["T2m"] - 0.5), T_surf)
    T_top5 = np.empty_like(T_surf); T_top5[:] = np.nan
    tau = np.full_like(T_surf, 6.0)
    tau = np.where((X["ptyp"]!="none") | (X["wind"]>=6), 3.0, tau)
    tau = np.where((X["SW_down"]>300) & (X["T2m"]>-2), 4.0, tau)
    tau = np.where((X["SW_down"]<50) & (X["wind"]<2) & (X["cloud"]<0.3), 8.0, tau)
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(T_surf)>0:
        T_top5[0] = min(X["T2m"].iloc[0], 0.0)
        for i in range(1, len(T_surf)):
            T_top5[i] = T_top5[i-1] + alpha[i] * (T_surf[i] - T_top5[i-1])
    X["T_surf"] = np.round(T_surf, 2)
    X["T_top5"] = np.round(T_top5, 2)
    excess = np.clip(sw_gain - conv - rad_cool, 0, None)
    wetness = ( (X["ptyp"].isin(["rain","mixed"]).astype(float))*2.0 + (excess/5.0) )
    wetness = np.where(X["T_surf"]<-0.5, 0.0, wetness)
    X["liq_water_pct"] = np.round(np.clip(wetness, 0, 6.0), 1)
    near_zero_bonus = 20 * np.exp(-((X["T_surf"] + 0.4)/1.1)**2)
    humidity_bonus  = np.clip((X["RH"]-60)/40, 0, 1)*10
    radiation_bonus = np.clip(X["SW_down"]/600, 0, 1)*8
    wind_pen        = np.clip(X["wind"]/10, 0, 1)*10
    wet_pen         = np.clip(X["liq_water_pct"]/6, 0, 1)*25
    base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
    X["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)
    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.liq_water_pct>=3.0: return "Primaverile/trasformata bagnata"
    if row.T_surf<=-8 and row.cloud<0.4: return "Rigelata/ghiacciata"
    return "Compatta/trasformata secca"

def reliability(hours_ahead):
    x = float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# ---------------------- WAX BRANDS (SOLID + LIQUID) ----------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
SWIX_LQ = [("HS Liquid Blue",-12,-6),("HS Liquid Violet",-8,-2),("HS Liquid Red",-4,4),("HS Liquid Yellow",0,10)]
TOKO_LQ = [("LP Liquid Blue",-12,-6),("LP Liquid Red",-6,-2),("LP Liquid Yellow",-2,8)]
VOLA_LQ = [("Liquid Blue",-12,-6),("Liquid Violet",-8,-2),("Liquid Red",-4,4),("Liquid Yellow",0,8)]
RODE_LQ = [("RL Blue",-12,-6),("RL Violet",-8,-2),("RL Red",-4,3),("RL Yellow",0,8)]
HOLM_LQ = [("Liquid Blue",-12,-6),("Liquid Red",-6,2),("Liquid Yellow",0,8)]
MAPL_LQ = [("Liquid Cold",-12,-6),("Liquid Medium",-7,-1),("Liquid Soft",-2,8)]
START_LQ= [("FHF Liquid Blue",-12,-6),("FHF Liquid Purple",-8,-2),("FHF Liquid Red",-3,6)]
SKIGO_LQ= [("C110 Liquid Blue",-12,-6),("C22 Liquid Violet",-8,-2),("C44 Liquid Red",-3,6)]

BRANDS = [("Swix",SWIX,SWIX_LQ),("Toko",TOKO,TOKO_LQ),("Vola",VOLA,VOLA_LQ),("Rode",RODE,RODE_LQ),
          ("Holmenkol",HOLM,HOLM_LQ),("Maplus",MAPL,MAPL_LQ),("Start",START,START_LQ),("Skigo",SKIGO,SKIGO_LQ)]

# ---------------------- LOGHI BRAND ----------------------
BRAND_LOGO_FILES = {
    "Swix": "swix.png",
    "Toko": "toko.png",
    "Vola": "vola.png",
    "Rode": "rode.png",
    "Holmenkol": "holmenkol.png",
    "Maplus": "maplus.png",
    "Start": "start.png",
    "Skigo": "skigo.png",
}

def _try_paths(filename: str):
    for root in ["logos", "assets/logos", "."]:
        path = os.path.join(root, filename)
        if os.path.exists(path):
            return path
    return None

@st.cache_data(show_spinner=False)
def _logo_b64(path: str):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None

def get_brand_logo_b64(brand_name: str):
    fname = BRAND_LOGO_FILES.get(brand_name)
    if not fname: return None
    p = _try_paths(fname)
    return _logo_b64(p) if p else None

def pick_wax(bands, t, rh):
    name = bands[0][0]
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax:
            name = n; break
    rh_tag = " (secco)" if rh<60 else " (medio)" if rh<80 else " (umido)"
    return name + rh_tag

def pick_liquid(liq_bands, t, rh):
    name = liq_bands[0][0]
    for n,tmin,tmax in liq_bands:
        if t>=tmin and t<=tmax:
            name = n; break
    return name

def wax_form_and_brushes(t_surf: float, rh: float):
    use_liquid = (t_surf > -1.0) or (rh >= 80)
    if t_surf <= -12: regime = "very_cold"
    elif t_surf <= -5: regime = "cold"
    elif t_surf <= -1: regime = "medium"
    else: regime = "warm"
    if use_liquid:
        form = "Liquida (topcoat) su base solida"
        if regime in ("very_cold","cold"):
            brushes = "Ottone → Nylon duro → Feltro/Rotowool → Nylon morbido"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Feltro/Rotowool → Crine"
        else:
            brushes = "Ottone → Nylon → Feltro/Rotowool → Panno microfibra"
    else:
        form = "Solida (panetto)"
        if regime == "very_cold":
            brushes = "Ottone → Nylon duro → Crine"
        elif regime == "cold":
            brushes = "Ottone → Nylon → Crine"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Crine → Nylon fine"
        else:
            brushes = "Ottone → Nylon → Nylon fine → Panno"
    return form, brushes, use_liquid

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (freddo/secco)"
    if Tsurf <= -3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf <= 0.5: return "Diagonal / Scarico a V (umido)"
    return "Wave marcata (bagnato caldo)"

def tune_for(Tsurf, discipline):
    if Tsurf <= -10:
        fam = "Linear Fine"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[discipline]
    elif Tsurf <= -3:
        fam = "Cross Hatch leggera"; base=0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[discipline]
    else:
        fam = "Diagonal / V"; base = 0.8 if Tsurf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[discipline]
    return fam, side, base

# ---------------------- Persist selection ----------------------
def tt(h,m): return dtime(h,m)
def persist(key, default):
    if key not in st.session_state: st.session_state[key]=default
    return st.session_state[key]

lat = persist("lat", 45.831); lon = persist("lon", 7.730)
place_label = persist("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
tzname = detect_timezone(lat,lon)
st.markdown(f"<div class='badge map-wrap'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b> · TZ <b>{tzname}</b></div>", unsafe_allow_html=True)

@st.cache_data(ttl=6*3600, show_spinner=False)
def osm_tile(lat, lon, z=9):
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8); r.raise_for_status()
    return r.content

# --- Reverse geocoding per aggiornare l’etichetta quando si impostano coordinate manuali ---
def reverse_geocode(lat, lon):
    try:
        def go():
            return requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format":"json","lat":lat,"lon":lon,"zoom":12,"addressdetails":1},
                headers=UA, timeout=8
            )
        r = _retry(go); r.raise_for_status()
        j = r.json(); addr = j.get("address",{}) or {}
        lab = concise_label(addr, j.get("display_name",""))
        cc = addr.get("country_code","")
        lab = f"{flag(cc)}  {lab}"
        return lab
    except:
        return f"{lat:.5f}, {lon:.5f}"

# ---------- PISTE (Overpass) ----------
@st.cache_data(ttl=3*3600, show_spinner=False)
def fetch_pistes_geojson(lat:float, lon:float, dist_km:int=30):
    # OSM piste:type nelle vicinanze (downhill, nordic, skitour, ecc.)
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"];
    );
    out geom;
    """
    r = requests.post("https://overpass-api.de/api/interpreter", data=query, headers=UA, timeout=30)
    r.raise_for_status()
    data = r.json().get("elements", [])
    feats=[]
    for el in data:
        props = {
            "id": el.get("id"),
            "piste:type": (el.get("tags") or {}).get("piste:type",""),
            "name": (el.get("tags") or {}).get("name","")
        }
        if "geometry" in el:
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
            geom = {"type":"LineString","coordinates":coords}
            feats.append({"type":"Feature","geometry":geom,"properties":props})
    return {"type":"FeatureCollection","features":feats}

# --- Mappa interattiva (Leaflet/Folium) con Satellite + piste ---
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    from folium import TileLayer, LayerControl, Marker
    from folium.plugins import MousePosition
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

if HAS_FOLIUM:
    with st.expander(T["map"] + " — clicca sulla mappa per selezionare", expanded=True):
        # Mappa
        m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None, control_scale=True, prefer_canvas=True, zoom_control=True)

        # Base maps
        TileLayer(tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                  name="Strade", attr="© OSM", overlay=False, control=True).add_to(m)
        TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                  name="Satellite", attr="Tiles © Esri", overlay=False, control=True).add_to(m)

        # Piste overlays (tiles)
        TileLayer(
            tiles="https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png",
            name="Piste overlay (tiles)", attr="© OpenSnowMap.org contributors",
            overlay=True, control=True, opacity=0.85
        ).add_to(m)

        # Piste vettoriali via Overpass
        try:
            gj = fetch_pistes_geojson(lat, lon, dist_km=30)
            if gj["features"]:
                folium.GeoJson(
                    data=gj,
                    name="Piste (OSM/Overpass)",
                    tooltip=folium.GeoJsonTooltip(fields=["name","piste:type"], aliases=["Nome","Tipo"]),
                    style_function=lambda f: {"color":"#3388ff","weight":3,"opacity":0.9}
                ).add_to(m)
        except Exception:
            pass

        # Marker posizione corrente
        Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)

        # Controlli
        MousePosition().add_to(m)
        LayerControl(position="bottomleft", collapsed=True).add_to(m)

        # Render + click
        out = st_folium(
            m,
            height=420,
            use_container_width=True,
            key="map_widget",
            returned_objects=["last_clicked"]
        )

        # Aggiorna coordinate su click
        click = (out or {}).get("last_clicked") or {}
        if click:
            new_lat = float(click.get("lat")); new_lon = float(click.get("lng"))
            st.session_state["lat"] = new_lat
            st.session_state["lon"] = new_lon
            st.session_state["place_label"] = reverse_geocode(new_lat, new_lon)
            st.success(f"Posizione aggiornata: {st.session_state['place_label']}")
            st.rerun()
else:
    try:
        tile = osm_tile(lat,lon, z=9)
        st.image(tile, caption=T["map"], width=220)
    except:
        pass

# --- Pannello opzionale: posizionamento manuali ---
with st.expander("➕ Imposta coordinate manuali / Set precise coordinates", expanded=False):
    c_lat, c_lon = st.columns(2)
    new_lat = c_lat.number_input("Lat", value=float(lat), format="%.6f")
    new_lon = c_lon.number_input("Lon", value=float(lon), format="%.6f")
    if st.button("Imposta / Set"):
        st.session_state["lat"] = float(new_lat)
        st.session_state["lon"] = float(new_lon)
        new_label = reverse_geocode(float(new_lat), float(new_lon))
        st.session_state["place_label"] = new_label
        st.rerun()

# ---------------------- DATE & WINDOWS + DOWNSCALING ALT ----------------------
cdate, calt = st.columns([1,1])
with cdate:
    target_day: date = st.date_input(T["ref_day"], value=persist("ref_day", date.today()), key="ref_day")
with calt:
    pista_alt = st.number_input(T["alt_lbl"], min_value=0, max_value=5000, value=int(elev or 1800), step=50, key="alt_m")
    if pista_alt<300:
        st.warning(T["low_alt"])

st.subheader(T["blocks"])
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input(T["start"]+" A", tt(9,0),  key="A_s")
    A_end   = st.time_input(T["end"]+" A",   tt(11,0), key="A_e")
with c2:
    B_start = st.time_input(T["start"]+" B", tt(11,0), key="B_s")
    B_end   = st.time_input(T["end"]+" B",   tt(13,0), key="B_e")
with c3:
    C_start = st.time_input(T["start"]+" C", tt(13,0), key="C_s")
    C_end   = st.time_input(T["end"]+" C",   tt(16,0), key="C_e")

st.subheader(T["horizon"])
hours = st.slider(T["horizon"]+" ("+("da ora" if lang=="IT" else "from now")+")", 12, 168, persist("hours",72), 12, key="hours")
st.markdown(f"<div class='slider-tip'>{T['tip']}</div>", unsafe_allow_html=True)

# ---------------------- RUN ----------------------
st.subheader("3) Meteo & calcolo")
btn = st.button(T["fetch"], type="primary", use_container_width=True)

def windows_valid():
    ok = True
    for lbl,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
        if s>=e:
            st.error(T["invalid_win"].format(lbl=lbl)); ok=False
    return ok

def build_pdf_report(res, place_label, t_med_map, wax_cards_html):
    fig = plt.figure(figsize=(8.27, 11.69), dpi=150)
    gs = fig.add_gridspec(8,1)
    ax0 = fig.add_subplot(gs[0,0]); ax1 = fig.add_subplot(gs[1:3,0]); ax2 = fig.add_subplot(gs[3:4,0]); ax3 = fig.add_subplot(gs[4:5,0])
    ax4 = fig.add_subplot(gs[5:6,0]); ax5 = fig.add_subplot(gs[6:7,0])
    fig.suptitle(f"Telemark · Pro Wax & Tune — {place_label}", fontsize=12, y=0.995)
    tloc = res["time_local"].dt.tz_localize(None)
    ax1.plot(tloc, res["T2m"], label="T aria"); ax1.plot(tloc, res["T_surf"], label="T neve"); ax1.plot(tloc, res["T_top5"], label="Top 5mm")
    ax1.set_title("Temperature"); ax1.grid(alpha=.2); ax1.legend(fontsize=8)
    ax2.bar(tloc, res["prp_mmph"], width=0.03); ax2.set_title("Precipitazione (mm/h)"); ax2.grid(alpha=.2)
    ax3.plot(tloc, res["SW_down"], label="SW↓"); ax3.plot(tloc, res["RH"], label="UR%"); ax3.set_title("Radiazione & Umidità"); ax3.grid(alpha=.2); ax3.legend(fontsize=8)
    ax4.plot(tloc, res["speed_index"]); ax4.set_title("Indice scorrevolezza"); ax4.grid(alpha=.2)
    ax0.axis('off'); ax5.axis('off')
    ax0.text(0.01,0.2, f"Sintesi blocchi (T_neve med): {t_med_map}", fontsize=10)
    ax5.text(0.01,0.9, "Waxes:", fontsize=10)
    ax5.text(0.02,0.75, "Vedi app per dettagli per brand e spazzole.", fontsize=8)
    buf = io.BytesIO(); fig.tight_layout(rect=[0,0,1,0.98]); fig.savefig(buf, format="pdf"); plt.close(fig)
    buf.seek(0); return buf.getvalue()

def plot_speed_mini(res):
    fig = plt.figure(figsize=(6,2.2))
    plt.plot(res["time_local"].dt.tz_localize(None), res["speed_index"])
    plt.title(T["speed_chart"]); plt.grid(alpha=.2)
    st.pyplot(fig); plt.close(fig)

def brand_card_html(name, base_solid, form, topcoat, brushes, logo_b64):
    logo_html = f"<div class='logo'><img src='data:image/png;base64,{logo_b64}'/></div>" if logo_b64 else "<div class='logo'></div>"
    return f"""
    <div class='brand'>
      {logo_html}
      <div style='flex:1'>
        <h4>{name}</h4>
        <div class='muted'>{T['base_solid']}: <b>{base_solid}</b></div>
        <div class='sub'>Forma: {form}</div>
        <div class='sub'>{T['topcoat_lbl']}: {topcoat}</div>
        <div class='sub'>Spazzole: {brushes}</div>
      </div>
    </div>
    """

if btn:
    if windows_valid():
        with st.status(T["status_title"], expanded=False) as status:
            try:
                with st.spinner("Open-Meteo…"):
                    js = _retry(lambda: fetch_open_meteo(lat,lon))
                raw = build_df(js, hours)
                if raw.empty:
                    st.error("Nessun dato meteo disponibile dalla fonte in questo momento.")
                    status.update(label="Sorgente vuota", state="error", expanded=True)
                    st.stop()
                raw = noaa_bias_correction(raw, lat, lon)
                base_alt = elev or pista_alt
                X = enrich_meteo_quickwins(raw, lat, lon, base_alt, pista_alt)
                res = snow_temperature_model(X)

                tzobj = tz.gettz(tzname)
                res["time_local"] = res["time_utc"].dt.tz_convert(tzobj)

                if abs(offset)>0:
                    res["T_surf"] = (res["T_surf"] + offset).round(2)
                    res["T_top5"] = (res["T_top5"] + offset).round(2)
                    near_zero_bonus = 20 * np.exp(-((res["T_surf"] + 0.4)/1.1)**2)
                    humidity_bonus  = np.clip((res["RH"]-60)/40, 0, 1)*10
                    radiation_bonus = np.clip(res["SW_down"]/600, 0, 1)*8
                    wind_pen        = np.clip(res["wind"]/10, 0, 1)*10
                    wet_pen         = np.clip(res["liq_water_pct"]/6, 0, 1)*25
                    base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
                    res["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)

                disp = res.copy()
                if use_fahrenheit:
                    for col in ["T2m","td","Tw","T_surf","T_top5"]:
                        disp[col] = c_to_f(disp[col])
                    Tair_lbl = T["t_air"].replace("°C","°F"); Td_lbl = T["td"].replace("°C","°F")
                    Tw_lbl   = T["tw"].replace("°C","°F"); Tsurf_lbl= T["t_surf"].replace("°C","°F")
                    Ttop_lbl = T["t_top5"].replace("°C","°F")
                else:
                    Tair_lbl, Td_lbl, Tw_lbl, Tsurf_lbl, Ttop_lbl = T["t_air"], T["td"], T["tw"], T["t_surf"], T["t_top5"]

                wind_unit_lbl = "m/s" if not use_fahrenheit else "km/h"

                # --- Charts (timezone-naive per robustezza plotting) ---
                tloc = disp["time_local"].dt.tz_localize(None)
                fig1 = plt.figure(figsize=(10,3))
                plt.plot(tloc, disp["T2m"], label=Tair_lbl)
                plt.plot(tloc, disp["T_surf"], label=Tsurf_lbl)
                plt.plot(tloc, disp["T_top5"], label=Ttop_lbl)
                plt.legend(); plt.title(T["temp"]); plt.xlabel(T["hour"]); plt.ylabel("°F" if use_fahrenheit else "°C"); plt.grid(alpha=0.2)
                st.pyplot(fig1); plt.close(fig1)

                fig2 = plt.figure(figsize=(10,2.6))
                plt.bar(tloc, disp["prp_mmph"], width=0.025)
                plt.title(T["prec"]); plt.xlabel(T["hour"]); plt.ylabel("mm/h"); plt.grid(alpha=0.2)
                st.pyplot(fig2); plt.close(fig2)

                fig3 = plt.figure(figsize=(10,2.6))
                plt.plot(tloc, disp["SW_down"], label="SW↓")
                plt.plot(tloc, disp["RH"], label=T["rh"])
                plt.legend(); plt.title(T["radhum"]); plt.grid(alpha=0.2)
                st.pyplot(fig3); plt.close(fig3)

                plot_speed_mini(disp)

                if show_debug:
                    st.info(f"Rows: {len(disp)} · time_local: {disp['time_local'].min()} → {disp['time_local'].max()}")

                # --- Blocchi & Cards brand (con loghi) ---
                blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
                t_med_map = {}
                for L,(s,e) in blocks.items():
                    st.markdown("---")
                    st.markdown(f"### Blocco {L}")
                    mask_day = disp["time_local"].dt.date == target_day
                    day_df = disp[mask_day].copy()
                    if day_df.empty:
                        W = disp.head(7).copy()
                    else:
                        sel = day_df[(day_df["time_local"].dt.time>=s) & (day_df["time_local"].dt.time<=e)]
                        W = sel if not sel.empty else day_df.head(6)
                    if W.empty:
                        st.info(T["nodata"]); continue
                    t_med = float(W["T_surf"].mean()); t_med_map[L]=round(t_med,1)
                    rh_med = float(W["RH"].mean())   # <-- FIX PARENTHESIS
                    any_alert = ((W["T_surf"] > (-0.5 if not use_fahrenheit else c_to_f(-0.5))) & (W["RH"]>85)).any()
                    if any_alert:
                        st.markdown(f"<div class='badge-red'>⚠ {T['alert'].format(lbl=L)}</div>", unsafe_allow_html=True)
                    k = classify_snow(W.iloc[0])
                    rel = reliability((W.index[0] if not W.empty else 0) + 1)
                    v_eff = (W["wind"] if not use_fahrenheit else ms_to_kmh(W["wind"])).mean()
                    st.markdown(
                        f"<div class='banner'><b>{T['cond']}</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}{'°F' if use_fahrenheit else '°C'} · <b>H₂O liquida</b> {float(W['liq_water_pct'].mean()):.1f}% · "
                        f"<b>Affidabilità</b> ≈ {rel}% · "
                        f"<b>V eff</b> {v_eff:.1f} {wind_unit_lbl}</div>",
                        unsafe_allow_html=True
                    )
                    t_for_struct = t_med if not use_fahrenheit else (t_med-32)*5/9
                    st.markdown(f"**{T['struct']}** {recommended_structure(t_for_struct)}")
                    wax_form, brush_seq, use_topcoat = wax_form_and_brushes(t_for_struct, rh_med)

                    st.markdown("<div class='grid'>", unsafe_allow_html=True)
                    for (name, solid_bands, liquid_bands) in BRANDS:
                        rec_solid  = pick_wax(solid_bands, t_for_struct, rh_med)
                        topcoat = (pick_liquid(liquid_bands, t_for_struct, rh_med) if use_topcoat else ("non necessario" if lang=="IT" else "not needed"))
                        logo_b64 = get_brand_logo_b64(name)
                        html = brand_card_html(name, rec_solid, wax_form, topcoat, brush_seq, logo_b64)
                        st.markdown(html, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                    # Tuning per disciplina
                    rows=[]
                    for d in ["SL","GS","SG","DH"]:
                        fam, side, base = tune_for(t_for_struct, d)
                        rows.append((d, fam, f"{side:.1f}°", f"{base:.1f}°"))
                    tune_list = "".join([f"<li><b>{d}</b>: {fam} — SIDE {side} · BASE {base}</li>" for d,fam,side,base in rows])
                    st.markdown(f"<div class='card tune'><div><b>Tuning per disciplina</b></div><ul class='small'>{tune_list}</ul></div>", unsafe_allow_html=True)

                # CSV/PDF download
                csv = disp.copy()
                csv["time_local"] = csv["time_local"].dt.strftime("%Y-%m-%d %H:%M")
                csv = csv.drop(columns=["time_utc"])
                st.download_button(T["download_csv"], data=csv.to_csv(index=False), file_name="forecast_snow_telemark.csv", mime="text/csv")

                pdf_bytes = build_pdf_report(disp, place_label, t_med_map, "")
                st.download_button("Scarica report PDF (1 pagina)", data=pdf_bytes, file_name="report_telemark.pdf", mime="application/pdf")

                status.update(label=f"{T['last_upd']}: {datetime.now().strftime('%H:%M')}", state="complete", expanded=False)

            except requests.exceptions.Timeout:
                status.update(label="Timeout servizio meteo. Clicca di nuovo per riprovare.", state="error", expanded=True)
            except requests.exceptions.HTTPError as e:
                status.update(label=f"Errore HTTP: {e}", state="error", expanded=True)
            except Exception as e:
                status.update(label=f"Errore: {e}", state="error", expanded=True)
