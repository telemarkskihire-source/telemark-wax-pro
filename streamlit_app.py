# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, datetime as dt
from dateutil import tz
from streamlit_searchbox import st_searchbox
import matplotlib.pyplot as plt

# ------------------------ THEME (dark) ------------------------
PRIMARY = "#06b6d4"   # turchese vivo
ACCENT  = "#e2e8f0"   # testo chiaro
MUTED   = "#94a3b8"   # testo secondario
CARDBG  = "#0b1220"   # box
APPBG   = "#0a0f1a"   # sfondo

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 800px at 10% -10%, #0f1b2e 0%, {APPBG} 45%);
}}
.block-container {{ padding-top: 0.7rem; }}
h1,h2,h3,h4,h5,h6, label, p, span, div {{ color:{ACCENT}; }}
small,.muted {{ color:{MUTED}; }}
.card {{
  background:{CARDBG};
  border:1px solid rgba(255,255,255,.08);
  border-radius:16px; padding:14px; box-shadow:0 10px 24px rgba(0,0,0,.35);
}}
.badge {{
  display:inline-block; background:{PRIMARY}1A; color:{ACCENT};
  border:1px solid {PRIMARY}66; padding:.25rem .55rem; border-radius:999px; font-size:.78rem
}}
.kpi {{ display:flex; gap:.5rem; align-items:center; }}
.kpi .lab {{ font-size:.8rem; color:{MUTED}; }}
.kpi .val {{ font-size:1rem; font-weight:800; color:{ACCENT}; }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.09); margin:1rem 0 }}
.cond {{
  background: linear-gradient(90deg, {PRIMARY}22, transparent);
  border: 1px solid {PRIMARY}55; padding:.6rem .8rem; border-radius:12px;
  display:flex; justify-content:space-between; align-items:center;
}}
.tag {{ color:{ACCENT}; font-weight:700; }}
.conf {{ color:{MUTED}; font-size:.85rem }}
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

def concise_label(addr:dict, fallback:str)->str:
    # nome breve + admin1 + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
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

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        d = r.json()
        if d and "elevation" in d and d["elevation"]:
            return float(d["elevation"][0])
    except:
        pass
    return None

# ------------------------ INPUTS (località + giorno + orari) ------------------------
st.markdown("### 1) Località & giorno")
c1, c2 = st.columns([2,1])
with c1:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (es. Champoluc, Plateau Rosa, Cervinia)",
        clear_on_submit=False,
        default=None
    )
with c2:
    day = st.date_input("Giorno blocchi", value=dt.date.today(), format="DD/MM/YYYY")

# decode selection -> lat,lon,label
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        st.session_state["lat"] = info["lat"]; st.session_state["lon"] = info["lon"]
        st.session_state["place_label"] = info["label"]

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='badge'>Località: <b>{place_label}</b>{alt_txt}</div>", unsafe_allow_html=True)

st.markdown("### 2) Finestre orarie A · B · C")
cA, cB, cC = st.columns(3)
with cA:
    A_start = st.time_input("Inizio A", dt.time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   dt.time(11,0), key="A_e")
with cB:
    B_start = st.time_input("Inizio B", dt.time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   dt.time(13,0), key="B_e")
with cC:
    C_start = st.time_input("Inizio C", dt.time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   dt.time(16,0), key="C_e")

hours = st.slider("Ore previsione", 24, 168, 96, 12)

# ------------------------ DATA PIPELINE ------------------------
def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

def _prp_type(row):
    prp = row["precipitation"]; rain = row.get("rain",0.0); snow = row.get("snowfall",0.0)
    if prp<=0 or pd.isna(prp): return "none"
    if rain>0.1 and snow>0.1: return "mixed"
    if snow>0.1 and rain<=0.1: return "snow"
    if rain>0.1 and snow<=0.1: return "rain"
    return "mixed"

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["td"]   = df["dew_point_2m"].astype(float)
    out["rh"]   = df["relative_humidity_2m"].astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["precipitation"] = df["precipitation"].astype(float)
    out["rain"] = df["rain"].astype(float)
    out["snowfall"] = df["snowfall"].astype(float)
    out["weathercode"] = df["weathercode"].astype(int)
    out["prp_type"] = df[["precipitation","rain","snowfall"]].apply(lambda r: _prp_type(r), axis=1)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    # --- condizioni "bagnato" più realistiche ---
    wet = (
        (df["rain"] > 0.1) |
        (df["T2m"] >= 0.5) |
        ((df["snowfall"] > 0.2) & (df["T2m"] > -0.5))
    )
    # superficie neve teorica
    T_surf = pd.Series(index=df.index, dtype=float)

    # se bagnata, la superficie converge verso 0 (ma non sempre 0)
    # più è umida/piovosa, più si avvicina a 0
    wet_strength = (df["rain"].clip(0,2)/2.0) + ((df["T2m"].clip(lower=0)/5.0)) + (df["rh"]/200.0)
    T_surf.loc[wet] = (1-wet_strength[wet]) * df["T2m"][wet] + wet_strength[wet] * 0.0
    T_surf.loc[wet] = T_surf.loc[wet].clip(upper=0.2)  # non andare troppo sopra zero

    # se asciutta, applico raffreddamento radiativo/notturno + vento
    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=7.0)
    # delta radiativo (notte limpida raffredda molto)
    drad = (1.8 + 3.2*clear - 0.25*windc)  # °C oltre T2m
    drad = drad.clip(0.4, 4.8)
    T_surf.loc[dry] = df["T2m"][dry] - drad[dry]

    # piccolo vincolo fisico
    T_surf = T_surf.clip(lower=-25.0, upper=1.0)

    # strat superiore (5 mm) con inerzia
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)  # costante di tempo
    tau.loc[(df["snowfall"]>0.2) | (df["rain"]>0.1) | (df["wind"]>=6)] = 3.0
    tau.loc[(df["sunup"]==0) & (df["cloud"]<0.3) & (df["wind"]<2)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    return df

def window_slice(res, tzname, the_date: dt.date, s: dt.time, e: dt.time):
    t_local = res["time"].dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t_local
    mask_day = D["dt"].dt.date == the_date
    W = D[mask_day & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D[mask_day].head(7)

# ------------------------ CLASSIFICHE & INDICI ------------------------
def describe_conditions(W: pd.DataFrame):
    if W is None or W.empty:
        return "Dati insufficienti", 0.4
    t = float(W["T_surf"].mean())
    prp_snow = float(W["snowfall"].sum())
    prp_rain = float(W["rain"].sum())
    rh = float(W["rh"].mean())
    # etichette semplici
    if prp_rain > 0.5 or t > -0.2:
        tag = "Neve bagnata / umida"
    elif prp_snow > 0.8 and t > -5:
        tag = "Neve nuova / fresca"
    elif t <= -10:
        tag = "Neve molto fredda e secca"
    elif -10 < t <= -4:
        tag = "Neve fredda e asciutta"
    else:
        tag = "Neve trasformata / primaverile"

    # affidabilità (euristica): meno precipitazioni, RH moderata, più affidabile
    conf = 0.7
    conf -= min(prp_rain/5, 0.25)
    conf -= min(prp_snow/8, 0.2)
    conf -= max(0, (rh-95)/200)  # RH altissima riduce un po'
    conf = float(max(0.3, min(0.95, conf)))
    return tag, conf

def glide_index(W: pd.DataFrame):
    """Indice di scorrevolezza 0-100 (alto = più scorrevole). Euristico ma leggibile."""
    if W is None or W.empty:
        return 50
    t = float(W["T_surf"].mean())
    prp_snow = float(W["snowfall"].sum())
    prp_rain = float(W["rain"].sum())
    rh = float(W["rh"].mean())
    idx = 60
    # temperatura ideale -4..-1
    if -4 <= t <= -1: idx += 20
    elif -8 <= t < -4: idx += 10
    elif -1 < t <= 0.5: idx += 10

    # neve nuova penalizza
    if prp_snow > 0.5: idx -= 15
    if prp_snow > 1.0: idx -= 8

    # pioggia penalizza molto
    if prp_rain > 0.2: idx -= 20

    # umidità altissima può frenare
    if rh > 95: idx -= 10

    return int(max(5, min(95, idx)))

# ------------------------ RUN ------------------------
st.markdown("### 3) Scarica & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{place_label}** caricati.")

        # KPI rapidi
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(f"<div class='kpi'><span class='lab'>T aria (ora)</span><span class='val'>{res['T2m'].iloc[0]:.1f}°C</span></div>", unsafe_allow_html=True)
        with k2: st.markdown(f"<div class='kpi'><span class='lab'>T neve (surf)</span><span class='val'>{res['T_surf'].iloc[0]:.1f}°C</span></div>", unsafe_allow_html=True)
        with k3: st.markdown(f"<div class='kpi'><span class='lab'>RH</span><span class='val'>{res['rh'].iloc[0]:.0f}%</span></div>", unsafe_allow_html=True)
        with k4: st.markdown(f"<div class='kpi'><span class='lab'>Vento</span><span class='val'>{res['wind'].iloc[0]:.1f} m/s</span></div>", unsafe_allow_html=True)

        # grafici compatti
        t = res["time"]
        fig1 = plt.figure(figsize=(7,2.8))
        plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve (surf)"); plt.plot(t,res["T_top5"],label="T neve (top5)")
        plt.xticks(rotation=20); plt.legend(); plt.title("Temperature prossime ore"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(7,2.4))
        plt.bar(t,res["precipitation"]); plt.title("Precipitazione (mm/h)"); plt.xticks(rotation=20); plt.ylabel("mm/h")
        st.pyplot(fig2)

        # Tabella dati essenziali (più pulita)
        show = res[["time","T2m","T_surf","T_top5","rh","precipitation","rain","snowfall","cloud","wind","prp_type"]].copy()
        show.columns = ["Ora","T aria (°C)","T neve (°C)","T top5 (°C)","RH (%)","P (mm/h)","Pioggia","Neve","Nuvolosità","Vento (m/s)","Tipo prp"]
        st.dataframe(show, use_container_width=True, hide_index=True)

        st.download_button("Scarica CSV", data=show.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi A/B/C per il giorno selezionato
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n### Blocco {L} — {day.strftime('%d/%m/%Y')}")
            W = window_slice(res, "Europe/Rome", day, s, e)
            if W is None or W.empty:
                st.info("Nessun dato per questa finestra.")
                continue

            t_med = float(W["T_surf"].mean())
            t_air = float(W["T2m"].mean())
            rh_m  = float(W["rh"].mean())
            gidx  = glide_index(W)
            tag, conf = describe_conditions(W)
            conf_pct = int(round(conf*100))

            b1,b2,b3,b4 = st.columns(4)
            b1.metric("T neve media", f"{t_med:.1f} °C")
            b2.metric("T aria media", f"{t_air:.1f} °C")
            b3.metric("RH media", f"{rh_m:.0f} %")
            b4.metric("Indice di scorrevolezza", f"{gidx}/100")

            st.markdown(f"<div class='cond'><div class='tag'>{tag}</div><div class='conf'>Affidabilità stimata: {conf_pct}%</div></div>", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Errore: {e}")
