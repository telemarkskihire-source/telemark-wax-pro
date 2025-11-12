import time, math, numpy as np, pandas as pd, requests, streamlit as st

UA = {"User-Agent":"telemark-wax-pro/1.0"}

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

def _retry(func, attempts=2, sleep=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i==attempts-1: raise
            time.sleep(sleep*(1.5**i))

def persist(key, default):
    if key not in st.session_state: st.session_state[key]=default
    return st.session_state[key]

def tt(h,m):
    from datetime import time as dtime
    return dtime(h,m)
