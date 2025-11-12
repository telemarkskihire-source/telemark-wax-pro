import numpy as np, pandas as pd, requests
from datetime import datetime
from dateutil import tz
import streamlit as st
from .utils import UA, rh_from_t_td, wetbulb_stull, clear_sky_ghi, effective_wind

@st.cache_data(ttl=600, show_spinner=False)
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
    r.raise_for_status(); return r.json()

@st.cache_data(ttl=24*3600, show_spinner=False)
def get_elev(lat,lon):
    rr = requests.get("https://api.open-meteo.com/v1/elevation", params={"latitude":lat, "longitude":lon}, headers=UA, timeout=8)
    rr.raise_for_status(); js = rr.json()
    return float(js["elevation"][0]) if js and "elevation" in js else None

@st.cache_data(ttl=12*3600, show_spinner=False)
def detect_timezone(lat, lon):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude":lat,"longitude":lon,"hourly":"temperature_2m","forecast_days":1,"timezone":"auto"}, headers=UA, timeout=10)
    r.raise_for_status(); return r.json().get("timezone","Europe/Rome")

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    now0 = pd.Timestamp.now(tz="UTC").floor("H")
    df = df[df["time"] >= now0].head(int(hours)).reset_index(drop=True)
    out = pd.DataFrame()
    out["time_utc"]   = df["time"]
    out["T2m"]        = df["temperature_2m"].astype(float)
    out["RH"]         = df["relative_humidity_2m"].astype(float) if "relative_humidity_2m" in df else np.full(len(df), np.nan)
    out["td"]         = (df["dew_point_2m"].astype(float) if "dew_point_2m" in df else out["T2m"].astype(float))
    out["cloud"]      = (df["cloudcover"].astype(float)/100).clip(0,1) if "cloudcover" in df else np.zeros(len(df))
    out["wind"]       = (df["windspeed_10m"].astype(float)/3.6) if "windspeed_10m" in df else np.zeros(len(df))  # m/s
    out["sunup"]      = df["is_day"].astype(int) if "is_day" in df else np.zeros(len(df), dtype=int)
    out["prp_mmph"]   = df["precipitation"].astype(float) if "precipitation" in df else np.zeros(len(df))
    out["rain"]       = df["rain"].astype(float) if "rain" in df else np.zeros(len(df))
    out["snowfall"]   = df["snowfall"].astype(float) if "snowfall" in df else np.zeros(len(df))
    out["wcode"]      = df["weathercode"].astype(int) if "weathercode" in df else np.zeros(len(df), dtype=int)
    out["lead_h"]     = ((out["time_utc"] - now0).dt.total_seconds()/3600.0).round(1)
    return out

# --- NOAA (facoltativo) ---
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_nearby_station(lat, lon, radius_m=25000, limit=3):
    if not NOAA_TOKEN: return []
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/stations",
        params={"datasetid":"GHCND","limit":limit,"sortfield":"distance","latitude":lat,"longitude":lon,"radius":radius_m},
        headers={"token": NOAA_TOKEN, **UA}, timeout=10)
    return (r.json().get("results") or [])

@st.cache_data(ttl=24*3600, show_spinner=False)
def _noaa_normals_dly(station_id):
    if not NOAA_TOKEN: return {}
    params = {"datasetid":"NORMAL_DLY","stationid":station_id,"datatypeid":["DLY-TAVG-NORMAL","DLY-PRCP-PCTALL-GE001HI"],"startdate":"2010-01-01","enddate":"2010-12-31","limit":1000}
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/data", params=params, headers={"token": NOAA_TOKEN, **UA}, timeout=12)
    vals = r.json().get("results") or []
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
        if tnorm is not None:
            med_model = float(np.nanmedian(df2["T2m"].values))
            bias = tnorm - med_model
            adj = np.clip(0.5*bias, -1.2, 1.2)
            df2["T2m"] = df2["T2m"] + adj
            df2["td"]  = df2["td"]  + adj
        df2["RH"]  = np.where(np.isnan(df2["RH"]), 70.0, df2["RH"])
        df2["RH"]  = np.clip(df2["RH"] + (70 - df2["RH"])*0.03, 1, 100)
        if prp_pct is not None and prp_pct >= 60:
            df2["prp_mmph"] *= 1.10; df2["rain"] *= 1.10; df2["snowfall"] *= 1.10
        return df2
    except Exception:
        return df

def lapse_correction(Tv, base_alt, target_alt, lapse=-6.5):
    dz = (target_alt - (base_alt or target_alt))
    return Tv + (lapse/1000.0) * dz

def enrich_meteo_quickwins(df, lat, lon, base_alt, target_alt):
    X = df.copy()
    if X["RH"].isna().any(): X.loc[:, "RH"] = rh_from_t_td(X["T2m"], X["td"])
    X["Tw"] = wetbulb_stull(X["T2m"], X["RH"])
    X["wind_eff"] = effective_wind(X["wind"])
    sw_list = [clear_sky_ghi(lat, lon, ts.to_pydatetime()) for ts in X["time_utc"]]
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
    def prp_type_row(row):
        if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
        if row.rain>0 and row.snowfall>0: return "mixed"
        if row.snowfall>0 and row.rain==0: return "snow"
        if row.rain>0 and row.snowfall==0: return "rain"
        snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
        if int(row.wcode) in snow_codes: return "snow"
        if int(row.wcode) in rain_codes: return "rain"
        return "mixed"
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

# --- EXPORT COMPAT ---
def render_meteo(T, ctx):
    # Prova a chiamare la tua funzione reale se esiste
    for name in ["panel_meteo", "run_meteo", "main", "render"]:
        fn = globals().get(name)
        if callable(fn):
            return fn(T, ctx)
    # Stub di fallback
    import streamlit as st
    st.markdown("**[meteo]** pronto (stub).")

# Alias generico
render = render_meteo

# --- export di fallback per l’orchestratore ---
if not any(k in globals() for k in ("render_meteo","panel_meteo","run_meteo","show_meteo","render")):
    def render_meteo(T, ctx):
        import streamlit as st
        st.markdown("**[meteo]** pronto (stub).")
    render = render_meteo
