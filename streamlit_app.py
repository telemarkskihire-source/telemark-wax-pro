# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, math, base64
from datetime import time, date, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ====================== THEME (DARK, MODERNO) ======================
PRIMARY = "#10bfcf"    # turchese Telemark
ACCENT  = "#22d3ee"    # ciano acceso
GOOD    = "#34d399"    # verde
WARN    = "#f59e0b"    # arancione
BAD     = "#ef4444"    # rosso
TEXT    = "#e5e7eb"    # testo chiaro
MUTED   = "#9ca3af"
BG0     = "#0b1220"    # sfondo app
CARD    = "#0f172a"    # card scura
BORD    = "rgba(255,255,255,.08)"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --primary: {PRIMARY};
}}
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 700px at 10% 0%, #0d1b2a 0%, {BG0} 40%, #0b1220 100%); }}
.block-container {{ padding-top: 1rem; padding-bottom: 3rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color:{TEXT}; }}
hr {{ border:none; border-top:1px solid {BORD}; margin: .6rem 0 1rem 0; }}

.hero {{ padding:18px 18px; border:1px solid {BORD}; background:linear-gradient(180deg, #0f172a 0%, #0b1220 100%);
         border-radius:18px; box-shadow: 0 10px 24px rgba(0,0,0,.35); display:flex; gap:16px; align-items:center; }}
.badge {{ border:1px solid {BORD}; padding:6px 10px; border-radius:999px; font-size:.78rem; opacity:.85; }}
.card {{ background:{CARD}; border:1px solid {BORD}; border-radius:16px; padding:14px; box-shadow:0 8px 20px rgba(0,0,0,.28); }}
.brand {{ display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:12px;
          background:rgba(255,255,255,.03); border:1px solid {BORD}; }}
.brand .nm {{ font-size:.8rem; color:{MUTED}; }}
.brand .rec {{ font-weight:800; }}
.kpi {{ display:flex; gap:8px; align-items:center; background:rgba(16,191,207,.06);
       border:1px dashed rgba(16,191,207,.45); padding:10px 12px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:#93c5fd; }}
.kpi .val {{ font-size:1rem; font-weight:800; }}

.banner {{
  border:1px solid {BORD}; border-radius:14px; padding:10px 14px; display:flex; gap:10px; align-items:center;
  background: linear-gradient(90deg, rgba(34,211,238,.12) 0%, rgba(34,211,238,.04) 100%);
}}
.banner .title {{ font-weight:800; color:{ACCENT}; }}
.smallmuted {{ color:{MUTED}; font-size:.85rem; }}

table td, table th {{ color:{TEXT} !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown(
    f"<div class='hero'>"
    f"<div style='font-size:1.35rem;font-weight:800;color:{ACCENT}'>Telemark · Pro Wax & Tune</div>"
    f"<div class='badge'>Previsioni → Temperatura neve → Sciolina · Struttura · Angoli</div>"
    f"</div>",
    unsafe_allow_html=True
)

# ====================== UTILS ======================
COUNTRIES = {
    "Italia (IT)": "it",
    "Svizzera (CH)": "ch",
    "Francia (FR)": "fr",
    "Austria (AT)": "at",
    "Norvegia (NO)": "no",
    "Svezia (SE)": "se",
    "Finlandia (FI)": "fi",
    "Germania (DE)": "de",
    "Tutti i paesi": None,
}

def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label_from_address(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc:
        short = f"{short} — {cc}"
    return short

def nominatim_search(search: str):
    if not search or len(search) < 2:
        return []
    country = st.session_state.get("country_code", None)
    params = {"q": search, "format":"json", "limit": 12, "addressdetails": 1}
    if country: params["countrycodes"] = country
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": "telemark-wax-app/1.1"},
            timeout=8
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        for item in r.json():
            addr = item.get("address", {}) or {}
            short = concise_label_from_address(addr, item.get("display_name",""))
            cc = addr.get("country_code","") or ""
            lat = float(item.get("lat", 0)); lon = float(item.get("lon", 0))
            label = f"{flag_emoji(cc)}  {short}"
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_map[key] = (lat, lon, label, addr)
            out.append(key)
        return out
    except Exception:
        return []

def get_elevation(lat:float, lon:float):
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

def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
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
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours, day:date, tzname:str):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    # Filtro giorno scelto (locale)
    tzinfo = tz.gettz(tzname)
    df["local_date"] = df["time"].dt.tz_localize(tzinfo, nonexistent='shift_forward', ambiguous='NaT').dt.date
    df = df[df["local_date"]==day]
    # Se il giorno è oggi, filtra ore passate
    nowloc = pd.Timestamp.now(tz=tzinfo).floor("H")
    df = df[df["time"]>=nowloc] if day==nowloc.date() else df
    df = df.head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["RH"]  = df["relative_humidity_2m"].astype(float)  # %
    out["td"]  = df["dew_point_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

# ---------------- SNOW TEMPERATURE MODEL (rivisto) ----------------
def compute_snow_temperature(df, dt_hours=1.0):
    """
    Heuristica fisica semplificata:
    - Raffreddamento radiativo: più cielo sereno → T_surf più bassa delle T2m
      cool = clip( 1.8 + 3.2*(1-cloud) - 0.25*wind , 0.6..5.5 )
    - Se 'wet' (pioggia/misto o neve con T vicino 0 e dew point alto) la T_surf ~ 0/-0.2
    - Integrazione termica dello strato top5mm con una costante di tempo tau variabile
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    # “bagnato” proxy: precipitazione liquida o neve con T e DP alti
    wet = (
        rain |
        ((df["T2m"] > 0.2) & (df["prp_mmph"] > 0)) |
        (snow & (df["T2m"] > -0.5) & (df["td"] > -1.0)) |
        (df["RH"] >= 95)  # saturazione → brina/acqua superficiale
    )

    # Raffreddamento radiativo
    clear = (1.0 - df["cloud"]).clip(0,1)
    cool = (1.8 + 3.2*clear - 0.25*df["wind"]).clip(0.6, 5.5)

    # Stima T_surf grezza
    T_raw = df["T2m"] - cool

    # Se bagnata: vicino a zero, ma non sempre esattamente 0
    T_surf = np.where(wet, np.minimum(0.0, df["T2m"] - 0.2), T_raw)

    # Vincoli di stabilità (non meno di T2m-8, non più di T2m+1)
    T_surf = np.maximum(T_surf, df["T2m"] - 8.0)
    T_surf = np.minimum(T_surf, df["T2m"] + 1.0)

    # Integrazione strato top 5 mm (memoria termica)
    tau = np.full(len(df), 6.0)
    tau = np.where(wet | (df["wind"]>=6), 3.0, tau)
    tau = np.where((df["sunup"]==0) & (df["wind"]<2) & (df["cloud"]<0.3), 8.0, tau)
    alpha = 1.0 - np.exp(-dt_hours / np.maximum(tau, 0.5))

    T_top5 = np.zeros(len(df))
    if len(df)>0:
        T_top5[0] = min(df["T2m"].iloc[0], 0.0) if wet.iloc[0] else T_surf[0]
        for i in range(1, len(df)):
            T_top5[i] = T_top5[i-1] + alpha[i] * (T_surf[i] - T_top5[i-1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    df["wet_flag"] = wet.astype(int)
    return df

# ---------------- CLASSIFICAZIONE NEVE + INDICI ----------------
def classify_snow(df):
    """
    Restituisce:
    - descrizione sintetica
    - indice di scorrevolezza (0..100)
    - confidenza (0..100)
    """
    if df.empty:
        return "Dati insufficienti", 0, 0

    # medie finestra
    t = float(df["T_surf"].mean())
    rh = float(df["RH"].mean())
    prp = float(df["prp_mmph"].mean())
    snow_h = (df["prp_type"].str.lower()=="snow").mean()
    wet_ratio = df["wet_flag"].mean()
    wind = float(df["wind"].mean())

    # “recent snow”: neve nelle ultime 6 ore della finestra
    recent_snow = (df["prp_type"].tail(6).str.lower()=="snow").any()

    # descrizione
    if wet_ratio>0.4 or (t>-1 and (prp>0.3 or rh>95)):
        desc = "Neve bagnata / primaverile"
    elif recent_snow and t<=-3:
        desc = "Neve nuova asciutta"
    elif recent_snow and t>-3:
        desc = "Neve nuova umida"
    elif t<=-6:
        desc = "Neve molto fredda / abrasiva"
    else:
        desc = "Compatta / trasformata"

    # indice di scorrevolezza (più alto = più scorrevole)
    # base su prossimità a 0°C e umidità moderata; penalità per forti nevicate o vento alto
    base = 60 - 1.8*abs(t + 0.5)  # picco vicino a -0.5°C
    moist_bonus = 0
    if -2 <= t <= 0.5:
        moist_bonus = 10 if 70<=rh<=95 else (5 if rh>95 else 0)
    precip_pen = -15 if prp>1.0 else (-7 if prp>0.2 else 0)
    wind_pen = -8 if wind>7 else (-4 if wind>4 else 0)
    wet_adj = -5 if wet_ratio>0.6 else 0
    glide = int(np.clip(base + moist_bonus + precip_pen + wind_pen + wet_adj, 0, 100))

    # confidenza: più alta con segnali coerenti e poco rumore
    conf = 60
    conf += 10 if (snow_h>0.5 or prp<0.2) else 0
    conf += 10 if (0.2<df["cloud"].mean()<0.8) else 0
    conf -= 10 if df.isna().any().any() else 0
    conf = int(np.clip(conf, 20, 95))

    return desc, glide, conf

# ---------------- WAX BANDS (8 marchi) ----------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [
    ("Swix"     ,SWIX),
    ("Toko"     ,TOKO),
    ("Vola"     ,VOLA),
    ("Rode"     ,RODE),
    ("Holmenkol",HOLM),
    ("Maplus"   ,MAPL),
    ("Start"    ,START),
    ("Skigo"    ,SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ---------------- STRUTTURA & ANGOLI ----------------
def tune_for(t_surf, discipline):
    # Solo nomi struttura (niente immagini)
    if t_surf <= -10:
        structure = "Lineare fine (freddo/secco)"
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        structure = "Cross-hatch leggero / onda leggera (universale)"
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        structure = "Scarico diagonale / V (umido/caldo)"
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return structure, side_map.get(discipline, 88.0), base

# ====================== SIDEBAR: COUNTRY + DATE ======================
with st.sidebar:
    st.markdown("### 🌍 Area di ricerca")
    country_label = st.selectbox("Seleziona nazione per filtrare la ricerca", list(COUNTRIES.keys()), index=0)
    st.session_state["country_code"] = COUNTRIES[country_label]

    st.markdown("### 📅 Giorno previsioni")
    today = date.today()
    day = st.date_input("Scegli giorno (fino a 7 giorni)", value=today, min_value=today, max_value=today+timedelta(days=6))

# ====================== 1) RICERCA LOCALITÀ ======================
st.markdown("#### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (es. Champoluc Ramey, Plateau Rosa, Cervinia)",
    clear_on_submit=False,
    default=None
)

# decode selection -> lat,lon,label
if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label, addr = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc", {}))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

# Fallback default if none selected yet
lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "🇮🇹 Champoluc, Valle d’Aosta — IT")

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {label}{alt_txt}")

# ====================== 2) FINESTRE A/B/C + ORE ======================
st.markdown("#### 2) Finestre orarie A · B · C")
c1, c2, c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9, 0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11, 0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11, 0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13, 0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13, 0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16, 0), key="C_e")

hours = st.slider("Orizzonte orario (max per il giorno scelto)", 6, 24, 12, 6)

# ====================== 3) DOWNLOAD & CALCOLO ======================
st.markdown("#### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

def window_slice(res, tzname, s, e, day:date):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==day) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(6)

if go:
    try:
        tzname = "Europe/Rome"
        js = fetch_open_meteo(lat, lon, tzname)
        src = build_df(js, hours, day, tzname)
        res = compute_snow_temperature(src, dt_hours=1.0)

        st.success(f"Dati per **{label}** caricati.")
        # Tabella pulita
        tbl = res[["time","T2m","td","RH","cloud","wind","prp_mmph","prp_type","T_surf","T_top5"]].copy()
        tbl = tbl.rename(columns={
            "time":"Ora (locale)", "T2m":"Aria °C", "td":"DewPt °C", "RH":"UR %", "cloud":"Copertura", "wind":"Vento m/s",
            "prp_mmph":"Prec mm/h", "prp_type":"Tipo", "T_surf":"Neve sup °C", "T_top5":"Neve top5mm °C"
        })
        st.dataframe(tbl.round(2), use_container_width=True)

        # Grafici rapidi
        t = pd.to_datetime(res["time"])
        import matplotlib.pyplot as plt
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="Aria (°C)"); plt.plot(t,res["T_surf"],label="Neve sup (°C)"); plt.plot(t,res["T_top5"],label="Top 5mm (°C)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        st.download_button("Scarica CSV risultato", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # Blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n### Blocco {L} · {day.strftime('%a %d %b')}")
            W = window_slice(res, tzname, s, e, day)
            if W.empty:
                st.info("Nessun dato nella finestra selezionata.")
                continue

            t_med = float(W["T_surf"].mean())
            desc, glide, conf = classify_snow(W)

            # Banner condizioni
            st.markdown(
                f"<div class='banner'>"
                f"<div class='title'>Condizioni: {desc}</div>"
                f"<div class='smallmuted'>T_surf medio: <b>{t_med:.1f}°C</b> · Indice di scorrevolezza: <b>{glide}</b>/100 · Affidabilità: <b>{conf}%</b></div>"
                f"</div>", unsafe_allow_html=True
            )

            # Wax cards (8 marchi)
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(
                    f"<div class='brand'><div style='width:10px;height:10px;border-radius:3px;background:{PRIMARY};'></div>"
                    f"<div><div class='nm'>{brand}</div><div class='rec'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><div style='width:10px;height:10px;border-radius:3px;background:{ACCENT};'></div>"
                    f"<div><div class='nm'>{brand}</div><div class='rec'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # Struttura + Angoli per discipline (solo nomi struttura, niente immagini)
            rows = []
            for d in ["SL","GS","SG","DH"]:
                sname, side_d, base_d = tune_for(t_med, d)
                rows.append([d, sname, f"{side_d:.1f}°", f"{base_d:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura consigliata","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
