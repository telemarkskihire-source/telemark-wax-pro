# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, math, base64
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ------------------------ THEME / STYLE ------------------------
PRIMARY = "#10bfcf"     # Telemark turquoise
ACCENT  = "#60a5fa"     # bright blue
WARN    = "#f59e0b"     # amber
DANGER  = "#ef4444"     # red
OK      = "#22c55e"     # green
TEXT    = "#e5e7eb"
BG      = "#0b1020"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% 0%, #101633 0%, {BG} 40%, #0a0f1d 100%);
}}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4,h5, p, span, label, div {{ color:{TEXT}; }}
.small {{ opacity:.8; font-size:.84rem; }}
.kpi {{ display:flex; gap:.6rem; align-items:center; padding:.6rem .8rem;
       border-radius:12px; border:1px solid rgba(255,255,255,.08);
       background:rgba(255,255,255,.04) }}
.tag {{ padding:.25rem .6rem; border-radius:999px; font-weight:700; font-size:.75rem;
        border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06) }}
.badge-ok {{ background:{OK}22; border-color:{OK}77; }}
.badge-warn {{ background:{WARN}22; border-color:{WARN}77; }}
.badge-danger {{ background:{DANGER}22; border-color:{DANGER}77; }}
.brand {{ display:flex; align-items:center; gap:.6rem; padding:.55rem .7rem;
          border-radius:12px; border:1px solid rgba(255,255,255,.1);
          background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02)); }}
.brand img {{ height:18px; filter: brightness(1.1) contrast(1.05); }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.12); margin:.9rem 0 }}
table td, table th {{ color:{TEXT}; }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # Nome corto + admin1 + sigla paese
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: 
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.0"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._opts = {}
        out = []
        for item in r.json():
            addr = item.get("address",{}) or {}
            label_short = concise_label(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            k = f"{flag_emoji(cc)}  {label_short}|||{lat:.6f},{lon:.6f}"
            st.session_state._opts[k] = {"lat":lat,"lon":lon,"addr":addr}
            out.append(k)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        e = r.json().get("elevation")
        if e and len(e)>0: return float(e[0])
    except: pass
    return None

# ------------------------ INPUT: LOCALITÀ ------------------------
st.markdown("#### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi… (es. Champoluc, Plateau Rosa, Sestriere, Livigno)",
    clear_on_submit=False,
    default=None
)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    if info:
        lat, lon = info["lat"], info["lon"]
        place_label = selected.split("|||")[0]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
elev_txt = f" · Alt **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><span class='tag'>{place_label}</span><span class='small'>Lat {lat:.3f} · Lon {lon:.3f}{elev_txt}</span></div>", unsafe_allow_html=True)

# ------------------------ FINESTRE A/B/C ------------------------
st.markdown("#### 2) Finestre orarie (oggi)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ METEO DATA ------------------------
def fetch_open_meteo(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Rome",
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","rain","snowfall","cloudcover",
            "windspeed_10m","is_day","weathercode"
        ]),
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"] = df["temperature_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    # RH may arrive as either key; try both
    rh_key = "relative_humidity_2m" if "relative_humidity_2m" in df.columns else "relativehumidity_2m"
    out["RH"]  = df.get(rh_key, pd.Series([None]*len(df))).astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)   # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

# ------------------------ SNOW TEMPERATURE MODEL ------------------------
def compute_snow_temperature(df, dt_hours=1.0):
    """
    Modello semplificato ma fisicamente sensato:
    - Pioggia o T>0 con precipitazione -> superficie ~ 0°C
    - Neve in atto -> superficie vicino a 0°C ma può essere fino a ~ -1°C
    - Notte serena -> raffreddamento radiativo (fino a 3–5°C sotto T2m)
    - Giorno soleggiato freddo -> lieve smorzamento
    - Limiti fisici: T_surf >= td - 2°C (non molto più fredda del dewpoint), T_surf <= 0°C quando bagnata
    - Strato top5 mm con memoria esponenziale (tau dinamica)
    """
    D = df.copy()
    is_night = D["sunup"].eq(0)
    prp = D["prp_mmph"].fillna(0)
    rain = D["prp_type"].eq("rain")
    snow = D["prp_type"].eq("snow")
    cloud = D["cloud"].fillna(0.5)
    wind = D["wind"].fillna(1.5)
    T2m  = D["T2m"].astype(float)
    td   = D["td"].astype(float)

    # Base estimate
    T_surf = T2m.copy()

    # Radiative cooling at night (clear nights stronger)
    cool = (1.5 + 4.0*(1.0-cloud) - 0.25*wind).clip(0.0, 5.0)
    T_surf = T_surf.where(~is_night, T2m - cool)

    # Daytime slight cooling if very clear & subzero
    day_clear = (~is_night) & (cloud<0.3) & (T2m<0)
    T_surf = T_surf.where(~day_clear, T2m - 0.7)

    # Precipitation effects
    wet_mask = (rain & (prp>0)) | ((prp>0) & (T2m>0))
    T_surf = T_surf.where(~wet_mask, 0.0)

    snow_mask = (snow & (prp>0))
    T_surf = T_surf.where(~snow_mask, T_surf.clip(upper=-0.2).where(T2m<-1.0, -0.3))

    # Physical caps: not much colder than dewpoint - 2°C; never above 0.0 if surface likely wet
    T_surf = T_surf.clip(upper=0.0)
    T_surf = pd.concat([T_surf, td - 2.0], axis=1).max(axis=1)

    # Memory for top 5mm
    tau = pd.Series(6.0, index=D.index)
    tau.loc[wet_mask | snow_mask | (wind>=6)] = 3.0
    tau.loc[(is_night) & (wind<2) & (cloud<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau.clip(lower=1.0)))

    T_top5 = pd.Series(index=D.index, dtype=float)
    if len(D)>0:
        T_top5.iloc[0] = min(T2m.iloc[0], 0.0)
        for i in range(1, len(D)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i] - T_top5.iloc[i-1])

    D["T_surf"] = T_surf
    D["T_top5"] = T_top5
    return D

# ------------------------ CLASSIFICATION / BANNERS ------------------------
def chromatic_index(t_surf: float)->int:
    # -15°C -> 0 (blu), 0°C -> 100 (rosso)
    return int((max(min(t_surf, 0.0), -15.0) + 15.0) / 15.0 * 100)

def snow_condition_block(window_df: pd.DataFrame):
    if window_df.empty:
        return ("Dati insufficienti", 40, "badge-warn")
    t = float(window_df["T_surf"].mean())
    rh = float(window_df["RH"].mean()) if "RH" in window_df else None
    prp = float(window_df["prp_mmph"].sum())
    snowing = (window_df["prp_type"]=="snow").any()
    raining = (window_df["prp_type"]=="rain").any()
    wind = float(window_df["wind"].mean())

    # Heuristics
    if snowing and t <= -2.0:
        label = "Neve nuova, asciutta"
        score = 85
        css = "badge-ok"
    elif snowing and -2.0 < t <= -0.3:
        label = "Neve nuova, umida"
        score = 80
        css = "badge-ok"
    elif (raining or (t>-0.5 and prp>0.5)):
        label = "Neve bagnata / primaverile"
        score = 75
        css = "badge-warn"
    elif t <= -7.0 and wind<6:
        label = "Molto fredda, secca"
        score = 70
        css = "badge-ok"
    else:
        label = "Trasformata / granulosa"
        score = 65
        css = "badge-warn"

    # Penalty for borderline 0°C
    if -1.0 < t < 0.0:
        score -= 7
        css = "badge-warn"

    # RH sanity
    if rh is not None and (rh<50 or rh>98):
        score -= 5

    score = int(max(40, min(92, score)))
    return (label, score, css)

# ------------------------ WAX BRANDS & STRUCTURES (names only) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]

BRANDS = [
    ("Swix", SWIX), ("Toko", TOKO), ("Vola", VOLA), ("Rode", RODE),
    ("Holmenkol", HOLM), ("Maplus", MAPL), ("Start", START), ("Skigo", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_for(t_surf, discipline):
    # Restituisce solo il NOME della struttura + angoli consigliati (SIDE/BASE)
    if t_surf <= -10:
        sname = "Lineare fine (freddo/secco)"
        base = 0.5; side = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}.get(discipline,88.0)
    elif t_surf <= -3:
        sname = "Incrociata leggera (universale)"
        base = 0.7; side = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}.get(discipline,88.0)
    else:
        sname = "Scarico diagonale / V (umido/caldo)"
        base = 0.8 if t_surf <= 0.5 else 1.0
        side = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}.get(discipline,88.0)
    return sname, side, base

# ------------------------ RUN ------------------------
st.markdown("#### 3) Scarica meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        # ===== KPI ROW =====
        t_now = float(res["T2m"].iloc[0])
        rh_now = float(res["RH"].iloc[0]) if "RH" in res and pd.notna(res["RH"].iloc[0]) else None
        t_surf_now = float(res["T_surf"].iloc[0])
        ci = chromatic_index(t_surf_now)
        color_ci = OK if ci<35 else (WARN if ci<75 else DANGER)
        k1,k2,k3 = st.columns([1,1,1])
        with k1:
            st.markdown(f"<div class='kpi'><span class='tag'>Aria</span><b>{t_now:.1f}°C</b>"
                        + (f"<span class='small'> · RH {rh_now:.0f}%</span>" if rh_now is not None else "")
                        + "</div>", unsafe_allow_html=True)
        with k2:
            st.markdown(f"<div class='kpi'><span class='tag'>Neve (superficie)</span><b>{t_surf_now:.1f}°C</b></div>", unsafe_allow_html=True)
        with k3:
            st.markdown(f"<div class='kpi'><span class='tag' style='border-color:{color_ci}; background:{color_ci}22'>Indice cromatico</span><b style='color:{color_ci}'>{ci}</b>/100</div>", unsafe_allow_html=True)

        # ===== TABELLA COMPATTA =====
        tbl = res[["time","T2m","td","RH","cloud","wind","prp_mmph","prp_type","T_surf","T_top5"]].copy()
        tbl.columns = ["Ora","T aria (°C)","DewPt (°C)","RH (%)","Nuvolosità","Vento (m/s)","Prec (mm/h)","Tipo","T neve (°C)","Top5mm (°C)"]
        tbl["Ora"] = pd.to_datetime(tbl["Ora"]).dt.strftime("%d/%m %H:%M")
        st.dataframe(tbl.round({"T aria (°C)":1,"DewPt (°C)":1,"RH (%)":0,"Nuvolosità":2,"Vento (m/s)":1,"Prec (mm/h)":2,"T neve (°C)":1,"Top5mm (°C)":1}),
                     use_container_width=True, height=340)

        # ===== GRAFICI =====
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure()
        plt.plot(t,res["T2m"],label="T aria")
        plt.plot(t,res["T_surf"],label="T superficie neve")
        plt.plot(t,res["T_top5"],label="Top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure()
        plt.bar(t, res["prp_mmph"])
        plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        st.download_button("Scarica CSV risultati",
                           data=res.to_csv(index=False),
                           file_name="forecast_snow_temperature.csv",
                           mime="text/csv")

        # ===== BLOCCHI A/B/C =====
        def window_slice(D, tzname, s, e):
            tt = pd.to_datetime(D["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
            X = D.copy(); X["dt"] = tt
            today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
            W = X[(X["dt"].dt.date==today) & (X["dt"].dt.time>=s) & (X["dt"].dt.time<=e)]
            return W if not W.empty else X.head(6)

        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, "Europe/Rome", s, e)
            t_med = float(W["T_surf"].mean())
            cond, score, css = snow_condition_block(W)
            st.markdown(f"<div class='kpi'><span class='tag'>T_surf medio</span><b>{t_med:.1f}°C</b>"
                        f"<span class='tag {css}'> {cond} · Affidabilità {score}%</span></div>", unsafe_allow_html=True)

            # Wax per marchio
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(f"<div class='brand'><span class='tag'>{brand}</span><b>{rec}</b></div>", unsafe_allow_html=True)
            for i,(brand,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(f"<div class='brand'><span class='tag'>{brand}</span><b>{rec}</b></div>", unsafe_allow_html=True)

            # Strutture (solo nome) + angoli per discipline
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                sname, side, base = tune_for(t_med, d)
                rows.append([d, sname, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura consigliata","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
