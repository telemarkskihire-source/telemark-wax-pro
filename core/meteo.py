# core/meteo.py
# Telemark · Pro Wax & Tune — METEO pipeline (fetch → arricchimento → snow model)
# Nessuna dipendenza da _retry esterno; esporto render_meteo(T, ctx) + alias render.

import math, io, time, requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime
from dateutil import tz

UA = {"User-Agent":"telemark-wax-pro/1.0"}

# ---------------------- small retry locale ----------------------
def _retry(func, attempts=2, sleep=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1: raise
            time.sleep(sleep * (1.5**i))

# ---------------------- fisica & util ----------------------
def rh_from_t_td(Tv, Td):
    Tv = np.array(Tv, dtype=float); Td = np.array(Td, dtype=float)
    a,b = 17.625, 243.04
    es = 6.1094 * np.exp((a*Tv)/(b+Tv))
    e  = 6.1094 * np.exp((a*Td)/(b+Td))
    RH = 100.0 * (e / es)
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

# ---------------------- servizi remoti (cached) ----------------------
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

# ---------------------- DEM 3×3 + slope/aspect (facoltativo) ----------------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def dem_patch(lat: float, lon: float, spacing_m: int = 30, size: int = 3):
    half = size // 2
    dlat = spacing_m / 111320.0
    dlon = spacing_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    lats, lons = [], []
    for j in range(size):
        for i in range(size):
            lats.append(lat + (j - half) * dlat)
            lons.append(lon + (i - half) * dlon)
    params = { "latitude": ",".join(f"{x:.6f}" for x in lats),
               "longitude": ",".join(f"{x:.6f}" for x in lons) }
    r = requests.get("https://api.open-meteo.com/v1/elevation", params=params, headers=UA, timeout=10)
    r.raise_for_status()
    js = r.json()
    elevs = js.get("elevation")
    if not elevs or len(elevs) != size * size: return None
    Z = np.array(elevs, dtype=float).reshape(size, size)
    return {"Z": Z, "spacing_m": spacing_m}

def slope_aspect_from_dem(Z: np.ndarray, spacing_m: float):
    dzdx = ((Z[0,2] + 2*Z[1,2] + Z[2,2]) - (Z[0,0] + 2*Z[1,0] + Z[2,0])) / (8.0 * spacing_m)
    dzdy = ((Z[2,0] + 2*Z[2,1] + Z[2,2]) - (Z[0,0] + 2*Z[0,1] + Z[0,2])) / (8.0 * spacing_m)
    slope_rad = math.atan(math.hypot(dzdx, dzdy))
    slope_deg = math.degrees(slope_rad)
    slope_pct = math.tan(slope_rad) * 100.0
    aspect_rad = math.atan2(dzdx, dzdy)   # 0° = Nord
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0
    return float(slope_deg), float(slope_pct), float(aspect_deg)

def aspect_to_compass(deg: float):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]

# ---------------------- pipeline ----------------------
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

# ---------------------- piccoli plot ----------------------
def _plot_series(disp, T):
    tloc = disp["time_local"].dt.tz_localize(None)

    fig1 = plt.figure(figsize=(10,3))
    plt.plot(tloc, disp["T2m"], label=T["t_air"])
    plt.plot(tloc, disp["T_surf"], label=T["t_surf"])
    plt.plot(tloc, disp["T_top5"], label=T["t_top5"])
    plt.legend(); plt.title(T["temp"]); plt.xlabel(T["hour"]); plt.ylabel("°C"); plt.grid(alpha=0.2)
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

# ---------------------- RENDER ----------------------
def render_meteo(T, ctx):
    """UI Meteo. Usa ctx['lat'], ctx['lon'], ctx['place_label'] (se esistono)."""
    st.markdown("## 3) Meteo & calcolo")

    lat = float(ctx.get("lat", st.session_state.get("lat", 45.831)))
    lon = float(ctx.get("lon", st.session_state.get("lon", 7.730)))
    place_label = ctx.get("place_label", st.session_state.get("place_label", "—"))

    # orizzonte + offset termico opzionale (riuso se già in state)
    cols = st.columns([1,1,1])
    with cols[0]:
        hours = st.slider(T["horizon"], 12, 168, st.session_state.get("hours", 72), 12, key="hours")
    with cols[1]:
        offset = st.slider(T["offset"], -1.5, 1.5, st.session_state.get("cal_offset", 0.0), 0.1, key="cal_offset")
    with cols[2]:
        do_debug = st.checkbox(T.get("debug","Mostra debug"), value=False)

    btn = st.button(T["fetch"], type="primary", use_container_width=True)

    if not btn:
        # badge luogo
        try:
            elev = get_elev(lat,lon)
            tzname = detect_timezone(lat,lon)
        except Exception:
            elev = None; tzname = "Europe/Rome"
        st.markdown(
            f"<div class='badge'>📍 <b>{place_label}</b> · Alt <b>{int(elev) if elev is not None else '—'} m</b> · TZ <b>{tzname}</b></div>",
            unsafe_allow_html=True
        )
        return

    # RUN
    with st.status(T["status_title"], expanded=False) as status:
        try:
            tzname = detect_timezone(lat,lon)
            js = _retry(lambda: fetch_open_meteo(lat,lon))
            raw = build_df(js, hours)
            if raw.empty:
                st.error("Nessun dato meteo disponibile dalla fonte in questo momento.")
                status.update(label="Sorgente vuota", state="error", expanded=True)
                return

            # altitudine target (se presente in state, altrimenti elevazione)
            try:
                base_alt = get_elev(lat,lon) or 1800
            except Exception:
                base_alt = 1800
            target_alt = st.session_state.get("alt_m", base_alt)

            X = enrich_meteo_quickwins(raw, lat, lon, base_alt, target_alt)
            res = snow_temperature_model(X)

            tzobj = tz.gettz(tzname)
            res["time_local"] = res["time_utc"].dt.tz_convert(tzobj)

            # offset termico pista
            if abs(offset) > 0:
                res["T_surf"] = (res["T_surf"] + offset).round(2)
                res["T_top5"] = (res["T_top5"] + offset).round(2)
                near_zero_bonus = 20 * np.exp(-((res["T_surf"] + 0.4)/1.1)**2)
                humidity_bonus  = np.clip((res["RH"]-60)/40, 0, 1)*10
                radiation_bonus = np.clip(res["SW_down"]/600, 0, 1)*8
                wind_pen        = np.clip(res["wind"]/10, 0, 1)*10
                wet_pen         = np.clip(res["liq_water_pct"]/6, 0, 1)*25
                base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
                res["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)

            # Esponi per gli altri moduli
            st.session_state["_meteo_res"] = res

            # Badge + grafici
            st.success(f"{T['last_upd']}: {datetime.now().strftime('%H:%M')}")
            if do_debug:
                st.info(f"Rows: {len(res)} · time_local: {res['time_local'].min()} → {res['time_local'].max()} · lat={lat:.5f}, lon={lon:.5f}")
            _plot_series(res, T)

            status.update(label=f"{T['last_upd']}: {datetime.now().strftime('%H:%M')}", state="complete", expanded=False)

        except requests.exceptions.Timeout:
            status.update(label="Timeout servizio meteo. Clicca di nuovo per riprovare.", state="error", expanded=True)
        except requests.exceptions.HTTPError as e:
            status.update(label=f"Errore HTTP: {e}", state="error", expanded=True)
        except Exception as e:
            status.update(label=f"Errore: {e}", state="error", expanded=True)

# alias che l’orchestratore può usare
render = render_meteo
