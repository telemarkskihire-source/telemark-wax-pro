# telemark_pro_app.py
# Telemark · Pro Wax & Tune — vNEXT (blend GFS + best, RH, radiation, snow-temp & scorrevolezza)
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time, datetime, timedelta, date
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ------------------------ THEME (dark + colori vivi) ------------------------
PRIMARY = "#0fe1ff"      # turchese brillante
ACCENT  = "#e5f2ff"      # testi chiari
MUTED   = "#9fb6c7"      # testo secondario
CARD_BG = "#0b1220"      # card
APP_BG  = "#0a0f1a"      # sfondo
WARN    = "#f59e0b"; OK = "#22c55e"; BAD = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 800px at 10% -10%, #0c1626 0%, {APP_BG} 50%); }}
.block-container {{ padding-top: .6rem; }}
h1,h2,h3,h4,h5,label,p,span,div {{ color:{ACCENT}; }}
.small {{ color:{MUTED}; font-size:.85rem }}
.card {{ background:{CARD_BG}; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:14px; box-shadow:0 12px 30px rgba(0,0,0,.35); }}
.brand {{ display:flex; align-items:center; gap:.7rem; padding:.5rem .7rem; border-radius:12px; background:#0e1a2e; border:1px solid rgba(255,255,255,.10); }}
.brand img {{ height:22px; }}
.kpi {{ display:flex; gap:.6rem; align-items:center; background:rgba(15,225,255,.07); border:1px dashed rgba(15,225,255,.45); padding:.5rem .7rem; border-radius:12px; }}
.badge {{ background:#132236; border:1px solid rgba(255,255,255,.10); color:{ACCENT}; padding:.2rem .5rem; border-radius:999px; font-size:.8rem }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.10); margin:.75rem 0 }}
.btn-pri button {{ background:{PRIMARY}!important; color:#00131a!important; font-weight:700 }}
.alert-ok {{ background: rgba(34,197,94,.1); border:1px solid rgba(34,197,94,.5); padding:.6rem .8rem; border-radius:12px; }}
.alert-warn {{ background: rgba(245,158,11,.12); border:1px solid rgba(245,158,11,.5); padding:.6rem .8rem; border-radius:12px; }}
.alert-bad {{ background: rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.5); padding:.6rem .8rem; border-radius:12px; }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# ------------------------ UTILS ------------------------
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

COUNTRIES = {
    "Italia (IT)":"IT","Suisse/Schweiz (CH)":"CH","France (FR)":"FR","Österreich (AT)":"AT",
    "Deutschland (DE)":"DE","España (ES)":"ES","Norway (NO)":"NO","Sweden (SE)":"SE",
    "Finland (FI)":"FI","USA (US)":"US","Canada (CA)":"CA","Altro (no filtro)":""}

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    # live suggestions (no Enter), optionally biased by country
    if not q or len(q)<2: return []
    country = st.session_state.get("country_iso","")
    params = {"q": q if not country else f"{q}, {country}",
              "format":"json","limit":12,"addressdetails":1}
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params=params, headers={"User-Agent":"telemark-wax-pro/1.1"}, timeout=8)
        r.raise_for_status()
        st.session_state._options = {}
        out=[]
        for item in r.json():
            addr = item.get("address",{}) or {}
            label_short = concise_label(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag(cc)}  {label_short}"
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); js = r.json()
        if js and "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except: pass
    return None

# ------------------------ DATA: Open-Meteo (best) + GFS blend ------------------------
# Nota: manteniamo i requirements invariati (solo requests).
OM_HOURLY = ",".join([
    # meteo base
    "temperature_2m","relative_humidity_2m","dew_point_2m","precipitation","rain","snowfall",
    "cloudcover","windspeed_10m","windgusts_10m","surface_pressure","is_day","weathercode",
    # radiazione & surface
    "shortwave_radiation","direct_radiation","diffuse_radiation",
    "soil_temperature_0cm","soil_moisture_0_to_1cm","snow_depth","freezing_level_height",
    # utili per energetica
    "et0_fao_evapotranspiration"
])

def fetch_open_meteo(lat, lon, timezone_str, models=None, start=None, end=None):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": OM_HOURLY, "forecast_days": 7
    }
    if models: params["models"] = models  # es. "gfs_seamless"
    if start: params["start_hour"] = start
    if end: params["end_hour"] = end
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
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
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"]   = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"]    = df["temperature_2m"].astype(float)
    out["RH"]     = df["relative_humidity_2m"].astype(float)
    out["td"]     = df["dew_point_2m"].astype(float)
    out["cloud"]  = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]   = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["gust"]   = (df["windgusts_10m"].astype(float)/3.6).round(3)
    out["p_sfc"]  = df["surface_pressure"].astype(float)
    out["sunup"]  = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["snow_depth"] = pd.to_numeric(df.get("snow_depth", pd.Series([None]*len(df))), errors="coerce")
    out["sw"] = pd.to_numeric(df.get("shortwave_radiation",0.0)).astype(float)     # W/m2
    out["sw_dir"] = pd.to_numeric(df.get("direct_radiation",0.0)).astype(float)
    out["sw_diff"]= pd.to_numeric(df.get("diffuse_radiation",0.0)).astype(float)
    out["soilT0"] = pd.to_numeric(df.get("soil_temperature_0cm", None), errors="coerce")
    out["soilW"]  = pd.to_numeric(df.get("soil_moisture_0_to_1cm", None), errors="coerce")
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

# ------------------------ PHYSICS: wet-bulb + energy-balance-lite ------------------------
def wet_bulb_approx(T, RH, p_hPa):
    """Stull (2011) approximate wet-bulb in °C (robusta)."""
    # convert needed terms
    rh = RH.clip(1,100)
    Tw = (T*math.atan(0.151977*(rh+8.313659)**0.5)
          + math.atan(T+rh) - math.atan(rh-1.676331)
          + 0.00391838*(rh**1.5)*math.atan(0.023101*rh) - 4.686035)
    return Tw

def compute_snow_temperature(df, dt_hours=1.0):
    """Bilancio energetico semplificato:
       - Se pioggia/melt -> T_surf ~ 0°C
       - Altrimenti evolve verso equilibrio considerando:
         * T aria, Tw (wet-bulb), radiazione shortwave, nuvolosità (longwave), vento (scambio),
         * umidità (evaporative cooling), e condizioni neve precedenti.
    """
    D = df.copy()
    D["time"] = pd.to_datetime(D["time"])
    n = len(D); 
    T_surf = pd.Series(index=D.index, dtype=float)
    T_top5 = pd.Series(index=D.index, dtype=float)

    # parametri fisici semplificati
    # coefficienti tarati empiricamente per soletta neve, esposizione media
    k_conv = 0.8        # scambio convettivo/evaporativo (misto) [°C per (m/s)]
    k_rad  = 0.012      # conversione W/m2 -> deltaT equivalente
    k_lw   = 1.8        # bonus cooling per cielo sereno (longwave out) in °C max
    k_evap = 0.015      # raffrescamento evaporativo ~ RH deficit
    k_cloud_shield = 0.65  # riduce LW loss se coperto

    # prima stima wet-bulb (serve RH, pressione ~ 1013 hPa se assente)
    p = D.get("p_sfc", pd.Series(1013.0, index=D.index)).fillna(1013.0)
    Tw = D.apply(lambda r: wet_bulb_approx(float(r["T2m"]), float(r["RH"]), float(p.loc[r.name])), axis=1)
    Tw = pd.to_numeric(Tw, errors="coerce")

    # determinazione "wet" (melt/rain) robusta
    wet_cond = (
        (D["prp_type"].isin(["rain","mixed"])) |
        ((D["T2m"] > -0.5) & (D["sw"]>200) & (D["cloud"]<0.3)) |
        ((D["T2m"]>-1.0) & (Tw>-0.2))
    )

    # integrazione temporale con tempo caratteristico dinamico
    if n>0:
        # stato iniziale: non fissarlo a 0, ma vicino a min(Tair, 0) con correzione rad
        T_surf.iloc[0] = min(D["T2m"].iloc[0] - 0.6*(1-D["cloud"].iloc[0]), 0.0)
        T_top5.iloc[0] = T_surf.iloc[0] - 0.5

    for i in range(1, n):
        Tair = D["T2m"].iloc[i]; rh = D["RH"].iloc[i]; wind = max(D["wind"].iloc[i], 0.1)
        cloud = D["cloud"].iloc[i]; sw = max(D["sw"].iloc[i], 0.0); sunup = int(D["sunup"].iloc[i])==1
        prev = T_surf.iloc[i-1]

        if wet_cond.iloc[i]:
            # verso 0°C con inerzia che dipende da precipitazione / radiazione
            melt_drive = 0.6 + 0.0008*sw + (0.5 if D["prp_mmph"].iloc[i]>0 else 0)
            T_eq = 0.0
        else:
            # equilibrio “secco”: aria, cooling radiativo, evaporativo e convettivo
            lw_cool = k_lw*(1.0 - cloud)                  # cielo sereno raffredda
            rad_term = k_rad*sw*(1 if sunup else 0)       # SW scalda solo di giorno
            evap = k_evap*(100.0 - rh)                    # deficit umido
            conv = k_conv*wind
            # target intermedio fra Tair e Tw, penalizzato da LW cooling
            T_eq = Tair - lw_cool*(1-k_cloud_shield*cloud) - evap
            # se aria molto asciutta, Tw << Tair: spinge verso Tw
            T_eq = 0.65*T_eq + 0.35*Tw.iloc[i] - 0.4*conv + 0.25*rad_term

            # evita sopra-lo 0 quando non c'è melt
            if T_eq > -0.2 and not sunup:
                T_eq = min(T_eq, -0.2)

            melt_drive = 0.28 + 0.03*wind + 0.0005*sw

        # tempo caratteristico (inerzia): neve dura più lenta, vento/sole accelerano
        tau = 4.0 - 1.2*min(wind,6.0) - (0.8 if sw>300 and sunup else 0.0)
        tau = max(1.2, tau)
        alpha = 1.0 - math.exp(-dt_hours / tau)
        T_surf.iloc[i] = prev + alpha*(T_eq - prev)
        # strato 0-5 mm: smorzato
        T_top5.iloc[i] = T_top5.iloc[i-1] + 0.6*alpha*(T_surf.iloc[i] - T_top5.iloc[i-1])

    D["Tw"] = Tw
    D["T_surf"] = T_surf
    D["T_top5"] = T_top5
    return D

def snow_condition_banner(Ts, prp_type, prp_mm, wind, new_snow_flag):
    # Regole rapide per descrizione + indice affidabilità
    txt = "Neve compatta"
    if prp_type in ("rain","mixed") or Ts>-0.2:
        txt = "Neve bagnata / primaverile"
    elif new_snow_flag:
        txt = "Neve nuova / farinosa"
    elif wind>8:
        txt = "Neve ventata / crosta possibile"
    elif Ts<-8:
        txt = "Neve molto fredda e secca"
    elif Ts<-3:
        txt = "Neve fredda e asciutta"
    reliability = 78
    if prp_type in ("rain","snow","mixed"): reliability += 7
    reliability -= int(max(0, wind-6)*2)
    reliability = int(max(40, min(95, reliability)))
    return txt, reliability

def glide_index(Ts, RH, sw, wind):
    """Indice di scorrevolezza (0-100), qualitativo: >70 molto scorrevole."""
    # caldo/umido e vicino a 0 → più scorrevole, troppo bagnata penalizza
    base = 50 + 18*max(-0.5, min(0.0, Ts)) + 0.12*RH + 0.02*sw - 1.5*max(0, wind-6)
    if Ts > -0.3 and RH>85: base -= 8  # troppo bagnata / suction
    return int(max(5, min(95, base)))

def window_slice(res, tzname, s, e, target_date:date):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==target_date) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ------------------------ WAX BANDS (8 marchi) ------------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRAND_BANDS = [
    ("Swix","#ef4444", SWIX),("Toko","#f59e0b", TOKO),("Vola","#3b82f6", VOLA),("Rode","#22c55e", RODE),
    ("Holmenkol","#06b6d4", HOLM),("Maplus","#f97316", MAPL),("Start","#eab308", START),("Skigo","#a855f7", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='150' height='34'><rect width='150' height='34' rx='6' fill='{color}'/><text x='10' y='22' font-size='14' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ UI: Ricerca (con filtro Paese) ------------------------
with st.sidebar:
    st.markdown("### Località")
    country = st.selectbox("Paese (filtra la ricerca)", list(COUNTRIES.keys()), index=0)
    st.session_state["country_iso"] = COUNTRIES[country]

st.markdown("#### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (es. Champoluc, Plateau Rosa, Cervinia)",
    clear_on_submit=False,
    default=None
)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><div class='lab'>Località</div><div class='val'>{place_label}</div><div class='small'>{alt_txt}</div></div>", unsafe_allow_html=True)

# ------------------------ Finestra temporale & orizzonte ------------------------
st.markdown("#### 2) Finestra oraria e giorno")
c1,c2,c3,c4 = st.columns([1.1,1.1,1.1,2.2])
with c1:
    A_start = st.time_input("Inizio", time(9,0), key="win_s")
with c2:
    A_end   = st.time_input("Fine",   time(12,0), key="win_e")
with c3:
    target_day = st.date_input("Giorno", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))
with c4:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ Scarica dati & calcola (BEST + GFS blend) ------------------------
st.markdown("#### 3) Meteo & calcolo")
go = st.button("Scarica e calcola", type="primary", help="Usa blend dei modelli (best + GFS NOAA) e calcolo fisico migliorato", args=None, kwargs=None)

if go:
    try:
        tzname = "Europe/Rome"  # niente toggle
        # BEST
        js_best = fetch_open_meteo(lat, lon, tzname, models=None)
        src_best = build_df(js_best, hours)
        # NOAA GFS (via Open-Meteo models)
        js_gfs  = fetch_open_meteo(lat, lon, tzname, models="gfs_seamless")
        src_gfs = build_df(js_gfs, hours)

        # Calcolo Ts per entrambi → ensemble semplice (media)
        res_best = compute_snow_temperature(src_best, dt_hours=1.0)
        res_gfs  = compute_snow_temperature(src_gfs,  dt_hours=1.0)
        res = res_best.copy()
        for col in ["T_surf","T_top5","Tw"]:
            res[col] = 0.5*res_best[col].values + 0.5*res_gfs[col].values

        # KPI header
        st.success(f"Dati per **{place_label}** (blend BEST+GFS) caricati.")

        # Tabella “pulita” (selezione colonne chiare)
        show = res[["time","T2m","RH","Tw","T_surf","T_top5","prp_mmph","prp_type","wind","cloud","sw","snow_depth"]].copy()
        show.rename(columns={
            "time":"Ora", "T2m":"T aria (°C)", "RH":"UR (%)", "Tw":"Wet-bulb (°C)",
            "T_surf":"T neve superficie (°C)", "T_top5":"T neve 0-5mm (°C)",
            "prp_mmph":"Prec (mm/h)", "prp_type":"Tipo", "wind":"Vento (m/s)",
            "cloud":"Nuvolosità (0-1)", "sw":"Rad. SW (W/m²)", "snow_depth":"Neve al suolo (cm)"
        }, inplace=True)
        st.dataframe(show, use_container_width=True, hide_index=True)

        # Grafici compatti
        t = pd.to_datetime(res["time"])
        g1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve surf"); plt.plot(t,res["T_top5"],label="T neve 0-5mm"); plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(g1)
        g2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(g2)

        # Slice finestra & “Blocco”
        W = window_slice(res, tzname, A_start, A_end, target_day)
        t_med = float(W["T_surf"].mean())
        rh_med = float(W["RH"].mean()); sw_med = float(W["sw"].mean()); wind_med = float(W["wind"].mean())
        prp_dom = W["prp_type"].value_counts().index[0] if not W.empty else "none"
        new_snow = (res["snow_depth"].diff().fillna(0)>0.5).rolling(6).max().fillna(0).iloc[:len(res)].any()

        desc, reliab = snow_condition_banner(t_med, prp_dom, float(W["prp_mmph"].sum()), wind_med, new_snow)
        glide = glide_index(t_med, rh_med, sw_med, wind_med)

        st.markdown(f"### Blocco selezionato — {target_day.isoformat()}  ({A_start.strftime('%H:%M')}–{A_end.strftime('%H:%M')})")
        st.markdown(
            f"<div class='card'><div class='kpi'><div class='lab'>T neve surf media</div><div class='val'>{t_med:.1f}°C</div>"
            f"<div class='lab'>UR</div><div class='val'>{rh_med:.0f}%</div>"
            f"<div class='lab'>Vento</div><div class='val'>{wind_med:.1f} m/s</div>"
            f"<div class='lab'>Rad SW</div><div class='val'>{sw_med:.0f} W/m²</div></div></div>", unsafe_allow_html=True
        )

        # Banner condizioni + Indice di scorrevolezza (no toggle)
        color_class = "alert-ok" if glide>=70 else ("alert-warn" if glide>=50 else "alert-bad")
        st.markdown(f"<div class='{color_class}'>Condizione neve: <b>{desc}</b> · Affidabilità stimata: <b>{reliab}%</b> · Indice di scorrevolezza: <b>{glide}/100</b></div>", unsafe_allow_html=True)

        # Wax recommendation: 8 marchi (cards colorate)
        st.markdown("#### Sciolina consigliata (8 marchi)")
        cols1 = st.columns(4); cols2 = st.columns(4)
        for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
            rec = pick(bands, t_med); svg = logo_badge(brand.upper(), col)
            cols1[i].markdown(f"<div class='brand'><img src='{svg}'/><div><div class='small'>{brand}</div><div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True)
        for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
            rec = pick(bands, t_med); svg = logo_badge(brand.upper(), col)
            cols2[i].markdown(f"<div class='brand'><img src='{svg}'/><div><div class='small'>{brand}</div><div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True)

        # Struttura & angoli (nomi, niente immagini)
        st.markdown("#### Struttura & angoli (nominale, per disciplina)")
        def tune_for(t_surf, discipline):
            if t_surf <= -10:
                fam = "Lineare fine (freddo/secco)"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}.get(discipline,88.0)
            elif t_surf <= -3:
                fam = "Incrociata leggera / onda (universale)"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}.get(discipline,88.0)
            else:
                fam = "Scarico diagonale / V (umido/caldo)"; base = 0.8 if t_surf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}.get(discipline,88.0)
            return fam, side, base
        rows=[]
        for d in ["SL","GS","SG","DH"]:
            fam, side, base = tune_for(t_med, d)
            rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
        st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

        # Download CSV
        st.download_button("Scarica CSV risultati (blend + calcolo)", data=res.to_csv(index=False), file_name="telemark_blend_snowcalc.csv", mime="text/csv")
    except Exception as e:
        st.error(f"Errore: {e}")
