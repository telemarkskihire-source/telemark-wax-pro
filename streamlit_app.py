# --- IMPORT in alto, assicurati di avere anche questi ---
from datetime import date, timedelta
import numpy as np
import pandas as pd

# ---------------- 1) Scelta giorno + orizzonte ----------------
cdate, chz = st.columns([2,1])
with cdate:
    target_day = st.date_input(
        "Giorno di riferimento",
        value=date.today(),
        min_value=date.today() - timedelta(days=2),
        max_value=date.today() + timedelta(days=7),
        key="target_day"          # <- chiave stabile
    )
with chz:
    hours = st.slider("Orizzonte orario (max per il giorno scelto)", 6, 24, 12, 1)

# ---------------- Open-Meteo: aggiungo anche umidità relativa ----------------
def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon, "timezone": tzname,
            "hourly": ",".join([
                "temperature_2m","dew_point_2m","relative_humidity_2m",
                "precipitation","rain","snowfall",
                "cloudcover","windspeed_10m","is_day","weathercode"
            ]),
            "forecast_days": 7,
        },
        timeout=30
    )
    r.raise_for_status()
    return r.json()

# ---------------- Pulizia/filtri orari robusti ----------------
def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(r):
        prp  = float(r.get("precipitation", 0) or 0)
        rain = float(r.get("rain", 0) or 0)
        snow = float(r.get("snowfall", 0) or 0)
        if prp <= 0: return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(r.get("weathercode", 0) or 0)
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, target_day, hours):
    h  = js["hourly"]
    df = pd.DataFrame(h).copy()

    # cast sicuri
    for col in ["temperature_2m","dew_point_2m","relative_humidity_2m",
                "precipitation","rain","snowfall","cloudcover","windspeed_10m","is_day","weathercode"]:
        if col in df: df[col] = pd.to_numeric(df[col], errors="coerce")

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).reset_index(drop=True)

    # finestra del giorno scelto + hours
    day_start = pd.Timestamp(target_day)              # naive
    day_end   = day_start + pd.Timedelta(hours=hours)
    mask = (df["time"] >= day_start) & (df["time"] < day_end)
    df = df.loc[mask].reset_index(drop=True)

    # dataframe finale
    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"]
    out["td"]   = df["dew_point_2m"]
    out["RH"]   = df.get("relative_humidity_2m", np.nan)
    out["cloud"] = (df["cloudcover"]/100.0).clip(0,1)
    out["wind"]  = (df["windspeed_10m"]/3.6).clip(lower=0)  # m/s
    out["sunup"] = df["is_day"].fillna(0).astype(int)
    out["prp_mmph"] = df["precipitation"].fillna(0.0)
    out["prp_type"] = _prp_type(df[["precipitation","rain","snowfall","weathercode"]].fillna(0))
    return out

# ---------------- Modello T_surf / T_top5 migliorato e stabile ----------------
def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])

    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sun  = df["sunup"].astype(int).eq(1)

    # wet / dry heuristic + RH
    tw   = (df["T2m"] + df["td"]) / 2.0
    rh   = df["RH"].fillna(80)
    wet  = (
        rain |
        (df["T2m"] > 0.2) |
        (sun & (df["cloud"] < 0.35) & df["T2m"].ge(-2.5)) |
        (snow & df["T2m"].ge(-0.8)) |
        (snow & tw.ge(-0.5)) |
        (rh > 92)
    )

    T_surf = pd.Series(np.nan, index=df.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=7.0)
    # raffreddamento radiativo più realistico
    drad = (1.2 + 3.4*clear - 0.28*windc).clip(0.6, 4.8)
    T_surf.loc[dry] = (df["T2m"] - drad)[dry]

    # irraggiamento solare in aria fredda ma serena (non fissare a -0.5 costante)
    sunny_cold = sun & dry & df["T2m"].between(-12, 0, inclusive="both")
    T_surf.loc[sunny_cold] = np.minimum(
        (df["T2m"] + 0.6*(1.0 - df["cloud"]))[sunny_cold],
        -0.3
    )

    # dinamica dello strato superficiale 0–5 mm
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sun) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = pd.Series(1.0 - np.exp(-dt_hours / tau), index=df.index)

    T_top5 = pd.Series(index=df.index, dtype=float)
    if len(df) > 0:
        T_top5.iloc[0] = min(float(df["T2m"].iloc[0]), 0.0)
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    return df
