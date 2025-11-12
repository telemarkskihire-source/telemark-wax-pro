# core/meteo.py
import io, math, requests, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime
from dateutil import tz

from .utils import UA, rh_from_t_td, wetbulb_stull, clear_sky_ghi, effective_wind

# ---- cache fetch ----
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

@st.cache_data(ttl=12*3600, show_spinner=False)
def detect_timezone(lat, lon):
    r = requests.get("https://api.open-meteo.com/v1/forecast",
                     params={"latitude":lat,"longitude":lon,"hourly":"temperature_2m","forecast_days":1,"timezone":"auto"},
                     headers=UA, timeout=10)
    r.raise_for_status(); return r.json().get("timezone","Europe/Rome")

# ---- pipeline (estratta dal tuo monoblocco) ----
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

def enrich_meteo_quickwins(df, lat, lon):
    X = df.copy()
    if X["RH"].isna().any(): X.loc[:, "RH"] = rh_from_t_td(X["T2m"], X["td"])
    X["Tw"] = wetbulb_stull(X["T2m"], X["RH"])
    X["wind_eff"] = effective_wind(X["wind"])
    sw_list = [clear_sky_ghi(lat, lon, ts.to_pydatetime()) for ts in X["time_utc"]]
    X["SW_clear"] = sw_list
    X["SW_down"] = X["SW_clear"] * (1 - 0.75*(X["cloud"]**3))
    # albedo semplice (senza snow age qui, per velocità)
    X["albedo"] = 0.75 - 0.15*np.clip(X["sunup"],0,1)
    # superficie neve (semplificata, coerente con monoblocco)
    conv = 0.20 * X["wind_eff"]
    rad_cool = (0.8 * (1.0 - X["cloud"]))
    sw_gain = (X["SW_down"] * (1 - X["albedo"])) / 200.0
    T_surf = X["T2m"] - conv - rad_cool + sw_gain
    X["T_surf"] = np.round(np.where(X["T2m"]>0.5, np.minimum(T_surf, 0.0), T_surf), 2)
    X["T_top5"] = np.round(np.minimum(X["T_surf"], X["T2m"]), 2)
    # bagnatura stimata
    excess = np.clip(sw_gain - conv - rad_cool, 0, None)
    wetness = ( (X["T2m"]> -0.5).astype(float) + (excess/5.0) )
    X["liq_water_pct"] = np.round(np.clip(wetness, 0, 6.0), 1)
    # speed index semplificato
    near_zero_bonus = 20 * np.exp(-((X["T_surf"] + 0.4)/1.1)**2)
    humidity_bonus  = np.clip((X["RH"]-60)/40, 0, 1)*10
    radiation_bonus = np.clip(X["SW_down"]/600, 0, 1)*8
    wind_pen        = np.clip(X["wind"]/10, 0, 1)*10
    wet_pen         = np.clip(X["liq_water_pct"]/6, 0, 1)*25
    base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
    X["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)
    return X

# ---- RENDER ----
def render_meteo(T, ctx):
    st.markdown("#### 3) Meteo & calcolo")
    lat, lon = float(ctx["lat"]), float(ctx["lon"])
    tzname = detect_timezone(lat, lon)

    hours = st.slider(T["horizon"]+" ("+("da ora" if ctx["lang"]=="IT" else "from now")+")",
                      12, 168, st.session_state.get("hours", 72), 12, key="hours_meteo")

    if st.button(T["fetch"], type="primary", use_container_width=True, key="fetch_meteo"):
        with st.status(T["status_title"], expanded=False):
            js = fetch_open_meteo(lat, lon)
            raw = build_df(js, hours)
            if raw.empty:
                st.error("Nessun dato meteo disponibile al momento."); return
            X = enrich_meteo_quickwins(raw, lat, lon)
            tzobj = tz.gettz(tzname)
            X["time_local"] = X["time_utc"].dt.tz_convert(tzobj)

            # salva per altri moduli (wax, tabelle, ecc.)
            st.session_state["_meteo_res"]  = X
            st.session_state["_meteo_tz"]   = tzname
            st.session_state["_meteo_when"] = datetime.now().isoformat()

            tloc = X["time_local"].dt.tz_localize(None)

            fig1 = plt.figure(figsize=(10,3))
            plt.plot(tloc, X["T2m"], label=T["t_air"])
            plt.plot(tloc, X["T_surf"], label=T["t_surf"])
            plt.plot(tloc, X["T_top5"], label=T["t_top5"])
            plt.legend(); plt.title(T["temp"]); plt.xlabel(T["hour"]); plt.ylabel("°C"); plt.grid(alpha=0.2)
            st.pyplot(fig1); plt.close(fig1)

            fig2 = plt.figure(figsize=(10,2.6))
            plt.bar(tloc, X["prp_mmph"], width=0.025)
            plt.title(T["prec"]); plt.xlabel(T["hour"]); plt.ylabel("mm/h"); plt.grid(alpha=0.2)
            st.pyplot(fig2); plt.close(fig2)

            st.success(f"{T['last_upd']}: {datetime.now().strftime('%H:%M')}")
    else:
        if "_meteo_res" in st.session_state:
            st.info("Dati meteo già calcolati (riusa cache). Clicca **Aggiorna** per ricalcolare.")

# alias
render = render_meteo
