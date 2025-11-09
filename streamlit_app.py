# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, datetime as dt
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- THEME (scuro + colori accesi) --------------------
PRIMARY = "#10bfcf"; BG = "#0b1220"; CARD = "#0f172a"; TEXT = "#e5f6ff"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --card:{CARD}; --text:{TEXT}; --primary:{PRIMARY}; }}
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 600px at 20% -10%, #12233a 0%, {BG} 45%); }}
.block-container {{ padding-top: .6rem; }}
h1,h2,h3,h4,h5,p,span,div,label {{ color: {TEXT}; }}
.card {{ background: var(--card); border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:14px; box-shadow: 0 12px 30px rgba(0,0,0,.35); }}
.badge {{ display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,.12);
         background: rgba(16,191,207,.08); color:#a5f3fc; font-size:.78rem }}
.kpi {{ display:flex;gap:10px;align-items:center; padding:8px 10px; border-radius:10px; background:rgba(255,255,255,.04); border:1px dashed rgba(255,255,255,.14); }}
.kpi .lab {{ font-size:.8rem; opacity:.8 }}
.kpi .val {{ font-weight:800 }}
.banner {{ padding:10px 12px; border-radius:12px; border:1px solid rgba(255,255,255,.12); display:flex; gap:10px; align-items:center }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# -------------------- UTILS --------------------
def flag(cc:str)->str:
    try:
        c = cc.upper(); return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

def nominatim_search(q:str):
    if not q or len(q)<2: return []
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
        r.raise_for_status()
        st.session_state._options = {}
        out=[]
        for item in r.json():
            addr = item.get("address",{}) or {}
            short = concise_label(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag(cc)}  {short}"
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"label":label}
            out.append(key)
        return out
    except:
        return []

def get_elev(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); js = r.json()
        if "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except: pass
    return None

def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        # aggiungo RH per visibilità “umidità aria”
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}; rain_codes = {51,53,55,61,63,65,80,81,82}
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
    out["time"] = df["time"]
    out["T2m"] = df["temperature_2m"].astype(float)
    out["RH"]  = df["relative_humidity_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

# Stima T_surf/T_top5 più “realistica”
def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    rain = df["prp_type"].str.lower().eq("rain")
    mixed = df["prp_type"].str.lower().eq("mixed")
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1

    # criterio "bagnato": pioggia o T2m>1.0, oppure neve con T2m>-0.5 e RH>90
    wet = (rain | mixed | (df["T2m"]>1.0) | (snow & (df["T2m"]>-0.5) & (df["RH"]>90)))
    T_surf = pd.Series(index=df.index, dtype=float)
    T_surf.loc[wet] = 0.0  # neve a 0 in condizioni bagnate

    # asciutto: T_surf resta sotto l’aria per raffreddamento radiativo + vento
    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=6.0)
    # delta radiativo: 0.8–4.0 °C in base a cielo/vento
    drad = (0.8 + 3.2*clear - 0.25*windc).clip(0.5, 4.0)
    T_surf.loc[dry] = (df["T2m"] - drad)[dry]
    # limite superiore: non oltre 0 °C
    T_surf = T_surf.clip(upper=0.0)

    # strato 0–5 mm: rilassa verso T_surf con tau variabile
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[rain | mixed | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    T_top5 = pd.Series(index=df.index, dtype=float)
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)
        for i in range(1,len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    return df

def slice_by_date_and_time(res, timezone, day:dt.date, s:dt.time, e:dt.time):
    t = res["time"].dt.tz_localize(tz.gettz(timezone), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==day) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W

# -------- Indice cromatico + descrizione condizioni + affidabilità ----------
def chroma_and_condition(window_df: pd.DataFrame):
    if window_df.empty:
        return 0, "#999999", "Dati insufficienti", 0

    t = window_df["T_surf"].mean(skipna=True)
    rh = window_df["RH"].mean(skipna=True)
    prp = window_df["prp_mmph"].mean(skipna=True)
    typ = window_df["prp_type"].mode().iloc[0] if not window_df["prp_type"].mode().empty else "none"

    # base score da T_surf (più freddo/secco = punteggio più alto)
    base = 100 - (t+15)*3.0  # t≈-15 -> ~100 ; t≈0 -> ~55
    if t>0: base -= 15
    base = max(0, min(100, base))

    # penalità/bonus umidità
    if rh>=90: base -= 20
    elif rh>=75: base -= 8
    else: base += 5

    # precipitazione
    if typ=="rain": base -= 35
    elif typ=="mixed": base -= 25
    elif typ=="snow":
        # neve nuova: penalità leggera (più lenta) se >0.3 mm/h
        if prp>=0.3: base -= 10

    score = int(max(0, min(100, round(base))))

    # colore + descrizione
    if score>=80: color, cond = "#3b82f6", "fredda/secca"
    elif score>=60: color, cond = "#22c55e", "fredda"
    elif score>=40: color, cond = "#f59e0b", "umida prossima a 0°C"
    else: color, cond = "#ef4444", "bagnata/pioggia"

    # affidabilità: dipende da numero campioni + coerenza
    n = len(window_df)
    spread = float(window_df["T_surf"].max() - window_df["T_surf"].min()) if n>1 else 0
    reliability = int(max(0, min(100, (min(n,8)/8)*100 - spread*6)))
    return score, color, cond, reliability

# -------------------- Ricerca località --------------------
st.markdown("#### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi… es. Champoluc, Plateau Rosa, Cervinia",
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

elev = get_elev(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><span class='lab'>Località</span><span class='val'>{place_label}</span><span class='lab'>{alt_txt}</span></div>", unsafe_allow_html=True)

# -------------------- Finestre A/B/C (con DATA) --------------------
st.markdown("#### 2) Finestre A · B · C")
today = dt.date.today()
c1,c2,c3 = st.columns(3)

with c1:
    A_date = st.date_input("Giorno A", today, min_value=today, max_value=today+dt.timedelta(days=6), key="A_d")
    A_start = st.time_input("Inizio A", dt.time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   dt.time(11,0), key="A_e")
with c2:
    B_date = st.date_input("Giorno B", today, min_value=today, max_value=today+dt.timedelta(days=6), key="B_d")
    B_start = st.time_input("Inizio B", dt.time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   dt.time(13,0), key="B_e")
with c3:
    C_date = st.date_input("Giorno C", today, min_value=today, max_value=today+dt.timedelta(days=6), key="C_d")
    C_start = st.time_input("Inizio C", dt.time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   dt.time(16,0), key="C_e")

hours = st.slider("Ore previsione da scaricare", 24, 168, 96, 12)

# -------------------- Meteo & Calcolo --------------------
st.markdown("#### 3) Scarica meteo & calcola")
if st.button("Scarica/aggiorna previsioni", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        # Tabella dati (più leggibile)
        tbl = res[["time","T2m","RH","td","prp_mmph","prp_type","cloud","wind","T_surf","T_top5"]].copy()
        tbl.columns = ["Ora","T aria (°C)","UR (%)","T rugiada (°C)","Prec (mm/h)","Tipo","Nuvolosità","Vento (m/s)","T neve superficiale (°C)","T neve 0–5mm (°C)"]
        st.dataframe(tbl, use_container_width=True)

        # Grafici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve surf"); plt.plot(t,res["T_top5"],label="T neve 0–5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # Blocchi
        blocks = {
            "A": (A_date, A_start, A_end),
            "B": (B_date, B_start, B_end),
            "C": (C_date, C_start, C_end),
        }

        # Marchi (liste brevi – puoi riestendere in seguito)
        SWIX = [("PS5",-18,-10),("PS6",-12,-6),("PS7",-8,-2),("PS8",-4,4),("PS10",0,10)]
        TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
        VOLA = [("MX Blue",-25,-10),("MX Violet",-12,-4),("MX Red",-5,0),("MX Yellow",-2,6)]
        RODE = [("R20",-18,-8),("R30",-10,-3),("R40",-5,0),("R50",-1,10)]
        BRANDS=[("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE)]
        def pick(bands,t):
            for n,tmin,tmax in bands:
                if t>=tmin and t<=tmax: return n
            return bands[-1][0] if t>bands[-1][2] else bands[0][0]

        def structure_for(t):
            if t<=-10: return "Linear Fine (S1)"
            if t<=-3:  return "Cross Hatch (S1)"
            if t<=0.5: return "Wave (S2)"
            return "Thumb Print (S2)"

        for L,(d,s,e) in blocks.items():
            st.markdown(f"### Blocco {L} — {d.isoformat()}  {s.strftime('%H:%M')}–{e.strftime('%H:%M')}")
            W = slice_by_date_and_time(res, "Europe/Rome", d, s, e)
            if W.empty:
                st.info("Nessun dato nella finestra scelta (allarga l’intervallo o aumenta Ore previsione).")
                continue

            t_med = float(W["T_surf"].mean())
            score, color, cond, rel = chroma_and_condition(W)
            st.markdown(
                f"<div class='banner' style='background:linear-gradient(90deg, {color}22, transparent)'>"
                f"<div class='kpi'><span class='lab'>T neve media</span><span class='val'>{t_med:.1f}°C</span></div>"
                f"<div class='kpi'><span class='lab'>Indice cromatico</span><span class='val' style='color:{color}'>{score}</span></div>"
                f"<div class='kpi'><span class='lab'>Condizione</span><span class='val'>{cond}</span></div>"
                f"<div class='kpi'><span class='lab'>Affidabilità</span><span class='val'>{rel}%</span></div>"
                f"</div>", unsafe_allow_html=True
            )

            cols = st.columns(len(BRANDS))
            for i,(brand,bands) in enumerate(BRANDS):
                rec = pick(bands, t_med)
                cols[i].markdown(f"<div class='kpi'><span class='lab'>{brand}</span><span class='val'>{rec}</span></div>", unsafe_allow_html=True)

            st.markdown(f"**Struttura consigliata:** {structure_for(t_med)}")
            rows=[]
            # angolo SIDE richiesto come 88/87 ecc; BASE in funzione del caldo
            def tune_for(t,disc):
                if t<=-10: base=0.5; side={"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[disc]
                elif t<=-3: base=0.7; side={"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[disc]
                else: base = 0.8 if t<=0.5 else 1.0; side={"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[disc]
                return base, side
            for dsc in ["SL","GS","SG","DH"]:
                b,sid = tune_for(t_med,dsc)
                rows.append([dsc, structure_for(t_med), f"{sid:.1f}°", f"{b:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

        st.download_button("Scarica CSV risultati",
                           data=res.rename(columns={"time":"Ora"}).to_csv(index=False),
                           file_name="forecast_snowtemp.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
