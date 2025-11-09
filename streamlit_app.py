# telemark_pro_app.py
import math, base64, os
from datetime import date, time, timedelta
from typing import Tuple

import pandas as pd
import numpy as np
import requests
import streamlit as st
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- THEME --------------------
PRIMARY = "#0bd3e8"   # turchese acceso
ACCENT  = "#f97316"   # arancio vivo
OK      = "#22c55e"
MUTED   = "#93a3b8"
CARD_BG = "rgba(255,255,255,.04)"
STROKE  = "rgba(255,255,255,.12)"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 30% -10%, #0b1220 0%, #0a0f1a 45%, #0a0f1a 100%);
}}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color:#e5ecff; }}
.kbd {{ background:#111827;border:1px solid {STROKE}; padding:1px 6px;border-radius:6px; }}
.card {{ background:{CARD_BG}; border:1px solid {STROKE}; border-radius:16px; padding:14px; box-shadow:0 10px 28px rgba(0,0,0,.35); }}
.badge {{ display:inline-flex; gap:6px; align-items:center; border:1px solid {PRIMARY}55; color:#bff6ff;
         background:{PRIMARY}1a; padding:6px 10px;border-radius:999px; font-size:.8rem; }}
.kpi {{ display:flex; gap:10px; align-items:center; background:rgba(11,211,232,.08);
       border:1px dashed {PRIMARY}; padding:10px 12px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:{MUTED}; }}
.kpi .val {{ font-size:1rem; font-weight:800; color:#e8f7ff; }}
.banner {{ border:1px solid {STROKE}; background:linear-gradient(90deg, rgba(11,211,232,.08), rgba(249,115,22,.08));
          padding:10px 14px; border-radius:12px; }}
hr {{ border:none;border-top:1px solid {STROKE}; margin:.5rem 0 }}
table td, table th {{ color:#e5ecff !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown("<h2>Telemark · Pro Wax & Tune</h2>", unsafe_allow_html=True)

# -------------------- HELPERS --------------------
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # Nome corto + regione + codice paese
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or addr.get("municipality") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

COUNTRY_CHOICES = {
    "IT": "Italia", "FR": "Francia", "CH": "Svizzera", "AT": "Austria",
    "DE": "Germania", "ES": "Spagna", "NO": "Norvegia", "SE": "Svezia"
}

def nominatim_search(q:str, cc_filter:str):
    if not q or len(q) < 2: 
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q, "format":"json", "limit": 12, "addressdetails": 1,
                "countrycodes": cc_filter.lower() if cc_filter else None
            },
            headers={"User-Agent":"telemark-wax-pro/1.1"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._options = {}
        out = []
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

def get_elevation(lat:float, lon:float)->float|None:
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except:
        pass
    return None

def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

# --------- physics bits ----------
def rel_humidity_from_T_Td(T:pd.Series, Td:pd.Series)->pd.Series:
    """T, Td in °C -> RH% using Magnus formula."""
    # saturation vapor pressure (hPa)
    def esat(c): return 6.112 * np.exp((17.62*c)/(243.12 + c))
    T = pd.to_numeric(T, errors="coerce")
    Td= pd.to_numeric(Td, errors="coerce")
    rh = (esat(Td) / esat(T)) * 100.0
    return rh.clip(0,100)

def precip_type(row)->str:
    prp = row.get("precipitation",0.0)
    if prp <= 0: return "none"
    rain = row.get("rain",0.0); snow = row.get("snowfall",0.0)
    if rain>0 and snow>0: return "mixed"
    if snow>0: return "snow"
    if rain>0: return "rain"
    code = int(row.get("weathercode") or 0)
    if code in {71,73,75,77,85,86}: return "snow"
    if code in {51,53,55,61,63,65,80,81,82}: return "rain"
    return "mixed"

def compute_df(js, horizon_hours:int)->pd.DataFrame:
    h = js["hourly"]
    df = pd.DataFrame(h)
    # times are strings in local timezone -> make naive timestamps
    df["time"] = pd.to_datetime(df["time"], utc=False)
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(horizon_hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"]  = df["time"]
    out["T2m"]   = pd.to_numeric(df["temperature_2m"], errors="coerce")
    out["Td"]    = pd.to_numeric(df["dew_point_2m"], errors="coerce")
    out["cloud"] = (pd.to_numeric(df["cloudcover"], errors="coerce")/100.0).clip(0,1)
    out["wind"]  = (pd.to_numeric(df["windspeed_10m"], errors="coerce")/3.6).clip(lower=0) # m/s
    out["is_day"]= (pd.to_numeric(df["is_day"], errors="coerce").fillna(1).astype(int) == 1)
    out["prp"]   = pd.to_numeric(df["precipitation"], errors="coerce").fillna(0.0)
    out["rain"]  = pd.to_numeric(df["rain"], errors="coerce").fillna(0.0)
    out["snow"]  = pd.to_numeric(df["snowfall"], errors="coerce").fillna(0.0)
    out["wcode"] = pd.to_numeric(df["weathercode"], errors="coerce").fillna(0).astype(int)
    out["prp_type"] = df.apply(precip_type, axis=1)
    out["RH"] = rel_humidity_from_T_Td(out["T2m"], out["Td"]).round(1)

    # ---- surface snow temperature with relaxation ----
    # baseline: T* towards which the surface tends (energy balance proxy)
    sun = out["is_day"]
    clear = (1.0 - out["cloud"]).clip(0,1)
    windc = out["wind"].clip(upper=8.0)

    # radiative/advection driver (°C)
    # more cooling with clear & wind; warming if wet conditions
    driver = - (1.2 + 2.5*clear + 0.25*windc)  # negative -> surface colder than air
    wetmask = (out["T2m"]>0) | (out["rain"]>0) | (out["prp_type"].isin(["rain","mixed"]))
    driver = driver.where(~wetmask, -0.2)  # wet surfaces stay near 0

    # candidate surface equilibrium T*
    T_star = out["T2m"] + driver
    T_star = T_star.clip(upper=0.0)  # neve non supera 0°C

    # relaxation over time (tau in h)
    tau = pd.Series(6.0, index=out.index)
    tau.loc[out["snow"]>0] = 2.5
    tau.loc[out["rain"]>0] = 1.5
    tau.loc[(~sun) & (clear>0.7) & (windc<2)] = 8.0
    alpha = 1.0 - np.exp(-1.0 / tau)  # dt=1h

    T_surf = pd.Series(index=out.index, dtype=float)
    if len(out)>0:
        T_surf.iloc[0] = min(out["T2m"].iloc[0], 0.0)
        for i in range(1, len(out)):
            T_prev = T_surf.iloc[i-1]
            T_surf.iloc[i] = T_prev + alpha.iloc[i]*(T_star.iloc[i] - T_prev)
    out["T_surf"] = T_surf.round(2)

    # top 5mm temperature (slower memory)
    tau5  = (tau*1.8).clip(upper=14.0)
    alpha5= 1.0 - np.exp(-1.0 / tau5)
    T_top5= pd.Series(index=out.index, dtype=float)
    if len(out)>0:
        T_top5.iloc[0] = min(out["T2m"].iloc[0], 0.0)
        for i in range(1, len(out)):
            T_prev = T_top5.iloc[i-1]
            T_top5.iloc[i] = T_prev + alpha5.iloc[i]*(out["T_surf"].iloc[i] - T_prev)
    out["T_top5"] = T_top5.round(2)

    # glide index (0-100): peak when T_surf is just below 0 and RH 60-90,
    # penalize heavy precip & extreme cold
    t = out["T_surf"].clip(-15, 0)
    gi = 100*np.exp(-((t+0.5)/3.5)**2)  # bell around -0.5°C
    gi *= (0.7 + 0.003* out["RH"].clip(40,95))    # humidity sweet spot
    gi *= (1.0 - 0.08*out["prp"].clip(0,6))       # too much precip reduces glide
    gi *= (1.0 - 0.02*out["wind"].clip(0,8))      # strong wind -> snow roughness
    out["glide_index"] = gi.clip(0,100).round(0)

    return out

def slice_day_window(res:pd.DataFrame, the_day:date, s:time, e:time)->pd.DataFrame:
    D = res.copy()
    D["date"] = D["time"].dt.date
    D["clock"]= D["time"].dt.time
    W = D[(D["date"]==the_day) & (D["clock"]>=s) & (D["clock"]<=e)]
    return W if not W.empty else D.iloc[:6]

def classify_snow(window:pd.DataFrame)->Tuple[str,float]:
    """Return (condizione, affidabilità%)"""
    if window.empty: return ("N/D", 0.0)
    t = window["T_surf"].mean()
    rh= window["RH"].mean()
    pr = window["prp"].sum()
    snow = window["snow"].sum()
    rain = window["rain"].sum()
    sun  = (window["is_day"].mean()>0.5)
    cloud= window["cloud"].mean()

    if snow>0.8:
        cond = "Neve nuova"
    elif rain>0.4 or (t>-0.3):
        cond = "Bagnata / Primaverile"
    elif t<-7 and cloud<0.4:
        cond = "Fredda e secca (velluto)"
    elif pr>0.6 and t<-1:
        cond = "Mista / granulosa"
    elif (not sun) and (t<-2) and cloud<0.3:
        cond = "Rigelo / compatta"
    else:
        cond = "Trasformata / granulosa"

    # affidabilità: penalizza prp alta, gradienti forti e cloud estremi
    var_t = float(window["T_surf"].std() or 0)
    reliab = 85.0
    reliab -= min(pr*8, 25)
    reliab -= min(var_t*12, 20)
    reliab -= abs(cloud-0.5)*30
    return (cond, float(np.clip(reliab, 35, 95)))

# --------- WAX bands & brands ----------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Warm",-2,10)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def structure_for(t_surf:float)->str:
    # Solo nomi, niente immagini
    if t_surf <= -10: return "Linear Fine (S1)"
    if t_surf <=  -3: return "Cross Hatch (S1)"
    if t_surf <=  -1: return "Wave (S2)"
    return "Thumb Print (S2)"

# -------------------- UI --------------------
st.markdown("<div class='badge'>⚡ Nuovo algoritmo · T_surf · Umidità · Condizione neve · Indice di scorrevolezza</div>", unsafe_allow_html=True)

# 1) Nazione + ricerca località
st.subheader("1) Località")
colA, colB = st.columns([1,3])
with colA:
    cc = st.selectbox("Nazione", options=list(COUNTRY_CHOICES.keys()), format_func=lambda x: f"{COUNTRY_CHOICES[x]} ({x})")
with colB:
    selected = st_searchbox(lambda q: nominatim_search(q, cc), key="place",
                            placeholder="Digita la località (es. Champoluc, Plateau Rosa, Sestriere)…",
                            clear_on_submit=False, default=None)

# default/fallback
lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", f"{flag('IT')}  Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='card'>📍 <b>{place_label}</b>{alt_txt}</div>", unsafe_allow_html=True)

# 2) Giorno + Finestre
st.subheader("2) Giorno & Finestre A · B · C")
c0, c1, c2, c3 = st.columns([1.2,1,1,1])
with c0:
    the_day = st.date_input("Giorno", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))
with c1:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)

# 3) Meteo + analisi
st.subheader("3) Meteo & Analisi neve")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "auto")
        res = compute_df(js, hours)

        # banner località
        st.success(f"Dati caricati per **{place_label}** · {len(res)} ore")

        # Tabella compatta
        show = res[["time","T2m","Td","RH","cloud","wind","prp","T_surf","T_top5","glide_index"]].copy()
        show.columns = ["Ora","T aria (°C)","DewPt (°C)","Umidità (%)","Nuvolosità","Vento (m/s)","Prec (mm/h)","T neve surf (°C)","T neve 5mm (°C)","Indice di scorrevolezza"]
        st.dataframe(show, use_container_width=True, height=320)

        # grafici sintetici
        t = res["time"]
        fig1 = plt.figure(figsize=(6.2, 2.6), dpi=130)
        plt.plot(t,res["T2m"],label="T aria")
        plt.plot(t,res["T_surf"],label="T neve (surf)")
        plt.plot(t,res["T_top5"],label="T neve (5mm)")
        plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); plt.legend(loc="best"); st.pyplot(fig1)

        # Blocchi
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = slice_day_window(res, the_day, s, e)
            t_med = float(W["T_surf"].mean())
            cond, reliability = classify_snow(W)
            glide = int(W["glide_index"].mean())

            st.markdown(
                f"<div class='banner'><b>Condizione stimata:</b> {cond} · "
                f"<b>Affidabilità:</b> {int(reliability)}% · "
                f"<b>Indice di scorrevolezza:</b> {glide}/100 · "
                f"<b>T_surf medio:</b> {t_med:.1f}°C</div>",
                unsafe_allow_html=True
            )

            # Wax consigliate (8 marchi)
            cols = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[:4]):
                rec = pick_wax(bands, t_med)
                cols[i].markdown(f"<div class='card'><b>{brand}</b><br/><span class='muted'>{rec}</span></div>", unsafe_allow_html=True)
            cols = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[4:]):
                rec = pick_wax(bands, t_med)
                cols[i].markdown(f"<div class='card'><b>{brand}</b><br/><span class='muted'>{rec}</span></div>", unsafe_allow_html=True)

            # Struttura consigliata (solo nome)
            st.markdown(f"**Struttura consigliata:** {structure_for(t_med)}")

            # Tabellina discipline senza toggle
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                # angoli leggermente adattivi
                if t_med <= -10:
                    base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
                elif t_med <= -3:
                    base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
                else:
                    base = 0.8 if t_med<=0.5 else 1.0
                    side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                rows.append([d, structure_for(t_med), f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","SIDE (°)","BASE (°)"]))

        # download CSV
        st.download_button("Scarica CSV completo", data=res.to_csv(index=False), file_name="telemark_forecast.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
