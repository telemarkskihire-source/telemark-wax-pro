# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark, cached, robust fetch, i18n, units toggle, lead-time, alerts, PDF report, map, validation

import os, math, base64, requests, pandas as pd, numpy as np, io, time
import streamlit as st
from datetime import datetime, date, time as dtime, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox
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
.brand {{ display:flex; align-items:center; gap:.65rem; background:#0e141d; border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem; }}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.btn-primary button {{ background:{ACCENT} !important; color:{'#111'} !important; font-weight:800 !important; }}
.slider-tip {{ color:var(--muted); font-size:.85rem }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
.map-wrap {{ display:flex; align-items:center; gap:.5rem; }}
.map-wrap img {{ border-radius:6px; border:1px solid #1e2a3a; }}
.badge-red {{ border-left:6px solid {ERR}; background:#2a1518; color:#fee2e2; padding:.6rem .8rem; border-radius:10px; }}
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
        "map":"Mappa (selezione)"
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
        "t_air":"Air T (°C)","td":"Td (°C)","rh":"RH (%)","tw":"Tw (°C)",
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
        "map":"Map (selection)"
    }
}

# UI state: language & units
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang=="IT" else L["en"]
units = st.sidebar.radio(T["unit"], [T["unit_c"], T["unit_f"]], index=0, horizontal=False)
use_fahrenheit = (units==T["unit_f"])

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
        except Exception as e:
            if i==attempts-1: raise
            time.sleep(sleep*(1.5**i))

# ---------------------- SEARCH with COUNTRY prefilter ----------------------
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
col_top = st.columns([2,1,1,1])
with col_top[1]:
    sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
    iso2 = COUNTRIES[sel_country]
with col_top[2]:
    # calibration offset
    offset = st.slider(T["offset"], -1.5, 1.5, 0.0, 0.1, key="cal_offset")
with col_top[3]:
    # Reset UI
    if st.button(T["reset"], use_container_width=True):
        for k in ["A_s","A_e","B_s","B_e","C_s","C_e","place","lat","lon","place_label","hours","country_sel","cal_offset"]:
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

    selected = st_searchbox(
        nominatim_search, key="place", placeholder=T["search_ph"],
        clear_on_submit=False, default=None
    )

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
    rr = requests.get("https://api.open-meteo.com/v1/elevation",
                      params={"latitude":lat, "longitude":lon}, headers=UA, timeout=8)
    rr.raise_for_status(); js = rr.json()
    return float(js["elevation"][0]) if js and "elevation" in js else None

@st.cache_data(ttl=12*3600, show_spinner=False)
def detect_timezone(lat, lon):
    # lightweight call only to get timezone name
    r = requests.get("https://api.open-meteo.com/v1/forecast",
                     params={"latitude":lat,"longitude":lon,"hourly":"temperature_2m","forecast_days":1,"timezone":"auto"},
                     headers=UA, timeout=10)
    r.raise_for_status()
    return r.json().get("timezone","Europe/Rome")

# ---------------------- NOAA (optional robust bias) ----------------------
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_nearby_station(lat, lon, radius_m=25000, limit=3):
    if not NOAA_TOKEN: return []
    r = requests.get(
        "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations",
        params={"datasetid":"GHCND","limit":limit,"sortfield":"distance",
                "latitude":lat,"longitude":lon,"radius":radius_m},
        headers={"token": NOAA_TOKEN, **UA}, timeout=10
    )
    j = r.json()
    return (j.get("results") or [])

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_normals_dly(station_id):
    if not NOAA_TOKEN: return {}
    params = {
        "datasetid": "NORMAL_DLY",
        "stationid": station_id,
        "datatypeid": ["DLY-TAVG-NORMAL","DLY-PRCP-PCTALL-GE001HI"],
        "startdate": "2010-01-01",
        "enddate":   "2010-12-31",
        "limit": 1000
    }
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/data",
                     params=params, headers={"token": NOAA_TOKEN, **UA}, timeout=12)
    j = r.json()
    vals = j.get("results") or []
    out = {}
    for rec in vals:
        dt = rec.get("date","")
        mmdd = dt[5:10]
        dtype = rec.get("datatype"); val = rec.get("value")
        if val is None: continue
        out.setdefault(dtype, {})[mmdd] = val
    return out

def noaa_bias_correction(df, lat, lon):
    if not NOAA_TOKEN:
        return df
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
    df["time"] = pd.to_datetime(df["time"], utc=True)  # UTC
    now0 = pd.Timestamp.utcnow().floor("H")
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)
    out = pd.DataFrame()
    out["time_utc"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["RH"] = df.get("relative_humidity_2m", np.nan).astype(float)
    out["td"]   = df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"] = df.get("weathercode",0).astype(int)
    # lead time (h)
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
    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ( (X["ptyp"]=="snow") & (X["T2m"]>-0.5) & (X["RH"]>90) ) |
        ( (X["SW_down"]>250) & (X["T2m"]>-1.0) ) |
        (X["T2m"]>0.5)
    )
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

BRANDS = [
    ("Swix",SWIX,SWIX_LQ),
    ("Toko",TOKO,TOKO_LQ),
    ("Vola",VOLA,VOLA_LQ),
    ("Rode",RODE,RODE_LQ),
    ("Holmenkol",HOLM,HOLM_LQ),
    ("Maplus",MAPL,MAPL_LQ),
    ("Start",START,START_LQ),
    ("Skigo",SKIGO,SKIGO_LQ)
]

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

# Tiny static map (OSM tile)
@st.cache_data(ttl=6*3600, show_spinner=False)
def osm_tile(lat, lon, z=9):
    # compute tile x,y
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8); r.raise_for_status()
    return r.content

try:
    tile = osm_tile(lat,lon, z=9)
    st.image(tile, caption=T["map"], width=220)
except:
    pass

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

# --- PDF report (A4 single page) ---
def build_pdf_report(res, place_label, t_med_map, wax_cards_html):
    # Compose a single-page matplotlib figure
    fig = plt.figure(figsize=(8.27, 11.69), dpi=150)  # A4
    gs = fig.add_gridspec(8,1)
    ax0 = fig.add_subplot(gs[0,0]); ax1 = fig.add_subplot(gs[1:3,0]); ax2 = fig.add_subplot(gs[3:4,0]); ax3 = fig.add_subplot(gs[4:5,0])
    ax4 = fig.add_subplot(gs[5:6,0]); ax5 = fig.add_subplot(gs[6:7,0])
    fig.suptitle(f"Telemark · Pro Wax & Tune — {place_label}", fontsize=12, y=0.995)
    tloc = res["time_local"]
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

# Mini speed chart helper
def plot_speed_mini(res):
    fig = plt.figure(figsize=(6,2.2))
    plt.plot(res["time_local"], res["speed_index"])
    plt.title(T["speed_chart"]); plt.grid(alpha=.2)
    st.pyplot(fig)

if btn:
    if windows_valid():
        with st.status(T["status_title"], expanded=False) as status:
            try:
                with st.spinner("Open-Meteo…"):
                    js = _retry(lambda: fetch_open_meteo(lat,lon))
                raw = build_df(js, hours)
                raw = noaa_bias_correction(raw, lat, lon)
                base_alt = elev or pista_alt
                X = enrich_meteo_quickwins(raw, lat, lon, base_alt, pista_alt)
                res = snow_temperature_model(X)

                # Local time by detected tz
                tzobj = tz.gettz(tzname)
                res["time_local"] = res["time_utc"].dt.tz_convert(tzobj)

                # Apply calibration offset to snow temperatures and recompute dependent metrics
                if abs(offset)>0:
                    res["T_surf"] = (res["T_surf"] + offset).round(2)
                    res["T_top5"] = (res["T_top5"] + offset).round(2)
                    # Recompute speed index with new T_surf (quick recalibration)
                    near_zero_bonus = 20 * np.exp(-((res["T_surf"] + 0.4)/1.1)**2)
                    humidity_bonus  = np.clip((res["RH"]-60)/40, 0, 1)*10
                    radiation_bonus = np.clip(res["SW_down"]/600, 0, 1)*8
                    wind_pen        = np.clip(res["wind"]/10, 0, 1)*10
                    wet_pen         = np.clip(res["liq_water_pct"]/6, 0, 1)*25
                    base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
                    res["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)

                # Units conversion for display
                disp = res.copy()
                if use_fahrenheit:
                    for col in ["T2m","td","Tw","T_surf","T_top5"]:
                        disp[col] = c_to_f(disp[col])
                    Tair_lbl = T["t_air"].replace("°C","°F")
                    Td_lbl   = T["td"].replace("°C","°F")
                    Tw_lbl   = T["tw"].replace("°C","°F")
                    Tsurf_lbl= T["t_surf"].replace("°C","°F")
                    Ttop_lbl = T["t_top5"].replace("°C","°F")
                else:
                    Tair_lbl, Td_lbl, Tw_lbl, Tsurf_lbl, Ttop_lbl = T["t_air"], T["td"], T["tw"], T["t_surf"], T["t_top5"]

                wind_eff_disp = disp["wind_eff"] if not use_fahrenheit else ms_to_kmh(disp["wind_eff"])
                wind_unit_lbl = "m/s" if not use_fahrenheit else "km/h"

                # --------- GRAPHS ----------
                tloc = disp["time_local"]
                fig1 = plt.figure(figsize=(10,3))
                plt.plot(tloc, disp["T2m"], label=Tair_lbl)
                plt.plot(tloc, disp["T_surf"], label=Tsurf_lbl)
                plt.plot(tloc, disp["T_top5"], label=Ttop_lbl)
                plt.legend(); plt.title(T["temp"]); plt.xlabel(T["hour"]); plt.ylabel("°F" if use_fahrenheit else "°C"); plt.grid(alpha=0.2)
                st.pyplot(fig1)

                fig2 = plt.figure(figsize=(10,2.6))
                plt.bar(tloc, disp["prp_mmph"], width=0.03, align="center")
                plt.title(T["prec"]); plt.xlabel(T["hour"]); plt.ylabel("mm/h"); plt.grid(alpha=0.2)
                st.pyplot(fig2)

                fig3 = plt.figure(figsize=(10,2.6))
                plt.plot(tloc, disp["SW_down"], label="SW↓")
                plt.plot(tloc, disp["RH"], label=T["rh"])
                plt.legend(); plt.title(T["radhum"]); plt.grid(alpha=0.2)
                st.pyplot(fig3)

                # Speed mini chart
                plot_speed_mini(disp)

                # --------- TABLE (clean) with lead time ----------
                show = pd.DataFrame({
                    T["hour"]:    disp["time_local"].dt.strftime("%Y-%m-%d %H:%M"),
                    Tair_lbl: disp["T2m"].round(1),
                    Td_lbl:     disp["td"].round(1),
                    T["rh"]:      disp["RH"].round(0),
                    Tw_lbl:     disp["Tw"].round(1),
                    f"{T['we'].split('(')[0].strip()} ({wind_unit_lbl})":  wind_eff_disp.round(1),
                    T["cloud"]:  (disp["cloud"]*100).round(0),
                    T["sw"]:  disp["SW_down"].round(0),
                    T["prp"]:  disp["prp_mmph"].round(2),
                    T["ptype"]:    disp["ptyp"].map({"none":T["none"],"rain":T["rain"],"snow":T["snow"],"mixed":T["mixed"]}),
                    Tsurf_lbl: disp["T_surf"].round(1),
                    Ttop_lbl:  disp["T_top5"].round(1),
                    T["lw"]:  disp["liq_water_pct"].round(1),
                    T["speed"]: disp["speed_index"].astype(int),
                    T["lead"]:  disp["lead_h"]
                })
                st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
                st.dataframe(show, use_container_width=True, hide_index=True)
                st.markdown("</div>", unsafe_allow_html=True)

                # --------- BLOCKS A/B/C with alerts ----------
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
                    rh_med = float(W["RH"].mean())
                    # alert condition:
                    any_alert = ((W["T_surf"] > (-0.5 if not use_fahrenheit else c_to_f(-0.5))) & (W["RH"]>85)).any()
                    if any_alert:
                        st.markdown(f"<div class='badge-red'>⚠ {T['alert'].format(lbl=L)}</div>", unsafe_allow_html=True)

                    # Local classify & reliability
                    k = classify_snow(W.iloc[0])
                    rel = reliability((W.index[0] if not W.empty else 0) + 1)
                    st.markdown(
                        f"<div class='banner'><b>{T['cond']}</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}{'°F' if use_fahrenheit else '°C'} · <b>H₂O liquida</b> {float(W['liq_water_pct'].mean()):.1f}% · "
                        f"<b>Affidabilità</b> ≈ {rel}%</div>",
                        unsafe_allow_html=True
                    )
                    st.markdown(f"**{T['struct']}** {recommended_structure(t_med if not use_fahrenheit else (t_med-32)*5/9)}")

                    wax_form, brush_seq, use_topcoat = wax_form_and_brushes(
                        (t_med if not use_fahrenheit else (t_med-32)*5/9), rh_med)

                    st.markdown(f"**{T['waxes']}**")
                    ccols1 = st.columns(4); ccols2 = st.columns(4)
                    for i,(name,solid_bands,liquid_bands) in enumerate(BRANDS[:4]):
                        base_t = (t_med if not use_fahrenheit else (t_med-32)*5/9)
                        rec_solid  = pick_wax(solid_bands, base_t, rh_med)
                        topcoat = pick_liquid(liquid_bands, base_t, rh_med) if use_topcoat else "—"
                        extra_liq = f"<div style='color:#93b2c6;font-size:.85rem'>Topcoat: {topcoat if use_topcoat else 'non necessario'}</div>"
                        ccols1[i].markdown(
                            f"<div class='brand'><div><b>{name}</b>"
                            f"<div style='color:#a9bacb'>Base: {rec_solid}</div>"
                            f"<div style='color:#93b2c6;font-size:.85rem'>Forma: {wax_form}</div>"
                            f"{extra_liq}"
                            f"<div style='color:#93b2c6;font-size:.85rem'>Spazzole: {brush_seq}</div>"
                            f"</div></div>", unsafe_allow_html=True
                        )
                    for i,(name,solid_bands,liquid_bands) in enumerate(BRANDS[4:]):
                        base_t = (t_med if not use_fahrenheit else (t_med-32)*5/9)
                        rec_solid  = pick_wax(solid_bands, base_t, rh_med)
                        topcoat = pick_liquid(liquid_bands, base_t, rh_med) if use_topcoat else "—"
                        extra_liq = f"<div style='color:#93b2c6;font-size:.85rem'>Topcoat: {topcoat if use_topcoat else 'non necessario'}</div>"
                        ccols2[i].markdown(
                            f"<div class='brand'><div><b>{name}</b>"
                            f"<div style='color:#a9bacb'>Base: {rec_solid}</div>"
                            f"<div style='color:#93b2c6;font-size:.85rem'>Forma: {wax_form}</div>"
                            f"{extra_liq}"
                            f"<div style='color:#93b2c6;font-size:.85rem'>Spazzole: {brush_seq}</div>"
                            f"</div></div>", unsafe_allow_html=True
                        )
                    # Mini table window
                    mini = pd.DataFrame({
                        T["hour"]: W["time_local"].dt.strftime("%H:%M"),
                        "T aria" if lang=="IT" else "Air T": W["T2m"].round(1),
                        "T neve" if lang=="IT" else "Snow T": W["T_surf"].round(1),
                        "UR%" if lang=="IT" else "RH%":   W["RH"].round(0),
                        ("V (m/s)" if not use_fahrenheit else "V (km/h)"): (W["wind"] if not use_fahrenheit else ms_to_kmh(W["wind"])).round(1),
                        T["ptype"]:   W["ptyp"].map({"none":T["none"],"snow":T["snow"],"rain":T["rain"],"mixed":T["mixed"]})
                    })
                    st.dataframe(mini, use_container_width=True, hide_index=True)

                    st.markdown("**Tuning per disciplina (SIDE/BASE):**")
                    rows=[]
                    t_for_tune = (t_med if not use_fahrenheit else (t_med-32)*5/9)
                    for d in ["SL","GS","SG","DH"]:
                        fam, side, base = tune_for(t_for_tune, d)
                        rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
                    st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

                # Download CSV
                csv = disp.copy()
                csv["time_local"] = csv["time_local"].dt.strftime("%Y-%m-%d %H:%M")
                csv = csv.drop(columns=["time_utc"])
                st.download_button(T["download_csv"], data=csv.to_csv(index=False),
                                   file_name="forecast_snow_telemark.csv", mime="text/csv")

                # One-page PDF report
                pdf_bytes = build_pdf_report(disp, place_label, t_med_map, "")
                st.download_button("Scarica report PDF (1 pagina)",
                                   data=pdf_bytes, file_name="report_telemark.pdf", mime="application/pdf")

                status.update(label=f"{T['last_upd']}: {datetime.now().strftime('%H:%M')}", state="complete", expanded=False)

            except requests.exceptions.Timeout:
                status.update(label="Timeout servizio meteo. Clicca di nuovo per riprovare.", state="error", expanded=True)
            except requests.exceptions.HTTPError as e:
                status.update(label=f"Errore HTTP: {e}", state="error", expanded=True)
            except Exception as e:
                status.update(label=f"Errore: {e}", state="error", expanded=True)
