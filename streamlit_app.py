# telemark_pro_app.py
import math, base64, os
from datetime import date, datetime, time, timedelta, timezone
import numpy as np
import pandas as pd
import requests
import streamlit as st
from dateutil import tz
from streamlit_searchbox import st_searchbox
import matplotlib.pyplot as plt

# -------------------- THEME / STYLE (dark, “pulsante”) --------------------
PRIMARY = "#10bfcf"   # Telemark turchese
ACCENT  = "#e11d48"   # rosso acceso per highlight
TEXT    = "#e5e7eb"
MUTED   = "#9ca3af"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --primary:{PRIMARY}; --accent:{ACCENT}; --text:{TEXT}; --muted:{MUTED}; }}
[data-testid="stAppViewContainer"] > .main {{ background: #0b1220; }}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4, label, p, span, div {{ color: var(--text); }}
.smallmuted {{ color: var(--muted); font-size:.82rem }}
.kpi {{ display:flex; gap:.6rem; align-items:center; background:#0f172a; border:1px solid #1f2937;
       padding:.6rem .8rem; border-radius:12px; }}
.card {{ background:#0f1626; border:1px solid #1f2937; border-radius:16px; padding:14px; }}
.btn-primary button {{ background:var(--accent) !important; border:0 !important; }}
.badge {{ background:rgba(16,191,207,.15); color:#cffafe; border:1px solid rgba(16,191,207,.35);
         padding:.2rem .5rem; border-radius:999px; font-size:.78rem; }}
hr {{ border:none; border-top:1px solid #1f2937; margin:.8rem 0 }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")

# -------------------- UTILS --------------------
ISO2_CHOICES = {
    "Italia (IT)": "it", "Svizzera (CH)": "ch", "Francia (FR)": "fr", "Austria (AT)": "at",
    "Germania (DE)": "de", "Svezia (SE)": "se", "Norvegia (NO)": "no",
    "Spagna (ES)": "es", "Stati Uniti (US)": "us", "Tutti i Paesi": ""
}

def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    area = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc   = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, area] if p]
    short = ", ".join(parts)
    if cc: short += f" — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2:
        return []
    try:
        ccodes = st.session_state.get("ccodes","")
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        if ccodes: params["countrycodes"] = ccodes
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params,
                         headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
        r.raise_for_status()
        st.session_state._opts = {}
        out=[]
        for item in r.json():
            addr = item.get("address",{}) or {}
            label = f"{flag(addr.get('country_code',''))}  {concise_label(addr, item.get('display_name',''))}"
            lat = float(item.get("lat",0)); lon=float(item.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._opts[key] = {"lat":lat,"lon":lon,"addr":addr,"label":label}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float)->float|None:
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except: pass
    return None

def fetch_open_meteo(lat, lon, tzname="Europe/Rome", start=None, hours=72):
    # start: naive datetime (local tz), hours horizon
    params = {
        "latitude":lat, "longitude":lon, "timezone":tzname,
        "hourly":"temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,"
                 "windspeed_10m,is_day,weathercode,snow_depth,surface_pressure",
        "forecast_days": 7
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    h = js["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])  # tz-aware per API timezone in label, ma trattiamo come naive poi localizziamo
    # Slice per giorno scelto + orizzonte:
    if start is not None:
        t0 = pd.Timestamp(start).tz_localize(tz.gettz(tzname))
    else:
        t0 = pd.Timestamp.now(tz=tz.gettz(tzname))
    t1 = t0 + pd.Timedelta(hours=hours)
    # Convert to same tz for comparison:
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    df = df[(df["time"]>=t0) & (df["time"]<t1)].reset_index(drop=True)
    return df

# ---- Physics helpers ----
def wet_bulb_stull(Tc:pd.Series, RH:pd.Series, P_hpa:pd.Series|float=1013.0)->pd.Series:
    """
    Stull (2011) approximation for wet-bulb (°C). RH in %.
    """
    # Ensure Series
    Tc = pd.Series(Tc, dtype=float)
    RH = pd.Series(RH, dtype=float).clip(lower=1.0, upper=100.0)
    Tw = Tc*np.arctan(0.151977*np.sqrt(RH+8.313659)) + np.arctan(Tc+RH) - np.arctan(RH-1.676331) \
         + 0.00391838*(RH**1.5)*np.arctan(0.023101*RH) - 4.686035
    return pd.Series(Tw, index=Tc.index)

def classify_precip(row)->str:
    # robust classification
    prp = float(row.get("precipitation",0) or 0)
    r   = float(row.get("rain",0) or 0)
    s   = float(row.get("snowfall",0) or 0)
    if prp<=0.01: return "none"
    if r>0 and s>0: return "mixed"
    if s>0 and r==0: return "snow"
    if r>0 and s==0: return "rain"
    # fallback by weathercode
    code=int(row.get("weathercode",0) or 0)
    if code in {71,73,75,77,85,86}: return "snow"
    if code in {51,53,55,61,63,65,80,81,82}: return "rain"
    return "mixed"

def compute_snow_thermo(df:pd.DataFrame)->pd.DataFrame:
    D = df.copy()
    # Ensure numeric series
    for c in ["temperature_2m","relative_humidity_2m","dew_point_2m","cloudcover","windspeed_10m",
              "is_day","precipitation","rain","snowfall","surface_pressure"]:
        if c in D:
            D[c] = pd.to_numeric(D[c], errors="coerce")

    D["prp_type"] = D.apply(classify_precip, axis=1)

    # Wet-bulb (°C)
    pres = D.get("surface_pressure", pd.Series(1013.0, index=D.index))
    D["Tw"] = wet_bulb_stull(D["temperature_2m"], D["relative_humidity_2m"], pres)

    # Radiative/ventilative cooling (hemi-empirical; produces variability reale)
    cloud = (D["cloudcover"]/100.0).clip(0,1)
    clear = (1.0 - cloud)
    wind  = (D["windspeed_10m"]/3.6).fillna(0)  # m/s
    sunup = D["is_day"].fillna(0).astype(int) == 1
    T2    = D["temperature_2m"]

    # Base surface target temp without precip
    # Night clear → forte raffreddamento, giorno nuvoloso → vicino a T2
    k_radiative = (0.6 + 2.8*clear - 0.25*np.clip(wind,0,6))  # °C “delta” da T2 (>=0.2)
    k_radiative = np.clip(k_radiative, 0.2, 4.5)
    T_surf_est  = T2 - k_radiative
    # Se sole e freddo moderato, limite a -0.5 per brina leggera
    T_surf_est = np.where(sunup & (T2.between(-10,0)), np.minimum(T2 + 0.5*(1-cloud), -0.5), T_surf_est)

    # Condizioni “bagnate”: pioggia/misto, T2>0, Tw vicino a 0, neve bagnata → T_surf -> 0
    wet = (D["prp_type"].isin(["rain","mixed"])) | (T2>0.0) | ((D["prp_type"]=="snow") & (T2>-1)) | (D["Tw"]>-0.2)
    T_surf = pd.Series(T_surf_est, index=D.index)
    T_surf.loc[wet] = 0.0

    # Relaxazione (top 5 mm) con costante di tempo variabile
    tau = pd.Series(6.0, index=D.index)  # ore
    tau.loc[D["prp_type"].isin(["rain","snow","mixed"]) | (wind>=6)] = 3.0
    tau.loc[(~sunup) & (wind<2) & (cloud<0.3)] = 8.0

    alpha = 1.0 - np.exp(-1.0 / tau)  # passo orario
    T_top5 = pd.Series(index=D.index, dtype=float)
    if len(D)>0:
        T_top5.iloc[0] = min(float(T2.iloc[0]), 0.0)
        for i in range(1,len(D)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i] - T_top5.iloc[i-1])

    D["T_surf"] = T_surf.astype(float)
    D["T_top5"] = T_top5.astype(float)

    # Stato neve
    recent_snow_6h = D["snowfall"].rolling(6, min_periods=1).sum().fillna(0)
    state = []
    for i,row in D.iterrows():
        ts = row["T_surf"]; t2=row["temperature_2m"]; rh=row["relative_humidity_2m"]
        pt=row["prp_type"]; new6 = recent_snow_6h.loc[i]
        if pt=="snow" or new6>=2.0:
            state.append("Neve nuova")
        elif pt in ("rain","mixed") or (ts>-0.2 and rh>=85):
            state.append("Bagnata")
        elif ts<=-5 and new6<0.5 and rh<80:
            state.append("Secca/compatta")
        elif ts<-0.2 and new6<0.5:
            state.append("Dura/Ghiacciata")
        else:
            state.append("Granulosa/primaverile")
    D["snow_state"] = state

    # Indice di scorrevolezza (0-100) – migliore intorno a T_surf -8…-2 con secco/vento moderato
    base_score = 100 - np.clip(np.abs(D["T_surf"] - (-5.0))*9.0, 0, 80)   # campana su -5 °C
    pen_prp = np.where(D["prp_type"].eq("rain"), 25, np.where(D["prp_type"].eq("mixed"), 15, 0))
    pen_snow = np.clip(recent_snow_6h*2.5, 0, 18)
    pen_wind = np.clip((D["windspeed_10m"]/3.6 - 8.0)*4.0, 0, 20)
    glide = np.clip(base_score - pen_prp - pen_snow - pen_wind, 5, 98)
    D["glide_index"] = glide.round(0).astype(int)

    # Affidabilità (0-100): più alta per orizzonti brevi, meno variabilità, poca prp
    hours_ahead = (D["time"] - D["time"].iloc[0]).dt.total_seconds()/3600.0
    varT = D["temperature_2m"].rolling(6, min_periods=1).std().fillna(0)
    reliab = 100 - np.clip(hours_ahead*0.8 + varT*4 + (D["precipitation"]*3), 0, 65)
    D["reliability"] = reliab.round(0).astype(int)

    return D

def window_slice_local(D:pd.DataFrame, tzname:str, target_day:date, s:time, e:time)->pd.DataFrame:
    # crea intervallo locale per il giorno scelto
    tzinfo = tz.gettz(tzname)
    start = datetime.combine(target_day, s).replace(tzinfo=tzinfo)
    end   = datetime.combine(target_day, e).replace(tzinfo=tzinfo)
    W = D[(D["time"]>=start) & (D["time"]<=end)]
    return W if not W.empty else D.head(6)

# -------------------- WAX bands & brands --------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [
    ("Swix", SWIX), ("Toko", TOKO), ("Vola", VOLA), ("Rode", RODE),
    ("Holmenkol", HOLM), ("Maplus", MAPL), ("Start", START), ("Skigo", SKIGO),
]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_for(Tsurf:float, discipline:str):
    # solo nomi struttura (niente immagini)
    if Tsurf <= -10:
        structure = "Lineare fine (freddo/secco)"
        base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}.get(discipline,88.0)
    elif Tsurf <= -3:
        structure = "Incrociata fine (universale freddo)"
        base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}.get(discipline,88.0)
    else:
        structure = "Diagonale/Scarico (umido/caldo)"
        base = 0.8 if Tsurf<=0.5 else 1.0
        side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}.get(discipline,88.0)
    return structure, side, base

# ==================== 1) RICERCA LOCALITÀ ====================
st.subheader("1) Seleziona area & località")

colA, colB = st.columns([1,2])
with colA:
    country_pick = st.selectbox("Nazione", list(ISO2_CHOICES.keys()), index=0)
    st.session_state["ccodes"] = ISO2_CHOICES[country_pick]

with colB:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e premi INVIO… (es. Champoluc, Plateau Rosa, Cervinia)",
        clear_on_submit=False,
        default=None
    )

# Persist selection
lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
label = st.session_state.get("label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    if info:
        lat, lon, label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["label"]=label

# Altitude
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'>📍 <b>{label}</b>{alt_txt}</div>", unsafe_allow_html=True)

# ==================== 2) Finestre + Giorno ====================
st.subheader("2) Finestre orarie (giorno selezionato)")

colG, col1, col2, col3 = st.columns([1.2,1,1,1])
with colG:
    target_day = st.date_input("Giorno di riferimento", value=date.today())
with col1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with col2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with col3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione (da ora del giorno scelto)", 12, 168, 72, 12)

# ==================== 3) Meteo & calcolo ====================
st.subheader("3) Meteo & Analisi neve")
go = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if go:
    try:
        tzname = "Europe/Rome"  # coerente con Italia/Alpi; possiamo dedurre da OSM in futuro
        start_dt = datetime.combine(target_day, time(0,0))
        raw = fetch_open_meteo(lat, lon, tzname, start=start_dt, hours=hours)
        if raw.empty:
            st.warning("Nessun dato nelle ore richieste.")
        else:
            D = compute_snow_thermo(raw)
            # Rinomina colonne per tabella pulita
            show = pd.DataFrame({
                "Ora (locale)": D["time"].dt.strftime("%d/%m %H:%M"),
                "T aria (°C)": D["temperature_2m"].round(1),
                "UR (%)": D["relative_humidity_2m"].round(0),
                "T_surf (°C)": D["T_surf"].round(1),
                "T_top5 (°C)": D["T_top5"].round(1),
                "Prp (mm/h)": D["precipitation"].round(1),
                "Tipo prp": D["prp_type"],
                "Vento (m/s)": (D["windspeed_10m"]/3.6).round(1),
                "Nuvolosità (%)": D["cloudcover"].round(0),
                "Stato neve": D["snow_state"],
                "Indice di scorrevolezza": D["glide_index"],
                "Affidabilità": D["reliability"]
            })
            st.dataframe(show, use_container_width=True, hide_index=True)

            # Grafici veloci
            t = D["time"]
            fig1 = plt.figure(); plt.plot(t, D["temperature_2m"], label="T aria")
            plt.plot(t, D["T_surf"], label="T_surf"); plt.plot(t, D["T_top5"], label="T_top5")
            plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
            st.pyplot(fig1)

            fig2 = plt.figure(); plt.bar(t, D["precipitation"]); plt.title("Precipitazione (mm/h)")
            plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

            # Blocchi A/B/C
            st.markdown("#### Raccomandazioni per blocchi")
            blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
            for L,(s,e) in blocks.items():
                W = window_slice_local(D, tzname, target_day, s, e)
                t_med = float(W["T_surf"].mean())
                state_mode = W["snow_state"].mode().iloc[0] if not W["snow_state"].mode().empty else "—"
                glide_med  = int(W["glide_index"].mean())
                rel_med    = int(W["reliability"].mean())

                st.markdown(f"**Blocco {L}**  ·  T_surf media **{t_med:.1f}°C**  ·  Stato: **{state_mode}**  ·  "
                            f"Indice di scorrevolezza **{glide_med}/100**  ·  Affidabilità **{rel_med}/100**")

                # Scioline
                cols = st.columns(4)
                for i,(brand,bands) in enumerate(BRANDS[:4]):
                    rec = pick_wax(bands, t_med)
                    cols[i].markdown(
                        f"<div class='card'><div class='smallmuted'>{brand}</div>"
                        f"<div style='font-weight:800'>{rec}</div></div>", unsafe_allow_html=True
                    )
                cols = st.columns(4)
                for i,(brand,bands) in enumerate(BRANDS[4:]):
                    rec = pick_wax(bands, t_med)
                    cols[i].markdown(
                        f"<div class='card'><div class='smallmuted'>{brand}</div>"
                        f"<div style='font-weight:800'>{rec}</div></div>", unsafe_allow_html=True
                    )

                # Strutture + angoli per le 4 discipline
                rows=[]
                for d in ["SL","GS","SG","DH"]:
                    sname, side, base = tune_for(t_med, d)
                    rows.append([d, sname, f"{side:.1f}°", f"{base:.1f}°"])
                st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

            # Download CSV
            st.download_button("Scarica CSV completo", data=D.to_csv(index=False).encode("utf-8"),
                               file_name="telemark_forecast_processed.csv", mime="text/csv",
                               use_container_width=True)

    except Exception as e:
        st.error(f"Errore: {e}")
