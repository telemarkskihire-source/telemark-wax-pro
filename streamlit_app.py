# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark, country-prefilter search, improved snow model + quick-wins, graphs, tuning tables

import os, math, base64, requests, pandas as pd, numpy as np
import streamlit as st
from datetime import datetime, date, time, timedelta
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
.btn-primary button {{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important; }}
.slider-tip {{ color:var(--muted); font-size:.85rem }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

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

def rh_from_t_td(T, Td):
    """UR% da T e Td (Magnus)."""
    T = np.array(T, dtype=float); Td = np.array(Td, dtype=float)
    a,b = 17.625, 243.04
    es  = 6.1094 * np.exp((a*T)/(b+T))
    e   = 6.1094 * np.exp((a*Td)/(b+Td))
    RH  = 100.0 * (e / es)
    return np.clip(RH, 1, 100)

def wetbulb_stull(T, RH):
    """Bulbo umido approssimato (Stull 2011), T in °C, RH in %."""
    RH = np.clip(RH, 1, 100)
    Tw = T * np.arctan(0.151977 * (RH + 8.313659)**0.5) + np.arctan(T + RH) - np.arctan(RH - 1.676331) + 0.00391838 * (RH**1.5) * np.arctan(0.023101*RH) - 4.686035
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
    """Clip 0..8 m/s, rendimenti decrescenti (log1p)."""
    w = np.clip(w, 0, 8.0)
    return 8.0 * (np.log1p(w) / np.log1p(8.0))

# ---------------------- SEARCH with COUNTRY prefilter ----------------------
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
    iso2 = COUNTRIES[sel_country]
with colSB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q":q, "format":"json", "limit":12, "addressdetails":1, "countrycodes": iso2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"},
                timeout=8
            )
            r.raise_for_status()
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
        nominatim_search, key="place", placeholder="Cerca… es. Champoluc, Plateau Rosa",
        clear_on_submit=False, default=None
    )

def get_elev(lat,lon):
    try:
        rr = requests.get("https://api.open-meteo.com/v1/elevation",
                          params={"latitude":lat, "longitude":lon}, timeout=8)
        rr.raise_for_status(); js = rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# ---------------------- DATE & WINDOWS + DOWNSCALING ALT ----------------------
cdate, calt = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())
with calt:
    pista_alt = st.number_input("Altitudine pista/garà (m)", min_value=0, max_value=5000, value=int(elev or 1800), step=50)

st.subheader("1) Finestre orarie A · B · C")
c1,c2,c3 = st.columns(3)
def tt(h,m): return time(h,m)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   tt(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", tt(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   tt(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", tt(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   tt(16,0), key="C_e")

st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)
st.markdown("<div class='slider-tip'>Suggerimento: < 48h → stime più affidabili</div>", unsafe_allow_html=True)

# ---------------------- METEO (Open-Meteo) ----------------------
def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone="UTC",
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7,
        ),
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"], utc=True)  # UTC
    now0 = pd.Timestamp.utcnow().floor("H")
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)
    out = pd.DataFrame()
    out["time_utc"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    if "relative_humidity_2m" in df: out["RH"] = df["relative_humidity_2m"].astype(float)
    else: out["RH"] = np.nan
    out["td"]   = df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"] = df.get("weathercode",0).astype(int)
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

# ---------------------- NOAA (optional robust bias) ----------------------
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)

def _noaa_nearby_station(lat, lon, radius_m=25000, limit=3):
    """Trova alcune stazioni GHCND vicine."""
    r = requests.get(
        "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations",
        params={"datasetid":"GHCND","limit":limit,"sortfield":"distance",
                "latitude":lat,"longitude":lon,"radius":radius_m},
        headers={"token": NOAA_TOKEN}, timeout=10
    )
    j = r.json()
    return (j.get("results") or [])

def _noaa_normals_dly(station_id):
    """Scarica NORMAL_DLY per TAVG e PCT precipitazione (giornaliere)."""
    # La API CDO in molti casi richiede un periodo; per le NORMAL_DLY il range annuale è ok (anno fittizio).
    # Riduciamo il payload: solo datatype utili e limit alto.
    params = {
        "datasetid": "NORMAL_DLY",
        "stationid": station_id,
        "datatypeid": ["DLY-TAVG-NORMAL","DLY-PRCP-PCTALL-GE001HI"],
        "startdate": "2010-01-01",
        "enddate":   "2010-12-31",
        "limit": 1000
    }
    r = requests.get("https://www.ncdc.noaa.gov/cdo-web/api/v2/data",
                     params=params, headers={"token": NOAA_TOKEN}, timeout=12)
    j = r.json()
    vals = j.get("results") or []
    out = {}
    for rec in vals:
        dt = rec.get("date","")
        mmdd = dt[5:10]  # "MM-DD"
        dtype = rec.get("datatype")
        val = rec.get("value")
        if val is None: continue
        if dtype not in out: out[dtype] = {}
        out[dtype][mmdd] = val
    return out  # dict: dtype -> { "MM-DD": value }

def noaa_bias_correction(df, lat, lon):
    """Layer robusto NOAA: bias termico parziale da NORMAL_DLY TAVG del giorno, nudging RH & Prp."""
    if not NOAA_TOKEN:
        return df
    try:
        stns = _noaa_nearby_station(lat, lon)
        if not stns:
            return df
        sid = stns[0]["id"]

        normals = _noaa_normals_dly(sid)
        if not normals:
            # fallback soft (identico a prima se normals mancano)
            df2 = df.copy()
            df2["T2m"] = df2["T2m"] + np.sign(0 - df2["T2m"])*0.3
            df2["RH"]  = np.where(np.isnan(df2["RH"]), 70.0, df2["RH"])
            df2["RH"]  = df2["RH"] + (70 - df2["RH"])*0.03
            return df2

        # giorno mese-corrente (UTC)
        now = datetime.utcnow().date()
        mmdd = now.strftime("%m-%d")

        # T media normale del giorno (decimi °C nelle normals). Alcuni set sono in decimi.
        tnorm_raw = normals.get("DLY-TAVG-NORMAL", {}).get(mmdd, None)
        tnorm = None
        if tnorm_raw is not None:
            # le NORMAL_DLY spesso sono in decimi di °C
            tnorm = float(tnorm_raw)/10.0

        # pct-giornaliero (prob di prp >= 0.1"): indicativo solo per nudging
        prp_pct = normals.get("DLY-PRCP-PCTALL-GE001HI", {}).get(mmdd, None)
        if prp_pct is not None:
            prp_pct = float(prp_pct)  # percentuale 0..100

        df2 = df.copy()

        # ---- Bias T2m (parziale) ----
        if tnorm is not None:
            med_model = float(np.nanmedian(df2["T2m"].values))
            bias = tnorm - med_model           # quanto il modello si discosta dalla norma
            adj = np.clip(0.5*bias, -1.2, 1.2) # applica 50% del bias, fino a ±1.2°C
            df2["T2m"] = df2["T2m"] + adj
            # dew-point coerente: sposta di stessa entità
            df2["td"]  = df2["td"]  + adj

        # ---- RH nudging verso 70% (very light) ----
        df2["RH"]  = np.where(np.isnan(df2["RH"]), 70.0, df2["RH"])
        df2["RH"]  = df2["RH"] + (70 - df2["RH"])*0.03
        df2["RH"]  = np.clip(df2["RH"], 1, 100)

        # ---- Precip nudging: se giorno climatologicamente umido (>60%), aumenta del +10% la prp prevista (soft) ----
        if prp_pct is not None and prp_pct >= 60:
            df2["prp_mmph"] = df2["prp_mmph"] * 1.10
            df2["rain"]     = df2["rain"] * 1.10
            df2["snowfall"] = df2["snowfall"] * 1.10

        return df2
    except Exception:
        # in caso di qualunque errore: ritorna i dati così come sono
        return df

# ---------------------- DOWNSCALING ALTITUDINALE ----------------------
def lapse_correction(T, base_alt, target_alt, lapse=-6.5):
    dz = (target_alt - (base_alt or target_alt))
    return T + (lapse/1000.0) * dz

# ---------------------- QUICK-WINS & SNOW MODEL ----------------------
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

# ---------------------- WAX BRANDS (with humidity hint) ----------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]

def pick_wax(bands, t, rh):
    name = bands[0][0]
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax:
            name = n; break
    rh_tag = " (secco)" if rh<60 else " (medio)" if rh<80 else " (umido)"
    return name + rh_tag

# >>> NEW: forma sciolina + sequenza spazzole (in base a T neve e UR) <<<
def wax_form_and_brushes(t_surf: float, rh: float):
    """
    Ritorna (form_str, brushes_str).
    - Forma: 'Solida (panetto)' oppure 'Liquida (topcoat)' per condizioni calde/umide.
    - Spazzole: sequenza consigliata generica (compatibile con la maggior parte dei brand).
    """
    # forma
    if (t_surf > -1.0) or (rh >= 80):
        form = "Liquida (topcoat) su base solida"
        is_liquid = True
    else:
        form = "Solida (panetto)"
        is_liquid = False

    # regime termico
    if t_surf <= -12:
        regime = "very_cold"
    elif t_surf <= -5:
        regime = "cold"
    elif t_surf <= -1:
        regime = "medium"
    else:
        regime = "warm"

    # sequenze (generiche e corte)
    if is_liquid:
        if regime in ("very_cold","cold"):
            brushes = "Ottone → Nylon duro → Feltro/Rotowool → Nylon morbido"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Feltro/Rotowool → Crine"
        else:  # warm
            brushes = "Ottone → Nylon → Feltro/Rotowool → Panno microfibra"
    else:
        if regime == "very_cold":
            brushes = "Ottone → Nylon duro → Crine"
        elif regime == "cold":
            brushes = "Ottone → Nylon → Crine"
        elif regime == "medium":
            brushes = "Ottone → Nylon → Crine → Nylon fine"
        else:  # warm
            brushes = "Ottone → Nylon → Nylon fine → Panno"

    return form, brushes

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

# ---------------------- RUN ----------------------
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon)
        raw = build_df(js, hours)

        # NOAA bias (robusto, con normals giornaliere se disponibili)
        raw = noaa_bias_correction(raw, lat, lon)

        # Enrich quick-wins (+ downscaling to pista_alt)
        base_alt = elev or pista_alt
        X = enrich_meteo_quickwins(raw, lat, lon, base_alt, pista_alt)

        # Snow model
        res = snow_temperature_model(X)

        # Local time for display (Europe/Rome)
        tzobj = tz.gettz("Europe/Rome")
        res["time_local"] = res["time_utc"].dt.tz_convert(tzobj)

        # --------- GRAPHS ----------
        tloc = res["time_local"]
        fig1 = plt.figure(figsize=(10,3))
        plt.plot(tloc, res["T2m"], label="T aria")
        plt.plot(tloc, res["T_surf"], label="T neve (superficie)")
        plt.plot(tloc, res["T_top5"], label="T neve (top 5mm)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); plt.grid(alpha=0.2)
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(10,2.6))
        plt.bar(tloc, res["prp_mmph"], width=0.03, align="center")
        plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); plt.grid(alpha=0.2)
        st.pyplot(fig2)

        fig3 = plt.figure(figsize=(10,2.6))
        plt.plot(tloc, res["SW_down"], label="SW_down stimata")
        plt.plot(tloc, res["RH"], label="UR%")
        plt.legend(); plt.title("Radiazione stimata & Umidità"); plt.grid(alpha=0.2)
        st.pyplot(fig3)

        # --------- TABLE (clean) ----------
        show = pd.DataFrame({
            "Ora":    res["time_local"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["td"].round(1),
            "UR (%)":      res["RH"].round(0),
            "Tw (°C)":     res["Tw"].round(1),
            "Vento eff (m/s)": res["wind_eff"].round(1),
            "Nuvolosità (%)":  (res["cloud"]*100).round(0),
            "SW↓ (W/m²)":  res["SW_down"].round(0),
            "Prp (mm/h)":  res["prp_mmph"].round(2),
            "Tipo prp":    res["ptyp"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "H₂O liquida (%)":  res["liq_water_pct"].round(1),
            "Indice scorrevolezza": res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --------- BLOCKS A/B/C ----------
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            mask_day = res["time_local"].dt.date == target_day
            day_df = res[mask_day].copy()
            if day_df.empty:
                W = res.head(7).copy()
            else:
                sel = day_df[(day_df["time_local"].dt.time>=s) & (day_df["time_local"].dt.time<=e)]
                W = sel if not sel.empty else day_df.head(6)

            if W.empty:
                st.info("Nessun dato nella finestra scelta.")
                continue

            t_med = float(W["T_surf"].mean())
            rh_med = float(W["RH"].mean())
            k = classify_snow(W.iloc[0])
            rel = reliability((W.index[0] if not W.empty else 0) + 1)

            st.markdown(
                f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                f"<b>T_neve med</b> {t_med:.1f}°C · <b>H₂O liquida</b> {float(W['liq_water_pct'].mean()):.1f}% · "
                f"<b>Affidabilità</b> ≈ {rel}%</div>",
                unsafe_allow_html=True
            )

            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            # >>> forma + spazzole
            wax_form, brush_seq = wax_form_and_brushes(t_med, rh_med)

            # Wax (8 brand) con RH bands + forma + spazzole
            st.markdown("**Scioline suggerite:**")
            ccols1 = st.columns(4); ccols2 = st.columns(4)
            for i,(name,bands) in enumerate(BRANDS[:4]):
                rec = pick_wax(bands, t_med, rh_med)
                ccols1[i].markdown(
                    f"<div class='brand'><div><b>{name}</b>"
                    f"<div style='color:#a9bacb'>{rec}</div>"
                    f"<div style='color:#93b2c6;font-size:.85rem'>Forma: {wax_form}</div>"
                    f"<div style='color:#93b2c6;font-size:.85rem'>Spazzole: {brush_seq}</div>"
                    f"</div></div>", unsafe_allow_html=True
                )
            for i,(name,bands) in enumerate(BRANDS[4:]):
                rec = pick_wax(bands, t_med, rh_med)
                ccols2[i].markdown(
                    f"<div class='brand'><div><b>{name}</b>"
                    f"<div style='color:#a9bacb'>{rec}</div>"
                    f"<div style='color:#93b2c6;font-size:.85rem'>Forma: {wax_form}</div>"
                    f"<div style='color:#93b2c6;font-size:.85rem'>Spazzole: {brush_seq}</div>"
                    f"</div></div>", unsafe_allow_html=True
                )

            # Mini tabella finestra
            mini = pd.DataFrame({
                "Ora": W["time_local"].dt.strftime("%H:%M"),
                "T aria": W["T2m"].round(1),
                "T neve": W["T_surf"].round(1),
                "UR%":   W["RH"].round(0),
                "V m/s": W["wind"].round(1),
                "Prp":   W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
            })
            st.dataframe(mini, use_container_width=True, hide_index=True)

            # Tuning per discipline (tabella ripristinata)
            st.markdown("**Tuning per disciplina (SIDE/BASE):**")
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

        # Download CSV completo
        csv = res.copy()
        csv["time_local"] = csv["time_local"].dt.strftime("%Y-%m-%d %H:%M")
        csv = csv.drop(columns=["time_utc"])
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
