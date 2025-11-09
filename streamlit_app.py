# telemark_pro_app.py
import math, base64, os, json, time
from datetime import date, datetime, timedelta, time as dtime

import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =========================[ THEME / UI ]=========================
PRIMARY = "#10bfcf"     # Telemark turquoise
ACCENT  = "#f97316"     # warm accent
OK      = "#16a34a"
WARN    = "#f59e0b"
BAD     = "#ef4444"
TEXT    = "#e5f6f8"
BG1     = "#0b1221"
BG2     = "#0e172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg1:{BG1}; --bg2:{BG2}; --txt:{TEXT}; --pri:{PRIMARY}; --acc:{ACCENT};
}}
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 1200px at 10% -10%, #12223d 0%, {BG1} 45%, {BG2} 100%); }}
.block-container {{ padding-top: 0.8rem; padding-bottom:2rem; }}
h1,h2,h3,h4{{ color:{TEXT}; letter-spacing:.3px }}
p, label, span, div {{ color:{TEXT}; }}
.small {{ color:#a7c7c9; font-size:.86rem; }}
.badge {{
  display:inline-flex; align-items:center; gap:.45rem; border:1px solid #1e2a44; background:rgba(16,191,207,.08);
  padding:.25rem .6rem; border-radius:999px; font-size:.78rem;
}}
.card {{
  background:rgba(10,20,35,.55); border:1px solid rgba(255,255,255,.06);
  border-radius:16px; padding:12px 14px; box-shadow:0 10px 28px rgba(0,0,0,.35);
}}
.banner {{
  border-radius:14px; padding:10px 14px; border:1px solid rgba(255,255,255,.08);
  display:flex; justify-content:space-between; align-items:center;
}}
.btn-pri button{{ background:{ACCENT}; color:white; border-radius:10px; font-weight:700 }}
.metric {{
  display:flex; gap:10px; align-items:center; background:rgba(16,191,207,.08);
  border:1px dashed rgba(16,191,207,.35); padding:8px 10px; border-radius:12px;
}}
hr{{ border:none; border-top:1px solid rgba(255,255,255,.08); margin:.8rem 0 }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# =========================[ HELPERS ]=========================
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str):
    # Nome corto + regione/prov + ISO
    name = addr.get("hamlet") or addr.get("village") or addr.get("town") or addr.get("city") or fallback
    admin = addr.get("state") or addr.get("region") or addr.get("county") or ""
    iso = (addr.get("country_code") or "").upper()
    base = ", ".join([x for x in [name, admin] if x])
    return f"{base} — {iso}" if iso else base

# ---------------- Location search with optional country filter
def nominatim_search(q:str):
    country = st.session_state.get("country_filter","")
    if not q or len(q)<2: return []
    try:
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        if country: params["countrycodes"] = country.lower()
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params=params,
                         headers={"User-Agent":"telemark-pro-wax/1.0"},
                         timeout=8)
        r.raise_for_status()
        st.session_state._opts = {}
        out=[]
        for it in r.json():
            addr = it.get("address",{}) or {}
            label = f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
            lat=float(it.get("lat",0)); lon=float(it.get("lon",0))
            key=f"{label}|||{lat:.5f},{lon:.5f}"
            st.session_state._opts[key]={"lat":lat,"lon":lon,"addr":addr,"label":label}
            out.append(key)
        return out
    except: return []

def get_elevation(lat,lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js=r.json(); return float(js["elevation"][0])
    except: return None

# ---------------- NASA POWER (hourly) as primary source for radiation/RH
def fetch_nasa_power(lat,lon,start_iso,end_iso,tz_str):
    # variables: T2M,RH2M,WS2M,PS,ALLSKY_SFC_SW_DWN (W/m2), PRECTOTCORR (mm/h)
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point"
    params = {
        "parameters":"T2M,RH2M,WS2M,PS,ALLSKY_SFC_SW_DWN,PRECTOTCORR",
        "start":start_iso, "end":end_iso,
        "latitude":lat, "longitude":lon,
        "community":"re",
        "format":"JSON",
        "user":"telemark-pro-wax"
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()["properties"]["parameter"]
    # Build dataframe
    idx=[]
    for k in data["T2M"].keys():
        # NASA POWER timestamps are like YYYYMMDDHH
        dt = datetime.strptime(k, "%Y%m%d%H")
        idx.append(dt)
    df=pd.DataFrame(index=pd.to_datetime(idx).tz_localize("UTC").tz_convert(tz_str))
    def col(name, key):
        s = pd.Series(data[key]); s.index = df.index
        df[name] = pd.to_numeric(s.values, errors="coerce")
    col("T2m", "T2M")
    col("RH", "RH2M")
    col("wind_ms", "WS2M")
    col("pressure_hPa","PS")
    col("SW_Wm2","ALLSKY_SFC_SW_DWN")
    col("precip_mmph","PRECTOTCORR")
    return df.reset_index(names="dt")

# ---------------- Open-Meteo fallback (hourly)
def fetch_open_meteo(lat,lon,tz_str):
    params = {
        "latitude":lat,"longitude":lon,"timezone":tz_str,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,shortwave_radiation,windspeed_10m,surface_pressure,is_day,weathercode",
        "forecast_days":7
    }
    r=requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    h=r.json()["hourly"]
    df=pd.DataFrame(h)
    df["dt"]=pd.to_datetime(df["time"])
    out=pd.DataFrame({
        "dt":df["dt"],
        "T2m":df["temperature_2m"].astype(float),
        "RH":df["relative_humidity_2m"].astype(float),
        "Td":df["dew_point_2m"].astype(float),
        "wind_ms":(df["windspeed_10m"].astype(float)/3.6),
        "pressure_hPa":df.get("surface_pressure",pd.Series([1013]*len(df))).astype(float),
        "SW_Wm2":df.get("shortwave_radiation",pd.Series([0]*len(df))).astype(float),
        "precip_mmph":df["precipitation"].astype(float),
        "rain_mmph":df["rain"].astype(float),
        "snow_mmph":df["snowfall"].astype(float),
        "cloud":(df["cloudcover"].astype(float)/100).clip(0,1),
        "is_day":df["is_day"].astype(int),
        "wcode":df["weathercode"].astype(int)
    })
    return out

# ---------------- slice by date/hours horizon (local-tz)
def slice_day(df_local_tz, target_day:date, hours:int):
    start = datetime.combine(target_day, dtime(0,0))
    end   = start + timedelta(hours=hours)
    D = df_local_tz.copy()
    D = D[(D["dt"]>=start) & (D["dt"]<end)].reset_index(drop=True)
    return D

# ---------------- thermo helpers
def saturation_vapor_pressure(Tc):
    # Tetens (hPa), T in °C
    return 6.112 * math.exp((17.62*Tc)/(243.12+Tc))

def actual_vapor_pressure(Tc, RH):
    return RH/100.0 * saturation_vapor_pressure(Tc)

def dewpoint_from_T_RH(Tc, RH):
    try:
        a = 17.27; b = 237.7
        alpha = ((a*Tc)/(b+Tc)) + math.log(RH/100.0 + 1e-6)
        return (b*alpha)/(a-alpha)
    except: return Tc

def sky_emissivity(Tc, RH, cloud):
    # Brutsaert + cloud correction
    e_a = actual_vapor_pressure(Tc, RH)
    eps_clear = 1.24 * (e_a/10.0)**(1/7) - 0.065  # ~0.6–0.8
    eps_clear = max(0.5, min(0.9, eps_clear))
    return (1-cloud)*eps_clear + cloud*0.98

def solve_Tsnow_row(Ta, RH, wind, SW, cloud, fresh_snow_last12h):
    """
    Simple surface energy-balance relaxation for Ts (°C).
    Inputs per-hour. Returns Ts (°C) and top-5mm temp.
    """
    # Albedo: higher for fresh snow
    albedo = 0.85 if fresh_snow_last12h>0.5 else 0.68 if Ta<-3 else 0.55
    SWnet = (1-albedo) * max(0.0, SW)  # W/m2

    # initial guess
    Ts = min(Ta, 0.0)
    sigma = 5.670374419e-8
    P_atm = 101325.0  # Pa
    for _ in range(12):
        eps_sky = sky_emissivity(Ta, RH, cloud)
        LW_in = eps_sky * sigma * (Ta+273.15)**4
        LW_out = 0.99 * sigma * (Ts+273.15)**4
        # Sensible heat (bulk)
        H = 10.0 * wind * (Ta - Ts)   # W/m2
        # Latent heat from humidity gradient (very rough)
        Td = dewpoint_from_T_RH(Ta, RH)
        q = max(0.0, Ta - Td)
        LE = 6.0 * (q)  # W/m2
        # Ground conduction: drives Ts toward 0 if near melting
        G = 5.0 * (0 - Ts)

        Rn = SWnet + (LW_in - LW_out) + H + LE + G
        # Relaxation toward melt if positive energy
        Ts_new = Ts + 0.0025 * Rn
        # clamp: cannot exceed 0 when melting
        Ts = min(0.0, Ts_new)

    # top-5mm damped toward Ts with time constant
    Ttop = Ts if Ts>=0 else 0.8*Ts + 0.2*Ta
    return Ts, Ttop

def compute_snow_physics(df):
    """
    df columns: dt (local), T2m, RH, wind_ms, SW_Wm2, cloud?, precip_mmph, snow_mmph
    Returns df+ Tsnow, Ttop, wetness, snow_type, glide_index (0-100)
    """
    d = df.copy()
    # Ensure fields
    for c in ["cloud","snow_mmph","precip_mmph"]:
        if c not in d: d[c]=0.0
    if "RH" not in d:
        # approximate RH from T & precip via Td unknown -> assume 70%
        d["RH"]=70.0

    # Fresh snow last 12h (rolling sum up to current hour)
    if "snow_mmph" in d:
        roll_fresh = pd.Series(d["snow_mmph"]).rolling(12, min_periods=1).sum()
    else:
        roll_fresh = pd.Series([0.0]*len(d))
    Ts_list=[]; Ttop_list=[]; wet=[]; sntype=[]; glide=[]
    for i,row in d.iterrows():
        fresh12 = float(roll_fresh.iloc[i]) if not pd.isna(roll_fresh.iloc[i]) else 0.0
        Ts, Ttop = solve_Tsnow_row(
            float(row["T2m"]), float(row["RH"]),
            float(max(0.1,row["wind_ms"])), float(row.get("SW_Wm2",0.0)),
            float(row.get("cloud",0.5)), fresh12
        )
        Ts_list.append(Ts); Ttop_list.append(Ttop)
        # Wetness classification
        if row.get("rain_mmph",0)>0.1 or (row["T2m"]>-0.5 and Ts>-0.2):
            wetlvl="bagnata"
        elif fresh12>3:
            wetlvl="neve nuova"
        elif Ts<-6:
            wetlvl="fredda/secca"
        else:
            wetlvl="trasformata"
        sntype.append(wetlvl)

        # Glide index 0-100
        # Base on Ttop (~0 best), liquid water (wet), wind abrasion (old snow), and cloud (radiative cooling)
        base = 60 + 20*max(0, 1-abs(Ttop)/5)  # nearer to 0 -> faster
        if wetlvl=="bagnata": base += 10
        if wetlvl=="fredda/secca": base -= 10
        base += 5*(row["wind_ms"]>8)
        base -= 5*(row.get("cloud",0.5)<0.2)
        glide.append(int(max(5, min(98, base))))

    d["T_surf"]=Ts_list
    d["T_top5"]=Ttop_list
    d["snow_consistency"]=sntype
    d["glide_index"]=glide
    return d

# ---------------- snow condition banner + reliability
def describe_window(W:pd.DataFrame):
    if W.empty:
        return "Nessun dato", 0
    tmed = float(W["T_surf"].mean())
    fresh = float(W.get("snow_mmph",pd.Series([0])).sum())
    rain  = float(W.get("rain_mmph",pd.Series([0])).sum()) if "rain_mmph" in W else 0.0
    rhmed = float(W["RH"].mean()) if "RH" in W else 70.0
    wind  = float(W["wind_ms"].mean())
    # testo
    if rain>1 or (tmed>-0.2):
        txt = "Neve bagnata / sul punto di fusione"
    elif fresh>5:
        txt = "Neve nuova, struttura fine consigliata"
    elif tmed<-8:
        txt = "Neve molto fredda & secca"
    else:
        txt = "Neve trasformata"
    # affidabilità: peggiora con orizzonte e variabilità
    spread = (W["T2m"].max()-W["T2m"].min())
    horizon_h = len(W)
    reliab = 90 - 0.15*horizon_h - 2.0*spread - 0.1*abs(80-rhmed)
    reliab = int(max(40, min(95, reliab)))
    return txt, reliab

# ---------------- Wax bands (no images)
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Violet/Blue",-12,-4),("MX-E Red",-5,0),("MX-E Warm",-2,10)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
BRANDS = [("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE)]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# =========================[ UI – STEP 1: Location ]=========================
st.subheader("1) Località")
colc, cols = st.columns([1,3])
with colc:
    csel = st.selectbox("Filtra per nazione (facoltativo)", ["","IT","FR","CH","AT","DE","NO","SE","FI","ES","US","CA"], index=1)
    st.session_state["country_filter"] = csel
with cols:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita… (es. Champoluc, Plateau Rosa, Cervinia, Sestriere)",
        clear_on_submit=False,
        default=None
    )

# default Champoluc
if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    lat, lon, label = info["lat"], info["lon"], info["label"]
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat,lon,label
else:
    lat = st.session_state.get("sel_lat",45.831); lon = st.session_state.get("sel_lon",7.730)
    label = st.session_state.get("sel_label","🇮🇹  Champoluc, Valle d’Aosta — IT")

elev = get_elevation(lat,lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='badge'>📍 {label}{alt_txt}</div>", unsafe_allow_html=True)

# =========================[ STEP 2: Day & windows ]=========================
st.subheader("2) Giorno e finestre orarie A · B · C")
tzname = "Europe/Rome"  # fisso locale
today = datetime.now(tz=tz.gettz(tzname)).date()
cdate, chz = st.columns([2,2])
with cdate:
    target_day = st.date_input("Giorno di riferimento", value=today, min_value=today, max_value=today+timedelta(days=6))
with chz:
    hours = st.slider("Ore previsione (da mezzanotte del giorno scelto)", 6, 168 if target_day==today else 24, 72 if target_day==today else 24, 6)

c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", dtime(9,0), key="A_s"); A_end = st.time_input("Fine A", dtime(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", dtime(11,0), key="B_s"); B_end = st.time_input("Fine B", dtime(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", dtime(13,0), key="C_s"); C_end = st.time_input("Fine C", dtime(16,0), key="C_e")

# =========================[ STEP 3: Fetch & Physics ]=========================
st.subheader("3) Meteo & Analisi neve")
st.caption("Usiamo NASA POWER per radiazione/umidità e Open-Meteo come fallback. L’algoritmo fisico stima temperatura della neve, consistenza e **indice di scorrevolezza**.")

if st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True):
    try:
        # Build local time range
        start_local = datetime.combine(target_day, dtime(0,0)).replace(tzinfo=tz.gettz(tzname))
        end_local   = start_local + timedelta(hours=hours)
        # Timestamps for NASA POWER (UTC-based, but accepts local date range)
        start_iso = start_local.strftime("%Y%m%d%H")
        end_iso   = (end_local - timedelta(hours=1)).strftime("%Y%m%d%H")

        # Try NASA POWER
        try:
            nasa = fetch_nasa_power(lat,lon,start_iso,end_iso,tzname)
            df = nasa.rename(columns={"dt":"dt"})  # already local tz
            # approximate cloud from SW vs clear-sky guess if available not—use Open-Meteo later if missing
            df["cloud"]=0.3  # placeholder; refined if OM available
            primary="NASA POWER"
        except Exception:
            df = None
            primary=""

        # Open-Meteo for precip types & cloud & backup
        try:
            om = fetch_open_meteo(lat,lon,tzname)
            om = slice_day(om, target_day, hours)
            if df is None:
                df = om.copy()
                primary="Open-Meteo"
            else:
                # merge important columns if missing
                for c in ["rain_mmph","snow_mmph","cloud","is_day","wcode","Td"]:
                    if c in om.columns:
                        df[c] = om[c].values
        except Exception:
            if df is None:
                st.error("Errore nel download dati meteo.")
                st.stop()

        # Ensure local tz naive timestamps
        if "dt" not in df.columns:
            st.error("Dati meteo non contengono timestamp validi.")
            st.stop()
        df["dt"]=pd.to_datetime(df["dt"]).dt.tz_localize(None)

        # Slice by day (robusto) se la fonte ha più ore
        df = slice_day(df, target_day, hours)

        # Compute physics
        res = compute_snow_physics(df)

        # Show small summary
        st.success(f"Dati caricati da **{primary}** per **{label}**. Ore: {len(res)}")
        # Table: compact & clear
        show = res[["dt","T2m","RH","wind_ms","SW_Wm2","precip_mmph","T_surf","T_top5","snow_consistency","glide_index"]].copy()
        show = show.rename(columns={
            "dt":"Ora locale","T2m":"T aria (°C)","RH":"UR (%)","wind_ms":"Vento (m/s)","SW_Wm2":"SW (W/m²)",
            "precip_mmph":"Prec (mm/h)","T_surf":"T neve (°C)","T_top5":"T top 5mm (°C)","snow_consistency":"Consistenza","glide_index":"Indice di scorrevolezza"
        })
        st.dataframe(show, use_container_width=True, hide_index=True)

        # Charts
        t = pd.to_datetime(res["dt"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve"); plt.plot(t,res["T_top5"],label="Top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["precip_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # Windows A/B/C, banner + wax + table disciplines
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---")
            st.markdown(f"### Blocco {L}")
            W = res[(res["dt"].dt.time>=s) & (res["dt"].dt.time<=e)]
            txt, reliab = describe_window(W)
            color = OK if reliab>=75 else WARN if reliab>=60 else BAD
            st.markdown(f"<div class='banner' style='background:rgba(255,255,255,.03)'><div><b>Condizione prevalente:</b> {txt}</div><div style='color:{color}; font-weight:800'>Affidabilità: {reliab}%</div></div>", unsafe_allow_html=True)
            if W.empty:
                st.info("Nessun dato nella finestra selezionata.")
                continue

            t_med = float(W['T_surf'].mean())
            st.caption(f"T_neve medio: **{t_med:.1f}°C** · Indice di scorrevolezza medio: **{int(W['glide_index'].mean())}**")

            # Wax brands (testo)
            cols = st.columns(len(BRANDS))
            for i,(name,bands) in enumerate(BRANDS):
                rec = pick(bands, t_med)
                cols[i].markdown(f"<div class='metric'><span style='font-weight:800'>{name}</span><span>{rec}</span></div>", unsafe_allow_html=True)

            # Strutture – solo nomi, niente immagini
            if t_med <= -10:
                structure = "Lineare fine (freddo/secco)"
            elif t_med <= -3:
                structure = "Cross hatch / universale leggera"
            else:
                structure = "Diagonale di scarico (umido/caldo)"
            st.write(f"**Struttura consigliata:** {structure}")

            # Angoli tabella (SL/GS/SG/DH)
            def tune_for(t_surf, d):
                if t_surf <= -10:
                    base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
                elif t_surf <= -3:
                    base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
                else:
                    base = 0.8 if t_surf<=0.5 else 1.0
                    side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                return side,base
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                sdeg,bdeg=tune_for(t_med,d)
                rows.append([d, f"{sdeg:.1f}°", f"{bdeg:.1f}°", structure])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE","Lamina BASE","Struttura"]))

        st.info("Nota: **Indice di scorrevolezza** (0–100) stimato da T della neve, contenuto d’acqua, vento e nuvolosità; maggiore è meglio.")

    except Exception as e:
        st.error(f"Errore: {e}")
