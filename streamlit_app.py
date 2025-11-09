# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark theme + search by country
# Meteo → neve: quick wins (RH, wet-bulb, vento eff., radiazione, albedo) + T_surf/T_top5 + scorrevolezza + granulometria

import os, math, base64, requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from datetime import date, time, datetime, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ========= THEME =========
PRIMARY = "#06b6d4"; ACCENT = "#f97316"; OK="#10b981"; WARN="#f59e0b"; ERR="#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
hr {{ border:none;border-top:1px solid var(--line);margin:.75rem 0 }}
.badge {{ display:inline-flex;gap:.5rem;align-items:center;background:#0b1220;border:1px solid #203045;
         color:#cce7f2;border-radius:12px;padding:.35rem .6rem;font-size:.85rem }}
.card  {{ background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:.9rem .95rem }}
.tbl table {{ border-collapse:collapse;width:100% }}
.tbl th,.tbl td {{ border-bottom:1px solid var(--line);padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1;font-weight:700;text-transform:uppercase;font-size:.78rem;letter-spacing:.06em }}
.banner {{ border-left:6px solid {ACCENT};background:#1a2230;color:#e2e8f0;padding:.75rem .9rem;border-radius:10px;font-size:.98rem }}
.brand {{ display:flex;gap:.6rem;align-items:center;background:#0e141d;border:1px solid #1e2a3a;border-radius:10px;padding:.45rem .6rem }}
.btn-primary button {{ background:{ACCENT} !important;color:#111 !important;font-weight:800 !important }}
.slider-tip {{ color:var(--muted);font-size:.85rem }}
a,.stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza, granulometria e scioline — blocchi A/B/C.")

# ========= HELPERS =========
def flag(cc:str)->str:
    try: c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s

# ========= SEARCH (with country prefilter) =========
COUNTRIES = {"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro)", list(COUNTRIES.keys()), index=0)
    ISO2 = COUNTRIES[sel_country]
with colSB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search",
                params={"q":q,"format":"json","limit":12,"addressdetails":1,"countrycodes":ISO2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.1"}, timeout=8)
            r.raise_for_status()
            opts={}; out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab = f"{flag(addr.get('country_code',''))}  {concise_label(addr,it.get('display_name',''))}"
                lat=float(it["lat"]); lon=float(it["lon"])
                key=f"{lab}|||{lat:.6f},{lon:.6f}"
                opts[key]={"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            st.session_state._options = opts
            return out
        except: return []

    selected = st_searchbox(nominatim_search, key="place",
                            placeholder="Cerca… es. Champoluc, Plateau Rosa",
                            clear_on_submit=False, default=None)

def get_elev(lat,lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); js=r.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat",45.831); lon = st.session_state.get("lon",7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat,lon,place_label = info["lat"],info["lon"],info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev else '—'} m</b></div>", unsafe_allow_html=True)

# ========= DAY & WINDOWS =========
cdate, chz = st.columns([1,1])
with cdate:
    target_day = st.date_input("Giorno di riferimento", value=date.today())
with chz:
    tzname = "Europe/Rome"; st.text_input("Fuso orario", tzname, disabled=True)

st.subheader("1) Finestre orarie A · B · C")
def tt(h,m): return time(h,m)
c1,c2,c3 = st.columns(3)
with c1:
    A_start=st.time_input("Inizio A",tt(9,0));   A_end=st.time_input("Fine A",tt(11,0))
with c2:
    B_start=st.time_input("Inizio B",tt(11,0));  B_end=st.time_input("Fine B",tt(13,0))
with c3:
    C_start=st.time_input("Inizio C",tt(13,0));  C_end=st.time_input("Fine C",tt(16,0))

st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)
st.markdown("<div class='slider-tip'>Suggerimento: < 48h → stime più affidabili</div>", unsafe_allow_html=True)

# ========= Open-Meteo =========
def fetch_open_meteo(lat, lon, tzname):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=dict(
        latitude=lat, longitude=lon, timezone=tzname,
        hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
        forecast_days=7), timeout=30)
    r.raise_for_status(); return r.json()

def _rh_from_T_Td(T, Td):
    # Magnus formula (°C) → RH %
    T = T.astype(float); Td = Td.astype(float)
    a,b = 17.625, 243.04
    es  = np.exp(a*T /(b+T));  e  = np.exp(a*Td/(b+Td))
    RH  = np.clip(100.0*e/es, 1.0, 100.0)
    return RH

def _stull_wetbulb(T, RH):
    # Stull (2011) approx, inputs in °C and % → Tw °C
    T  = T.astype(float); RH = np.clip(RH.astype(float), 1.0, 100.0)
    # use numpy arctan
    Tw = (T*np.arctan(0.151977*np.sqrt(RH+8.313659)) +
          np.arctan(T+RH) - np.arctan(RH-1.676331) +
          0.00391838*np.power(RH,1.5)*np.arctan(0.023101*RH) - 4.686035)
    return Tw

def _solar_clear(lat, lon, elev_m, ts):
    """
    Quick clear-sky GHI (W/m2) using simple geometry:
    cosθ = sinφ sinδ + cosφ cosδ cosh ; SW_clear ≈ 990 * max(0, cosθ)
    where δ ≈ 23.44° * sin(2π*(284+N)/365)
    """
    phi = np.radians(lat)
    DOY = ts.dt.dayofyear.values
    H   = ts.dt.hour.values + ts.dt.minute.values/60.0
    delta = np.radians(23.44*np.sin(2*np.pi*(284+DOY)/365.0))
    h_ang = np.radians((H-12.0)*15.0)
    cosz = np.sin(phi)*np.sin(delta) + np.cos(phi)*np.cos(delta)*np.cos(h_ang)
    cosz = np.clip(cosz, 0, 1)
    SW_clear = 990.0 * cosz
    return pd.Series(SW_clear, index=ts.index)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])  # naive UTC-like in provided tz
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)

    out = pd.DataFrame(index=df.index)
    out["time"]  = df["time"]
    out["T2m"]   = df["temperature_2m"].astype(float)
    out["Td"]    = (df["dew_point_2m"] if "dew_point_2m" in df else out["T2m"]).astype(float)

    if "relative_humidity_2m" in df:
        out["RH"] = df["relative_humidity_2m"].astype(float)
    else:
        out["RH"] = _rh_from_T_Td(out["T2m"], out["Td"])

    out["Tw"]    = _stull_wetbulb(out["T2m"], out["RH"])
    out["cloud"] = (df["cloudcover"].astype(float)/100.0).clip(0,1)
    wind_ms      = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)   # m/s
    out["wind"]  = wind_ms
    # vento effettivo (0–8 m/s log1p)
    out["wind_eff"] = (np.log1p(np.clip(wind_ms,0,8)) / np.log1p(8)) * 8.0

    out["sunup"]    = df["is_day"].astype(int)
    out["prp"]      = df["precipitation"].astype(float)
    out["rain"]     = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"]    = df.get("weathercode",0).astype(int)

    # radiazione stimata: clear-sky * (1 - 0.75*cloud^3)
    SW_clear = _solar_clear(lat, lon, elev if elev else 0.0, out["time"])
    out["SW_down"] = (SW_clear * (1.0 - 0.75*np.power(out["cloud"],3))).clip(lower=0)

    return out

# precip type
def prp_type_row(row):
    if row.prp<=0 or pd.isna(row.prp): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes={71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# ========== Snow energy/temperature + quick wins integration ==========
def _albedo_from_age(age_h, Tsurf_guess):
    # 0–12h ~0.85 → 7d ~0.60; se T>0 e giorno → 0.55
    alb = 0.85 - 0.25*np.clip(age_h, 0, 168)/168.0
    if Tsurf_guess > 0.0: alb = np.minimum(alb, 0.55)
    return np.clip(alb, 0.45, 0.90)

def add_snow_age(df):
    # età da ultima nevicata (>= 0.5 mm/h neve)
    snow_event = (df["snowfall"] >= 0.5)
    age = np.zeros(len(df), dtype=float); last_idx = None
    for i,ev in enumerate(snow_event.values):
        if ev: last_idx = i; age[i]=0.0
        else:
            age[i] = (i-last_idx) if last_idx is not None else np.inf
    df["snow_age_h"] = age  # in ore
    return df

def estimate_grain(df):
    # granulometria (mm) e classe: funzione di età, Tsurf stimata grezza e cicli MF
    # useremo Tsurf provvisorio (dopo lo step principale lo ricalcoliamo coerente)
    T = df["T2m"]; sun = (df["sunup"]==1)
    # proxy melt-freeze: ore con T> -0.5°C e SW_down>250 W/m2
    mf = ((T>-0.5) & (df["SW_down"]>250)).rolling(6, min_periods=1).sum().clip(0,6)/6.0
    # granulo in mm
    grain_mm = np.clip(0.2 + 0.0015*df["snow_age_h"] + 0.6*mf, 0.2, 3.0)
    cls = np.where(df["snow_age_h"]<24, "Fresca fine (0.2–0.5)",
          np.where(mf>0.5, "Primaverile/granulosa (1–2)",
          np.where((T<-5)&(df["cloud"]<0.3)&(~sun), "Rigelata fine (0.3–0.6)", "Trasformata (0.5–1.0)")))
    df["grain_mm"]=np.round(grain_mm,2); df["grain_class"]=cls
    return df

def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    X = df.copy()
    X["ptype"] = X.apply(prp_type_row, axis=1)

    # condizioni bagnate
    sunup = (X["sunup"]==1)
    near0 = X["T2m"].between(-1.2, 1.2)
    wet = ((X["ptype"].isin(["rain","mixed"])) |
           ((X["ptype"]=="snow") & X["T2m"].ge(-1.0)) |
           (sunup & (X["cloud"]<0.35) & X["T2m"].ge(-2.0)) |
           (X["T2m"]>0.0))

    # T_surf primi set
    T_surf = pd.Series(np.nan, index=X.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - X["cloud"]).clip(0,1)
    # cooling radiativo/notturno + convettivo (usa vento effettivo)
    drad = (1.4 + 3.1*clear - 0.35*X["wind_eff"]).clip(0.4, 5.0)  # °C da sottrarre
    T_surf.loc[dry] = X["T2m"][dry] - drad[dry]

    # giorno freddo e soleggiato → non scendere troppo sotto aria
    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = np.minimum(
        (X["T2m"] + 0.4*(1.0 - X["cloud"]))[sunny_cold],
        -0.8
    )

    # età neve + albedo dinamico → micro-forcing (spinge verso 0 con sole e albedo basso)
    X = add_snow_age(X)
    alb = _albedo_from_age(X["snow_age_h"], T_surf.fillna(0.0))
    solar_gain = (X["SW_down"]*(1.0-alb))/900.0   # scala 0..~1
    T_surf = np.where(sunup, T_surf + (solar_gain.clip(0,1)*0.8), T_surf)

    # top ~5mm: rilassamento a T_surf con tau dinamico
    T_top5 = pd.Series(np.nan, index=X.index, dtype=float)
    tau = pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptype"]!="none") | (X["wind_eff"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind_eff"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(X)>0:
        T_top5.iloc[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf[i] - T_top5.iloc[i-1])

    X["T_surf"] = np.round(T_surf,2)
    X["T_top5"] = np.round(T_top5,2)

    # granulometria (usa stima definita sopra; dipende anche da SW/età)
    X = estimate_grain(X)

    # indice scorrevolezza 0..100
    # base: optimum vicino a -0.5..-2 con moderata umidità
    base = 100 - np.clip(np.abs(X["T_surf"] + 2.0)*9.0, 0, 100)
    wet_pen   = ((X["ptype"].isin(["rain","mixed"])) | near0).astype(int)*22
    sticky    = ((X["RH"]>92) & (X["T_surf"]>-1.0)).astype(int)*10
    coarse_boost = np.clip((X["grain_mm"]-0.8)*10, -5, 8)  # granulo medio aiuta scorrere (se non bagnato)
    speed = np.clip(base - wet_pen - sticky + coarse_boost, 0, 100)
    X["speed_index"] = speed.round(0)

    return X

def classify_snow(row):
    if row.ptype=="rain": return "Neve bagnata/pioggia"
    if row.ptype=="mixed": return "Mista pioggia-neve"
    if row.ptype=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptype=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.sunup==0 and row.cloud<0.4: return "Rigelata/ghiacciata"
    if row.sunup==1 and row.T_surf>-2 and row.cloud<0.3: return "Primaverile/trasformata"
    return "Compatta"

def reliability_from_time(t0):
    if t0 is None: return 50
    hrs = max(1,(t0 - pd.Timestamp.now()).total_seconds()/3600.0)
    return 85 if hrs<=24 else 75 if hrs<=48 else 65 if hrs<=72 else 50 if hrs<=120 else 40

# ========= Wax brands & structures (names only) =========
SWIX=[("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO=[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA=[("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE=[("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM=[("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL=[("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START=[("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO=[("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS=[("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]
def pick(bands,t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Ts):
    if Ts<=-10: return "Linear Fine (freddo/secco)"
    if Ts<=-3:  return "Cross Hatch leggera (universale freddo)"
    if Ts<=0.5: return "Diagonal/Scarico V (umido)"
    return "Wave/Scarico marcato (bagnato caldo)"

def tune_for(Ts, discipline):
    if Ts <= -10:
        fam="Linear Fine"; base=0.5; side={"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[discipline]
    elif Ts <= -3:
        fam="Cross Hatch leggera"; base=0.7; side={"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[discipline]
    else:
        fam="Diagonal/Scarico V"; base=(0.8 if Ts<=0.5 else 1.0); side={"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[discipline]
    return fam, side, base

# ========= UI: Calculate =========
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js  = fetch_open_meteo(lat,lon,tzname)
        raw = build_df(js, hours)
        res = snow_temperature_model(raw)

        # Main table
        show = pd.DataFrame({
            "Ora":    res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["Td"].round(1),
            "UR (%)":      res["RH"].round(0),
            "Tw (°C)":     res["Tw"].round(1),
            "Vento eff (m/s)": res["wind_eff"].round(1),
            "Nuvolosità (%)":  (res["cloud"]*100).round(0),
            "Rad. SW (W/m²)":  res["SW_down"].round(0),
            "Prp (mm/h)":      res["prp"].round(2),
            "Tipo prp":        res["ptype"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "Grana (mm)":       res["grain_mm"].round(2),
            "Classe grana":     res["grain_class"],
            "Scorrevolezza":    res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Charts
        t = res["time"]
        fig1 = plt.figure(figsize=(10,3)); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve"); plt.plot(t,res["T_top5"],label="T top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)

        fig2 = plt.figure(figsize=(10,2.8)); plt.bar(t,res["prp"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # Blocks
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        tzobj = tz.gettz(tzname)
        # filtro per giorno scelto
        mask_day = res["time"].dt.tz_localize(tzobj, nonexistent='shift_forward', ambiguous='NaT').dt.date == target_day
        day_df = res[mask_day].copy()
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")
            if day_df.empty:
                W = res.head(6).copy()
            else:
                cut = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                W = cut if not cut.empty else day_df.head(6)

            if W.empty:
                st.info("Nessun dato nella finestra scelta."); continue

            t_med = float(W["T_surf"].mean())
            state = classify_snow(W.iloc[0])
            rel = reliability_from_time(W["time"].iloc[0].to_pydatetime())
            grain = f'{W["grain_class"].mode().iat[0]} (~{W["grain_mm"].mean():.1f} mm)'

            st.markdown(f"<div class='banner'><b>Condizioni previste:</b> {state} · "
                        f"<b>T_neve med</b> {t_med:.1f}°C · <b>Grana stimata</b> {grain} · "
                        f"<b>Affidabilità</b> ≈ {rel}%</div>", unsafe_allow_html=True)

            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            # Scioline + mini tabella
            col1,col2 = st.columns(2)
            with col1:
                st.markdown("**Scioline (per T neve media):**")
                cols1 = st.columns(4); cols2 = st.columns(4)
                for i,(name,bands) in enumerate(BRANDS[:4]):
                    cols1[i].markdown(f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{pick(bands,t_med)}</div></div></div>", unsafe_allow_html=True)
                for i,(name,bands) in enumerate(BRANDS[4:]):
                    cols2[i].markdown(f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{pick(bands,t_med)}</div></div></div>", unsafe_allow_html=True)
            with col2:
                mini = pd.DataFrame({
                    "Ora": W["time"].dt.strftime("%H:%M"),
                    "T aria": W["T2m"].round(1),
                    "T neve": W["T_surf"].round(1),
                    "UR%":   W["RH"].round(0),
                    "V m/s": W["wind_eff"].round(1),
                    "Prp":   W["ptype"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"}),
                    "Scorr.": W["speed_index"].astype(int)
                })
                st.dataframe(mini, use_container_width=True, hide_index=True)

            # Tabellina discipline/angoli
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE","Lamina BASE"]))

        # Download CSV
        csv = res.copy(); csv["time"] = csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="telemark_snow_forecast.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
