# telemark_pro_app.py
import math, base64, os
from datetime import time, date, timedelta, datetime

import pandas as pd
import requests
import streamlit as st
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- THEME / STYLE (dark + accent) --------------------
PRIMARY = "#10bfcf"      # Telemark turquoise
ACCENT  = "#f97316"      # warm accent (buttons/markers)
TEXT    = "#e5e7eb"      # light text
MUTED   = "#9ca3af"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --primary: {PRIMARY};
  --accent: {ACCENT};
  --text: {TEXT};
  --muted: {MUTED};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 0% -10%, #0b1220 0%, #0f172a 40%, #0b1220 100%);
}}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5,h6, label, p, span, div {{ color: var(--text); }}
.small-muted {{ color: var(--muted); font-size:.85rem }}
.kpi {{ display:flex; align-items:center; gap:.5rem; background:rgba(16,191,207,.06);
       border:1px dashed rgba(16,191,207,.45); padding:.5rem .75rem; border-radius:12px; }}
.card {{ background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
        border-radius:16px; padding:14px; box-shadow:0 10px 22px rgba(0,0,0,.25); }}
.brand {{ display:flex;align-items:center;gap:.75rem;background:rgba(255,255,255,.03);
          border:1px solid rgba(255,255,255,.08); border-radius:12px;padding:.5rem .75rem; }}
.badge {{ display:inline-flex;gap:.4rem;align-items:center;background:#0b1220;border:1px solid #223045;
          padding:.25rem .6rem;border-radius:999px;font-size:.78rem; color:var(--muted)}}
hr {{ border:none;border-top:1px solid #1f2937;margin:.75rem 0 }}
/* Buttons */
.stButton>button {{ background: var(--accent); color:white; border:none; font-weight:700; }}
.stSlider [role=slider]::before {{ background: var(--accent)!important; }}
/* Tables */
thead th {{ background:#0b1220!important; }}
</style>
""", unsafe_allow_html=True)

st.markdown("<h2>Telemark · Pro Wax & Tune</h2>", unsafe_allow_html=True)

# -------------------- HELPERS --------------------
COUNTRY_MAP = {
    "Italia (IT)": "it", "Svizzera (CH)": "ch", "Francia (FR)": "fr",
    "Austria (AT)": "at", "Germania (DE)": "de", "Norvegia (NO)": "no",
    "Svezia (SE)": "se", "Finlandia (FI)": "fi"
}

def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # Nome corto + admin/valle + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("county") or addr.get("state") or ""
    cc = (addr.get("country_code") or "").upper()
    short = ", ".join([p for p in [name, admin1] if p])
    if cc: short += f" — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q) < 2: return []
    try:
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        cc = st.session_state.get("pref_country_cc")
        if cc: params["countrycodes"] = cc
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params=params,
                         headers={"User-Agent":"telemark-wax-pro/1.1"},
                         timeout=8)
        r.raise_for_status()
        st.session_state._options = {}
        out=[]
        for item in r.json():
            addr = item.get("address",{}) or {}
            lat = float(item.get("lat",0.0)); lon = float(item.get("lon",0.0))
            label = f"{flag(addr.get('country_code',''))}  {concise_label(addr, item.get('display_name',''))}"
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"addr":addr,"label":label}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        arr = r.json().get("elevation",[])
        return float(arr[0]) if arr else None
    except: return None

def fetch_open_meteo(lat, lon, tzname="Europe/Rome", days=7):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "timezone": tzname,
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","rain","snowfall","cloudcover","windspeed_10m",
            "surface_pressure","is_day","weathercode"
        ]),
        "forecast_days": days
    }, timeout=30)
    r.raise_for_status()
    return r.json()

def prp_type_row(row):
    prp = row["precipitation"]
    rain = row.get("rain",0.0); snow = row.get("snowfall",0.0)
    if pd.isna(prp) or prp<=0: return "none"
    if rain>0 and snow>0: return "mixed"
    if snow>0: return "snow"
    if rain>0: return "rain"
    # fallback by WMO code
    code = int(row.get("weathercode",0) or 0)
    if code in {71,73,75,77,85,86}: return "snow"
    if code in {51,53,55,61,63,65,80,81,82}: return "rain"
    return "mixed"

def build_df(js:dict):
    h = js["hourly"]; df = pd.DataFrame(h)
    # times are strings already in tz local -> keep naive
    df["time"] = pd.to_datetime(df["time"], utc=False)
    # cast / clean
    for col in ["temperature_2m","dew_point_2m","relative_humidity_2m",
                "precipitation","rain","snowfall","cloudcover","windspeed_10m",
                "surface_pressure","is_day","weathercode"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # derived
    df["prp_type"] = df.apply(prp_type_row, axis=1)
    df.rename(columns={
        "temperature_2m":"T2m","dew_point_2m":"Td","relative_humidity_2m":"RH",
        "cloudcover":"Cloud","windspeed_10m":"Wind","surface_pressure":"P"
    }, inplace=True)
    # scaling
    df["Cloud"] = (df["Cloud"]/100.0).clip(0,1)
    df["Wind"]  = (df["Wind"]/3.6).clip(lower=0)  # m/s
    return df

# === Snow surface temperature & condition model (fast, robust) =========
def compute_snow_model(df:pd.DataFrame, dt_hours=1.0):
    """
    Energy-balance–inspired, robust in realtime:
    - Shortwave/longwave via cloud fraction
    - Convective exchange with wind
    - Wetness from precip type + T + RH
    - 5 mm top-layer relaxation
    """
    df = df.copy()
    # flags
    is_snow = df["prp_type"].str.lower().eq("snow")
    is_rain = df["prp_type"].str.lower().eq("rain")
    is_mixed= df["prp_type"].str.lower().eq("mixed")
    is_day  = (df["is_day"].fillna(1).astype(int) == 1)

    # Effective wet flag
    # wet when: rain/mixed OR T>0 OR high RH with sun OR snow near 0
    tw = (df["T2m"] + df["Td"]) / 2.0
    wet = (
        is_rain | is_mixed |
        (df["T2m"] > 0.0) |
        (is_day & (df["Cloud"]<0.35) & (df["T2m"]>=-3) & (df["RH"]>=75)) |
        (is_snow & ((df["T2m"]>=-1) | (tw>-0.5)))
    )

    # Radiative/convective cooling “strength”
    clear = (1.0 - df["Cloud"]).clip(0,1)
    windc = df["Wind"].clip(upper=8.0)
    # baseline negative offset from air T (night clear stronger)
    drad = (1.0 + 3.2*clear - 0.25*windc).clip(0.3, 4.8)

    T_surf = pd.Series(index=df.index, dtype=float)
    T_top5 = pd.Series(index=df.index, dtype=float)

    # Wet surface clamps to melting point
    T_surf.loc[wet] = 0.0
    # Dry surface: colder than air by radiative/convective loss
    dry = ~wet
    T_surf.loc[dry] = df.loc[dry, "T2m"] - drad.loc[dry]

    # Sunny-cold correction (glazing)
    sunny_cold = is_day & dry & df["T2m"].between(-12, 0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (df["T2m"] + 0.6*(1.0 - df["Cloud"]))[sunny_cold],
        pd.Series(-0.7, index=df.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # Relaxation for top 5 mm (faster if wet/windy/precip)
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[wet | (df["Wind"]>=6) | is_snow | is_rain | is_mixed] = 3.0
    tau.loc[(~is_day) & (df["Wind"]<2) & (df["Cloud"]<0.25)] = 8.0
    alpha = 1.0 - np_exp(-dt_hours / tau.values)  # vector safe

    if len(df) > 0:
        T_top5.iloc[0] = min(float(df["T2m"].iloc[0]), 0.0)
        for i in range(1, len(df)):
            prev = T_top5.iloc[i-1]
            T_top5.iloc[i] = prev + alpha[i] * (T_surf.iloc[i] - prev)

    # snow “state” & glide index
    cond, glide, conf = [], [], []
    for i,row in df.iterrows():
        t2, ts, rh, w = row["T2m"], T_surf[i], row["RH"], row["Wind"]
        ptype = str(row["prp_type"]).lower()
        # condition string (new / packed / wet / glazed / icy / sugar / etc.)
        if ptype in ("snow","mixed") and t2 <= -1:
            c = "neve nuova / fredda"
        elif ptype in ("snow","mixed") and t2 > -1:
            c = "neve nuova umida"
        elif ptype == "rain" or t2 >= 0 or rh >= 95:
            c = "bagnata / primaverile"
        elif (ts < -6 and w < 3):
            c = "molto fredda / secca"
        elif (ts <= -2 and rh < 80):
            c = "fredda / compatta"
        elif (ts > -2 and ts <= 0):
            c = "granolosa / trasformata"
        else:
            c = "variabile"

        # glide index (0=collosa, 100=molto scorrevole)
        # base: vicino a 0°C e bagnata scorre, freddo secco meno
        g = 50
        if ts >= -0.3: g += 25
        if ptype == "rain" or t2 >= 0: g += 15
        if rh > 90 and ts > -1: g += 10
        if ts < -6: g -= 25
        if w < 1 and ts < -4: g -= 10
        g = int(max(0, min(100, g)))

        # confidence: più alto con precipitazioni/venti moderati e copertura media
        conf_i = 60
        if (row["precipitation"] > 0): conf_i += 15
        if 0.2 <= row["Cloud"] <= 0.8: conf_i += 10
        if 2 <= row["Wind"] <= 6: conf_i += 5
        conf_i = int(max(20, min(95, conf_i)))

        cond.append(c); glide.append(g); conf.append(conf_i)

    out = df.copy()
    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    out["cond"] = cond
    out["glide_index"] = glide
    out["confidence"] = conf
    return out

def np_exp(x):
    # safe exp for list/series
    import numpy as _np
    return _np.exp(_np.array(x, dtype=float))

def window_by_day(df, tzname, target_day:date, s:time, e:time):
    # df["time"] naive local -> compare by .dt.date & .dt.time
    D = df.copy()
    dcol = D["time"].dt.date
    tcol = D["time"].dt.time
    mask = (dcol == target_day) & (tcol >= s) & (tcol <= e)
    W = D.loc[mask]
    return W if not W.empty else D[dcol == target_day].head(7)

# -------------------- WAX BANDS & BRANDS --------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Violet/Blue",-12,-4),("MX-E Red",-5,0),("MX-E Warm",-2,10)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_for(tsurf, discipline):
    # recommend structure name + angles
    if tsurf <= -10:
        fam = "Lineare fine (freddo/secco)"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}.get(discipline,88.0)
    elif tsurf <= -3:
        fam = "Incrociata / leggera onda (universale)"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}.get(discipline,88.0)
    else:
        fam = "Scarico diagonale / caldo-umido"; base = 0.8 if tsurf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}.get(discipline,88.0)
    return fam, side, base

# ==================== 1) RICERCA LOCALITÀ ====================
st.subheader("1) Scegli paese e cerca località")

cA, cB = st.columns([1,2])
with cA:
    country_label = st.selectbox("Paese", list(COUNTRY_MAP.keys()), index=0, help="Filtra la ricerca al paese selezionato")
    st.session_state["pref_country_cc"] = COUNTRY_MAP[country_label]
with cB:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Scrivi… (es. Champoluc, Plateau Rosa, Cervinia, Val d’Isère…) – la lista appare senza premere Invio",
        clear_on_submit=False,
        default=None
    )

# state defaults
lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
tzname = "Europe/Rome"  # fisso per semplicità (Open-Meteo lo usa solo come stringa)

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon; st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b>{alt_txt}</div>", unsafe_allow_html=True)

# ==================== 2) Finestre + Giorno ====================
st.subheader("2) Giorno e finestre orarie A · B · C")
cdate, chz = st.columns([1,2])
with cdate:
    target_day = st.date_input("Giorno di riferimento", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))
with chz:
    horizon = st.slider("Ore previsione (da ora)", 12, 168, 72, 12, help="Orizzonte massimo disponibile")

c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s"); A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s"); B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s"); C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

# ==================== 3) Meteo + Analisi neve ====================
st.subheader("3) Meteo & Analisi neve")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon, tzname, days=7)
        src = build_df(js)
        # limita orizzonte (da adesso)
        now0 = pd.Timestamp.now().floor("H")
        src = src[src["time"] >= now0].head(horizon).reset_index(drop=True)
        res = compute_snow_model(src, dt_hours=1.0)

        st.success("Dati meteo caricati e modello neve calcolato.")
        # tabella pulita
        show = res[["time","T2m","Td","RH","Wind","precipitation","prp_type","T_surf","T_top5","cond","glide_index","confidence"]].copy()
        show.rename(columns={
            "time":"Ora locale","T2m":"T aria (°C)","Td":"T rugiada (°C)","RH":"UR (%)",
            "Wind":"Vento (m/s)","precipitation":"Prp (mm/h)","prp_type":"Tipo prp",
            "T_surf":"T neve sup (°C)","T_top5":"T top 5mm (°C)","cond":"Condizione",
            "glide_index":"Indice di scorrevolezza","confidence":"Affidabilità (%)"
        }, inplace=True)
        st.dataframe(show, use_container_width=True)

        # grafici compatti
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T supercie neve"); plt.plot(t,res["T_top5"],label="T top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["precipitation"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # Blocchi A/B/C
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = window_by_day(res, tzname, target_day, s, e)
            if W.empty:
                st.warning("Nessun dato nell’intervallo selezionato."); continue
            t_med = float(W["T_surf"].mean())
            cond_mode = W["cond"].mode().iloc[0] if not W["cond"].mode().empty else W["cond"].iloc[0]
            glide_med = int(W["glide_index"].mean())
            conf_med = int(W["confidence"].mean())

            st.markdown(
                f"<div class='card'><div class='kpi'>"
                f"<div><b>T_surf medio:</b> {t_med:.1f}°C</div>"
                f"<div><b>Condizione:</b> {cond_mode}</div>"
                f"<div><b>Indice di scorrevolezza:</b> {glide_med}/100</div>"
                f"<div><b>Affidabilità:</b> {conf_med}%</div>"
                f"</div></div>", unsafe_allow_html=True
            )

            # WAX cards
            cR1 = st.columns(4); cR2 = st.columns(4)
            for i,(name,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cR1[i].markdown(f"<div class='brand'><div style='font-weight:800'>{name}</div><div>{rec}</div></div>", unsafe_allow_html=True)
            for i,(name,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cR2[i].markdown(f"<div class='brand'><div style='font-weight:800'>{name}</div><div>{rec}</div></div>", unsafe_allow_html=True)

            # Strutture + angoli (tabella fissa delle 4 discipline)
            fam_ref, _, _ = tune_for(t_med, "GS")
            st.markdown(f"**Struttura consigliata (riferimento GS):** {fam_ref}")
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
