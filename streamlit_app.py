# telemark_pro_app.py
# Telemark · Pro Wax & Tune — rebuild 100% dark + new snow model
# Ruben Favre — Champoluc

import streamlit as st
import pandas as pd
import numpy as np
import requests, math, base64
from datetime import datetime, date, time, timedelta
from dateutil import tz
import matplotlib.pyplot as plt

# -------------------- THEME (dark, vivid accents) --------------------
PRIMARY = "#0ea5b7"   # turchese Telemark
PRIMARY_SOFT = "rgba(14,165,183,.14)"
RED = "#ef4444"
GREEN = "#22c55e"
AMBER = "#f59e0b"
TEXT = "#e5e7eb"
MUTED = "#94a3b8"
BG = "#0b1220"        # quasi nero blu
CARD = "#0f172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --primary: {PRIMARY}; }}
[data-testid="stAppViewContainer"] > .main {{ background: {BG}; }}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4, p, span, label, div {{ color: {TEXT}; }}
small, .muted {{ color: {MUTED}; }}
.card {{ background:{CARD}; border:1px solid rgba(255,255,255,.08); 
        border-radius:14px; padding:12px; box-shadow:0 10px 25px rgba(0,0,0,.35); }}
.btn {{
  background:{PRIMARY}; color:white; border:0; border-radius:10px; padding:.6rem .9rem;
  font-weight:700; letter-spacing:.2px; cursor:pointer;
}}
.badge {{
  display:inline-flex; gap:.35rem; align-items:center;
  background:{PRIMARY_SOFT}; border:1px solid rgba(14,165,183,.4);
  color:{TEXT}; border-radius:999px; padding:.25rem .55rem; font-size:.78rem;
}}
.kpi {{ display:flex; gap:.6rem; align-items:center;
       background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
       padding:.5rem .7rem; border-radius:12px; }}
.kpi .lab {{ color:{MUTED}; font-size:.78rem }}
.kpi .val {{ font-weight:800 }}
.progress {{
  height:10px; width: 100%; background:rgba(255,255,255,.08); border-radius:999px;
}}
.progress > div {{ height:100%; border-radius:999px; background:linear-gradient(90deg,#ef4444,#f59e0b,#22c55e); }}
.tbl thead tr th {{ background:rgba(255,255,255,.05); }}
.tbl, .tbl * {{ color:{TEXT}; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Dark UI · Previsioni Open-Meteo · Altitudine · Blocchi A/B/C · Indice di scorrevolezza</span>", unsafe_allow_html=True)


# -------------------- HELPERS --------------------
def flag(cc:str)->str:
    try:
        c = cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    """Nome corto e comprensibile per evitare generici tipo 'Zermatt' quando cerchi Plateau Rosa."""
    name = addr.get("attraction") or addr.get("alpine_hut") or addr.get("peak") or \
           addr.get("hamlet") or addr.get("village") or addr.get("neighbourhood") or \
           addr.get("suburb") or addr.get("town") or addr.get("city") or \
           addr.get("ski") or fallback.split(",")[0]
    area = addr.get("county") or addr.get("region") or addr.get("state") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, area] if p]
    out = ", ".join(parts)
    return (out + (f" — {cc}" if cc else "")) or fallback

def search_locations(q:str)->list[dict]:
    if not q or len(q)<2: return []
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q":q,"format":"json","limit":12,"addressdetails":1},
                         headers={"User-Agent":"telemark-pro-wax/1.0"}, timeout=8)
        r.raise_for_status()
        results=[]
        for it in r.json():
            addr = it.get("address",{}) or {}
            label = concise_label(addr, it.get("display_name",""))
            lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
            cc = addr.get("country_code","")
            results.append({
                "label": f"{flag(cc)} {label}",
                "lat": lat, "lon": lon, "addr": addr
            })
        return results
    except: return []


def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if js and "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except: pass
    return None


def fetch_open_meteo(lat, lon, start_dt:datetime, hours:int, tzname="Europe/Rome"):
    """Richiede tutti i campi necessari per il modello."""
    end_dt = start_dt + timedelta(hours=hours)
    params = {
        "latitude": lat, "longitude": lon, "timezone": tzname,
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","snowfall","rain","cloudcover","windspeed_10m",
            "is_day","weathercode","precipitation_probability"
        ]),
        "start_date": start_dt.date().isoformat(),
        "end_date": end_dt.date().isoformat(),
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# -------------------- SNOW MODEL v2 --------------------
def build_df(js, start_dt:datetime, hours:int):
    h = js["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    # seleziona la finestra richiesta (da start_dt a start_dt+hours)
    t0 = pd.Timestamp(start_dt).tz_localize(None)
    t1 = t0 + pd.Timedelta(hours=hours)
    df = df[(df["time"]>=t0)&(df["time"]<t1)].reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["Td"]   = df["dew_point_2m"].astype(float)
    out["RH"]   = df["relative_humidity_2m"].astype(float).clip(0,100)
    out["Cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["Wind"] = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)      # m/s
    out["Sun"]  = df["is_day"].astype(int)
    out["Prp"]  = df["precipitation"].astype(float)
    out["Rain"] = df.get("rain", pd.Series([0]*len(df))).astype(float)
    out["Snow"] = df.get("snowfall", pd.Series([0]*len(df))).astype(float)
    out["Wcode"]= df.get("weathercode", pd.Series([0]*len(df))).astype(int)
    out["PrpProb"]= df.get("precipitation_probability", pd.Series([np.nan]*len(df))).astype(float)

    # tipo precipitazione
    def prp_type(row):
        if row.Prp<=0: return "none"
        if row.Rain>0 and row.Snow>0: return "mixed"
        if row.Snow>0 and row.Rain==0: return "snow"
        if row.Rain>0 and row.Snow==0: return "rain"
        code=row.Wcode
        if code in (71,73,75,77,85,86): return "snow"
        if code in (51,53,55,61,63,65,80,81,82): return "rain"
        return "mixed"
    out["PrpType"] = out.apply(prp_type, axis=1)
    return out


def compute_snow_temperatures(df:pd.DataFrame):
    """
    Heuristica fisica:
      - se bagnata/precipitazione liquida => T_surf≈0
      - se neve nuova e T2m>-1 => 0
      - scambio radiativo/notturno fa scendere rispetto a T2m in modo proporzionale a cielo sereno e poco vento
      - strato top5 mm evolve verso T_surf con costante di tempo variabile (vento, precipitazioni, notte)
    Restituisce T_surf e T_top5 (°C), indice scorrevolezza 0-100, descrizione neve, affidabilità %.
    """
    df = df.copy()
    n = len(df)
    if n==0:
        return df

    # Base: bagnato?
    tw = (df["T2m"] + df["Td"])/2.0
    wet_mask = (
        (df["PrpType"].isin(["rain","mixed"])) |
        (df["T2m"]>0) |
        ((df["Sun"]==1) & (df["Cloud"]<0.35) & (df["T2m"]>=-3)) |
        ((df["PrpType"]=="snow") & (df["T2m"]>=-1)) |
        ((df["PrpType"]=="snow") & (tw>-0.5))
    )

    # T_surf iniziale
    T_surf = np.full(n, np.nan, dtype=float)
    T_surf[wet_mask.values] = 0.0

    # Asciutto -> raffreddamento radiativo
    dry = ~wet_mask.values
    clear = (1.0 - df["Cloud"].values).clip(0,1)
    windc = df["Wind"].values.clip(max=6.0)
    # coefficiente radiativo (0.5..4.5)
    drad = (1.5 + 3.0*clear - 0.3*windc).clip(0.5, 4.5)
    T_surf[dry] = (df["T2m"].values[dry] - drad[dry])

    # Sole freddo: limitiamo sottoraffreddamento
    sunup = (df["Sun"].values==1)
    sunny_cold = sunup & dry & ((df["T2m"].values>=-10) & (df["T2m"].values<=0))
    if sunny_cold.any():
        alt_est = df["T2m"].values[sunny_cold] + 0.5*(1.0 - df["Cloud"].values[sunny_cold])
        T_surf[sunny_cold] = np.minimum(alt_est, -0.5)

    # Evoluzione strato top 5 mm (risolve "sempre 0")
    T_top5 = np.full(n, np.nan, dtype=float)
    # tau (ore) più breve se vento forte / precipitazione / neve nuova; più lunga in notte calma e sereno
    tau = np.full(n, 6.0)
    tau[(df["PrpType"].isin(["rain","snow"])).values | (df["Wind"].values>=6.0)] = 3.0
    tau[(df["Sun"].values==0) & (df["Wind"].values<2.0) & (df["Cloud"].values<0.3)] = 8.0
    alpha = 1.0 - np.exp(-1.0 / tau)  # dt=1h

    # inizializza: se in bagnato prendi 0, altrimenti clamp a min(T2m,0)
    T_top5[0] = 0.0 if wet_mask.values[0] else min(df["T2m"].values[0], 0.0)
    for i in range(1, n):
        T_top5[i] = T_top5[i-1] + alpha[i]*(T_surf[i] - T_top5[i-1])

    df["T_surf"] = np.round(T_surf, 2)
    df["T_top5"] = np.round(T_top5, 2)

    # ---------------- Indice di scorrevolezza (0-100) ----------------
    # fattori: vicinanza a 0°C (pellicola), neve nuova bagnata (alta), freddo secco (medio-basso), vento alto (medio),
    # gradi giorno -> penalità per -10°C e oltre
    near0 = np.exp(-((df["T_surf"])**2)/(2*1.2**2))   # campana attorno a 0
    wet_bonus = wet_mask.astype(float)*0.25
    wind_pen = np.clip(df["Wind"]/12.0, 0, 0.25)
    cold_pen = np.clip(np.maximum(-df["T_surf"]-6, 0)/8.0, 0, 0.35)
    glide = (0.55*near0 + wet_bonus + 0.15*(1-wind_pen) + 0.05*(1-cold_pen))
    glide = (glide*100).clip(0,100)
    df["GlideIndex"] = np.round(glide,0)

    # ---------------- Nevicate / consistenza & affidabilità ----------------
    # classificazione semplice
    def classify(row):
        if row["PrpType"] in ("rain","mixed") or row["T_surf"]>-0.4:
            return "bagnata/primaverile"
        if row["PrpType"]=="snow" and row["T_surf"]>-2:
            return "neve nuova umida"
        if row["T_surf"]<=-2 and row["Cloud"]<0.4 and row["Wind"]<4:
            return "fredda/secca"
        if row["Wind"]>=8:
            return "ventata/compatta"
        return "trasformata/granulosa"

    df["SnowType"] = df.apply(classify, axis=1)

    # affidabilità: media di (1-varianza cloud) + presenza prob. precipitazione + vento moderato
    prp_prob = df["PrpProb"].fillna(50) / 100.0
    calm = (1 - np.clip(df["Wind"]/12.0, 0, 1))
    sky = 1 - np.abs(df["Cloud"] - df["Cloud"].rolling(3, min_periods=1, center=True).mean()).fillna(0)
    rel = (0.45*sky + 0.25*(1-np.abs(prp_prob-0.5)*2) + 0.30*calm)
    df["Reliability"] = (rel*100).clip(35,95).round(0)

    return df


def window_today(df:pd.DataFrame, tzname, s:time, e:time, start_dt:datetime):
    # finestra sul giorno della data selezionata
    local = df.copy()
    local["dt"] = pd.to_datetime(local["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent="shift_forward", ambiguous="NaT")
    day = start_dt.astimezone(tz.gettz(tzname)).date()
    W = local[(local["dt"].dt.date==day) & (local["dt"].dt.time>=s) & (local["dt"].dt.time<=e)]
    return W if not W.empty else local.head(6)


# -------------------- UI — 1) LOCALITÀ & DATA --------------------
st.markdown("#### 1) Località e data di partenza")
colL, colBtn, colAlt = st.columns([3,1,2])

with colL:
    q = st.text_input("Cerca (Enter per cercare)", placeholder="es. Plateau Rosa, Champoluc, Cervinia", key="q", label_visibility="visible")
with colBtn:
    do_search = st.button("Cerca", use_container_width=True)
with colAlt:
    start_day = st.date_input("Giorno di inizio", date.today(), format="DD/MM/YYYY")

if (do_search or st.session_state.get("q_submit", False) or (q and q.endswith("\n"))):
    pass  # non serve altro: usiamo il bottone

results = search_locations(q.strip()) if (do_search and q.strip()) else []
if results:
    choices = [f"{r['label']}  ({r['lat']:.3f},{r['lon']:.3f})" for r in results]
    idx = st.selectbox("Scegli risultato", list(range(len(choices))), format_func=lambda i: choices[i], index=0)
    sel = results[idx]
    st.session_state["lat"] = sel["lat"]; st.session_state["lon"] = sel["lon"]; st.session_state["place_label"]=sel["label"]

# default Champoluc se non ancora scelto
lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹 Champoluc — IT")

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {place_label}{alt_txt}")

# orizzonte e blocchi orari
colh1, colh2 = st.columns([2,1])
with colh1:
    hours_horizon = st.slider("Ore previsione (orizzonte)", min_value=12, max_value=168, value=72, step=12)
with colh2:
    tzname = "Europe/Rome"   # niente selettore, stabilizzato

st.markdown("#### 2) Finestre orarie A · B · C")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0));   A_end   = st.time_input("Fine A",   time(11,0))
with c2:
    B_start = st.time_input("Inizio B", time(11,0));  B_end   = st.time_input("Fine B",   time(13,0))
with c3:
    C_start = st.time_input("Inizio C", time(13,0));  C_end   = st.time_input("Fine C",   time(16,0))


# -------------------- RUN — 3) PREVISIONI & CALCOLO --------------------
st.markdown("#### 3) Dati meteo & calcolo")
if st.button("Scarica/aggiorna previsioni", type="primary"):
    try:
        start_dt = datetime.combine(start_day, time(0,0)).replace(tzinfo=tz.gettz(tzname))
        js = fetch_open_meteo(lat, lon, start_dt, hours_horizon, tzname)
        src = build_df(js, start_dt, hours_horizon)
        res = compute_snow_temperatures(src)

        st.success(f"Dati per **{place_label}** caricati.")
        # tabella chiara e compatta
        show = res.copy()
        show["time"] = pd.to_datetime(show["time"]).dt.strftime("%d/%m %H:%M")
        show = show[[
            "time","T2m","Td","RH","Cloud","Wind","Prp","PrpType","T_surf","T_top5","GlideIndex","SnowType","Reliability"
        ]]
        show = show.rename(columns={
            "time":"Ora", "T2m":"T° aria", "Td":"T° rugiada", "RH":"UR %", "Cloud":"Nuvolosità",
            "Wind":"Vento m/s", "Prp":"Prec. mm/h", "PrpType":"Tipo", "T_surf":"T° neve sup",
            "T_top5":"T° top 5mm", "GlideIndex":"Indice scorrevolezza", "SnowType":"Neve", "Reliability":"Affidabilità %"
        })
        st.dataframe(show, use_container_width=True, hide_index=True, column_config={
            "Nuvolosità": st.column_config.NumberColumn(format="%.2f"),
            "Vento m/s": st.column_config.NumberColumn(format="%.1f"),
            "Prec. mm/h": st.column_config.NumberColumn(format="%.2f"),
            "Indice scorrevolezza": st.column_config.NumberColumn(format="%.0f"),
        }, key="tblmain")

        # grafici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(figsize=(7,2.6)); 
        plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve sup"); plt.plot(t,res["T_top5"],label="T top 5mm")
        plt.title("Temperature (°C)"); plt.legend(); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)

        fig2 = plt.figure(figsize=(7,2.3)); 
        plt.bar(t,res["Prp"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # blocchi A/B/C
        blocks = {"A":(A_start,A_end), "B":(B_start,B_end), "C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = window_today(res, tzname, s, e, start_dt)
            t_med = float(W["T_surf"].mean())
            glide_med = float(W["GlideIndex"].mean())
            snow_mode = W["SnowType"].value_counts().idxmax()
            rel_med = int(W["Reliability"].mean())

            # banner condizioni
            colB1, colB2, colB3 = st.columns([1.3,1,1.2])
            with colB1:
                st.markdown(f"<div class='kpi'><div class='lab'>T° neve media</div><div class='val'>{t_med:.1f}°C</div></div>", unsafe_allow_html=True)
            with colB2:
                st.markdown(f"<div class='kpi'><div class='lab'>Neve</div><div class='val'>{snow_mode}</div></div>", unsafe_allow_html=True)
            with colB3:
                st.markdown(f"<div class='kpi'><div class='lab'>Indice di scorrevolezza</div><div class='val'>{glide_med:.0f}/100</div></div>", unsafe_allow_html=True)
            st.markdown(f"<small class='muted'>Affidabilità stimata: {rel_med}%</small>", unsafe_allow_html=True)

            # tabella discipline (senza toggle)
            def tune_for(t_surf, discipline):
                if t_surf <= -10:
                    fam = "Lineare fine (freddo/secco)"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[discipline]
                elif t_surf <= -3:
                    fam = "Incrociata universale";          base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[discipline]
                else:
                    fam = "Scarico diagonale / V (umido/caldo)"; base = 0.8 if t_surf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[discipline]
                return fam, side, base

            rows = []
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            df_tune = pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"])
            st.table(df_tune)

        # download CSV
        st.download_button("Scarica CSV completo", data=res.to_csv(index=False), file_name="telemark_forecast_snow.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
