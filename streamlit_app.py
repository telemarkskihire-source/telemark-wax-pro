# telemark_pro_app.py
import os, math, base64, datetime as dt
from datetime import time, date
from dateutil import tz

import streamlit as st
import pandas as pd
import requests
import matplotlib.pyplot as plt
from streamlit_searchbox import st_searchbox

# ====================== THEME / STYLE ======================
PRIMARY = "#0fd3d5"   # turchese acceso
ACCENT  = "#e2e8f0"   # testo primario chiaro
MUTED   = "#94a3b8"   # testo secondario
CARD_BG = "#0b1220"   # card bg
APP_BG1 = "#0b1220"
APP_BG2 = "#0f172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --primary: {PRIMARY};
  --accent: {ACCENT};
  --muted: {MUTED};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 10% -5%, #102032 0%, {APP_BG1} 25%), linear-gradient(180deg, {APP_BG1} 0%, {APP_BG2} 100%);
}}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4,h5,label, p, span, div {{ color: {ACCENT}; }}
.small, .muted {{ color: {MUTED}; }}
.card {{
  background:{CARD_BG};
  border:1px solid rgba(255,255,255,.08);
  border-radius:16px;
  padding:16px;
  box-shadow:0 12px 28px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.04);
}}
.brand {{
  display:flex; align-items:center; gap:.6rem; padding:.5rem .7rem;
  border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.03);
  border-radius:12px;
}}
.kpi {{
  display:flex; gap:.6rem; align-items:center;
  background:rgba(15,211,213,.10); border:1px dashed rgba(15,211,213,.5);
  padding:.5rem .65rem; border-radius:12px;
}}
.kpi b {{ color:#a5f3fc }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.08); margin:.75rem 0 }}
.banner {{
  border-radius:14px; padding:12px 14px; border:1px solid rgba(255,255,255,.08);
  display:flex; gap:.9rem; align-items:flex-start;
}}
.banner.good  {{ background: linear-gradient(90deg, rgba(34,197,94,.12), rgba(34,197,94,.05)); }}
.banner.mid   {{ background: linear-gradient(90deg, rgba(234,179,8,.12), rgba(234,179,8,.05)); }}
.banner.bad   {{ background: linear-gradient(90deg, rgba(239,68,68,.12), rgba(239,68,68,.05)); }}
.badge {{
  display:inline-flex; gap:.45rem; align-items:center;
  padding:.25rem .5rem; border-radius:999px; font-size:.78rem;
  border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.06)
}}
select, input, textarea {{ color:black !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# ====================== HELPERS ======================
def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

COUNTRY_OPTIONS = [
    ("Tutti", ""), ("🇮🇹 Italia", "it"), ("🇨🇭 Svizzera", "ch"), ("🇫🇷 Francia","fr"),
    ("🇦🇹 Austria","at"), ("🇩🇪 Germania","de"), ("🇸🇪 Svezia","se"), ("🇳🇴 Norvegia","no"),
    ("🇺🇸 USA","us"), ("🇨🇦 Canada","ca"),
]

def concise_label(addr:dict, display_name:str)->str:
    # Nome corto + admin1 + CC
    name = addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or \
           addr.get("town") or addr.get("city") or display_name.split(",")[0]
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search_factory(country_code_filter:str):
    def _search(q:str):
        if not q or len(q)<2:
            return []
        try:
            params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
            if country_code_filter: params["countrycodes"] = country_code_filter
            r = requests.get("https://nominatim.openstreetmap.org/search",
                             params=params,
                             headers={"User-Agent":"telemark-wax-pro/1.2"},
                             timeout=8)
            r.raise_for_status()
            out = []
            st.session_state._options = {}
            for item in r.json():
                addr = item.get("address",{}) or {}
                label_short = concise_label(addr, item.get("display_name",""))
                cc = addr.get("country_code","") or ""
                label = f"{flag(cc)}  {label_short}"
                lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
                key = f"{label}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
                out.append(key)
            return out
        except:
            return []
    return _search

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

# ====================== DATA FETCH ======================
def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","rain","snowfall","cloudcover","windspeed_10m",
            "is_day","weathercode"
        ]),
        "forecast_days": 7,
        "wind_speed_unit": "ms"   # m/s
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

# (Opzionale) Enrichment NOAA se token presente e Paese US — fallback automatico se fallisce.
def try_noaa_enrichment(lat, lon):
    token = os.getenv("NOAA_TOKEN", "").strip()
    if not token:
        return None
    try:
        # Esempio minimal: gridpoint meteogram NWS (solo per US). Qui solo sanity-check.
        # In una evoluzione si può fondere NBM probabilistico.
        headers = {"User-Agent":"telemark-wax-pro/1.2", "Accept":"application/geo+json"}
        meta = requests.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=headers, timeout=8)
        if meta.status_code!=200: return None
        grid = meta.json()["properties"]["forecastHourly"]
        fc = requests.get(grid, headers=headers, timeout=8)
        if fc.status_code!=200: return None
        # Non fondiamo i dati ora: l’algoritmo resta basato su Open-Meteo.
        return {"ok": True}
    except:
        return None

# ====================== TRANSFORMERS ======================
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

def build_df(js, hours, tzname):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])  # naive local to tz param
    now_local = pd.Timestamp.now(tz=tz.gettz(tzname)).tz_localize(None).floor("H")
    df = df[df["time"] >= now_local].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"]  = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"]   = df["temperature_2m"].astype(float)
    out["td"]    = df["dew_point_2m"].astype(float)
    out["RH"]    = df["relative_humidity_2m"].astype(float).clip(0,100)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = df["windspeed_10m"].astype(float) # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["snow_mmph"] = df["snowfall"].astype(float)
    out["rain_mmph"] = df["rain"].astype(float)
    return out

# ====================== SNOW PHYSICS (heuristic) ======================
def compute_snow_layers(df, dt_hours=1.0):
    """
    Modello semplificato ma più robusto:
    - se prp rain/mixed → superficie ~0°C
    - se T2m>0°C → superficie → 0°C (fusione)
    - altrimenti bilancio radiativo semplificato con cloud & vento per raffreddamento
    - T_top5 (0–5mm) = filtro esponenziale verso T_surf con tau variabile (vento/precip)
    - Stima liquid water fraction (LWF) vs 0°C, RH, prp
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1

    # Tw ~ (T + Td)/2 come proxy per umidità assoluta
    tw = (df["T2m"] + df["td"]) / 2.0

    # Condizione "wet" (tende a 0 °C)
    wet = (rain | (df["T2m"]>0) |
           (snow & (df["T2m"]>=-1)) |
           (sunup & (df["cloud"]<0.35) & (df["T2m"]>=-3)) |
           (snow & tw.ge(-0.5).fillna(False)))

    T_surf = pd.Series(index=df.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    # Raffreddamento radiativo: più cielo sereno & vento basso -> T_surf < T2m
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=8.0)  # m/s
    drad = (1.2 + 3.2*clear - 0.25*windc).clip(0.4, 4.5)
    T_surf.loc[dry] = df["T2m"][dry] - drad[dry]

    # Correzione "sole freddo": quando sole, se T2m tra -12 e 0 con cielo poco coperto,
    # la pelle può risalire, ma teniamo vincolo massimo -0.8
    sunny_cold = sunup & dry & df["T2m"].between(-12,0, inclusive="both") & (df["cloud"]<0.25)
    T_surf.loc[sunny_cold] = pd.concat([
        (df["T2m"] + 0.6*(1.0 - df["cloud"]))[sunny_cold],
        pd.Series(-0.8, index=df.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # Strato 0–5 mm: risposta con time constant variabile
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)   # h
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)  # primo step conservativo
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    # Liquid Water Fraction (stima qualitativa 0–1)
    # cresce vicino a 0°C, con RH alta e rain/mixed; decresce con freddo secco
    lwf = (
        (df["T_surf_est"] if "T_surf_est" in df.columns else 0)  # placeholder se volessimo fondere altri modelli
    )
    # usiamo direttamente T_surf e RH
    lwf = ((df["T2m"].clip(upper=0) + 0.8*df["RH"]/100.0) / 2.5).clip(0,1)
    lwf = lwf + (df["rain_mmph"].clip(lower=0)/2.0).clip(0,0.4)
    lwf = lwf.clip(0,1)

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    df["LWF"]    = lwf

    return df

def classify_snow(df: pd.DataFrame) -> pd.Series:
    """
    Classifica neve (testuale) basata su T_surf, LWF, snow recente, vento & sole.
    """
    out = []
    # accumulo neve ultima 6h
    snow6 = df["snow_mmph"].rolling(6, min_periods=1).sum().fillna(0)
    for i, row in df.iterrows():
        t = row["T_surf"]
        lwf = row["LWF"]
        prp = row["prp_type"].lower()
        w = row["wind"]; cl = row["cloud"]; sun = row["sunup"]==1
        s6 = snow6.iloc[i] if i < len(snow6) else 0

        if prp=="snow" and s6>=2:
            out.append("neve nuova")
        elif lwf>0.55:
            out.append("bagnata / trasformata")
        elif (t<=-8) and (w>6 or cl<0.3):
            out.append("fredda / secca")
        elif t<=-3:
            out.append("fredda")
        elif -3<t<0 and lwf<0.35:
            out.append("vecchia / compatta")
        else:
            out.append("primaverile / umida")
    return pd.Series(out, index=df.index)

def glide_index(df: pd.DataFrame) -> pd.Series:
    """
    Indice di scorrevolezza 0–100.
    Alto quando:
      - T_surf vicino a 0 (ma non troppo bagnato)
      - LWF medio (0.3–0.6)
      - vento moderato-basso
      - nuvolosità medio/alta (riduce raffreddamento radiativo)
    Penalità con freddo estremo, vento forte, LWF troppo alto o troppo basso.
    """
    t = df["T_surf"].clip(-15, 2)
    lwf = df["LWF"].clip(0,1)
    wind = df["wind"].clip(0,12)
    cloud = df["cloud"].clip(0,1)

    score = 0
    # picco a -1 .. 0
    score += (1 - ((t + 1.0).abs()/6.0).clip(0,1)) * 40
    # LWF “dolce” 0.3–0.6
    score += (1 - ((lwf - 0.45).abs()/0.45).clip(0,1)) * 35
    # vento: meno è meglio
    score += (1 - (wind/12.0)) * 15
    # cloud alto riduce freddo radiante notturno
    score += (cloud) * 10

    return score.clip(0,100)

def reliability(df: pd.DataFrame) -> pd.Series:
    """
    Affidabilità (%) semplice:
      - scende con l’orizzonte (più lontano nel tempo → meno affidabile)
      - penalità con variabilità alta di prp e vento nelle ultime ore
    """
    t = pd.to_datetime(df["time"])
    hrs = (t - t.min()).dt.total_seconds()/3600.0
    horizon_penalty = (1 - (hrs/168)).clip(0.35, 1.0)  # minimo 35%

    # variabilità locale (finestre 6h)
    prp_var = df["prp_mmph"].rolling(6, min_periods=1).std().fillna(0)
    wind_var = df["wind"].rolling(6, min_periods=1).std().fillna(0)

    var_penalty = (1 - (prp_var.clip(0,2)/2)*0.3 - (wind_var.clip(0,4)/4)*0.3).clip(0.4,1.0)

    rel = (horizon_penalty * var_penalty) * 100
    return rel.clip(35, 95)

# ====================== WAX BRANDS ======================
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]

BRANDS = [
    ("Swix",      "#ef4444", SWIX),
    ("Toko",      "#f59e0b", TOKO),
    ("Vola",      "#3b82f6", VOLA),
    ("Rode",      "#22c55e", RODE),
    ("Holmenkol", "#06b6d4", HOLM),
    ("Maplus",    "#f97316", MAPL),
    ("Start",     "#eab308", START),
    ("Skigo",     "#a855f7", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# Struttura “nome” (niente immagini)
def structure_name_for_t(t_surf: float) -> str:
    if t_surf <= -10:    return "Linear fine (freddo/secco)"
    if t_surf <= -3:     return "Cross hatch / Wave (universale freddo)"
    return "Diagonal / V (umido/caldo)"

# ====================== UI – INPUTS ======================
with st.container():
    cA, cB = st.columns([1,2])
    with cA:
        country_label = st.selectbox("Paese per la ricerca", [c for c,_ in COUNTRY_OPTIONS], index=0)
        cc_filter = dict(COUNTRY_OPTIONS)[country_label]
    with cB:
        search_fn = nominatim_search_factory(cc_filter)
        selected = st_searchbox(
            search_fn,
            key="place",
            placeholder="Scrivi e scegli… (es. Champoluc, Plateau Rosa, Sestriere)",
            clear_on_submit=False,
            default=None
        )

# decode selection -> lat,lon,label
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        st.session_state.sel_lat   = info["lat"]
        st.session_state.sel_lon   = info["lon"]
        st.session_state.sel_label = info["label"]

lat   = st.session_state.get("sel_lat", 45.831)
lon   = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "🇮🇹  Champoluc — IT")

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {label}{alt_txt}")

c1,c2,c3 = st.columns([1,1,2])
with c1:
    tzname = "Europe/Rome"  # niente toggle, fisso EU/IT – (si può cambiare se serve)
with c2:
    sel_day = st.date_input("Giorno", value=date.today(), min_value=date.today(), max_value=date.today()+dt.timedelta(days=6))
with c3:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

st.markdown("### Finestre orarie A · B · C")
cA,cB,cC = st.columns(3)
with cA:
    A_start = st.time_input("Inizio A", time(9, 0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11, 0), key="A_e")
with cB:
    B_start = st.time_input("Inizio B", time(11, 0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13, 0), key="B_e")
with cC:
    C_start = st.time_input("Inizio C", time(13, 0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16, 0), key="C_e")

# ====================== RUN ======================
st.markdown("### Meteo & raccomandazioni")
go = st.button("Scarica e calcola per la località selezionata", type="primary")

if go:
    try:
        _ = try_noaa_enrichment(lat, lon)  # opzionale (silenzioso)
        js = fetch_open_meteo(lat, lon, tzname)
        src = build_df(js, hours, tzname)
        res = compute_snow_layers(src, dt_hours=1.0)

        # classificazioni e indici
        res["condizione"] = classify_snow(res)
        res["scorrevolezza"] = glide_index(res).round(0)
        res["affidabilita_%"] = reliability(res).round(0)

        # ---- filtro per giorno scelto
        res["dt"] = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
        day_mask = res["dt"].dt.date == sel_day
        day_df = res[day_mask].copy()
        if day_df.empty:
            st.warning("Nessun dato per il giorno selezionato nell’orizzonte richiesto; mostro le prime ore disponibili.")
            day_df = res.head(24).copy()

        # ---- tabella “pulita”
        show = day_df.copy()
        show["Ora"] = show["dt"].dt.strftime("%a %H:%M")
        show = show[[
            "Ora","T2m","td","RH","wind","cloud","prp_mmph","prp_type","snow_mmph","rain_mmph",
            "T_surf","T_top5","LWF","condizione","scorrevolezza","affidabilita_%"
        ]].rename(columns={
            "T2m":"T aria (°C)", "td":"Td (°C)", "RH":"UR (%)",
            "wind":"Vento (m/s)", "cloud":"Nuvolosità (0-1)",
            "prp_mmph":"Prp (mm/h)", "prp_type":"Tipo prp",
            "snow_mmph":"Neve (mm/h)", "rain_mmph":"Pioggia (mm/h)",
            "T_surf":"T neve superficie (°C)", "T_top5":"T neve 0-5mm (°C)",
            "LWF":"H2O liquida (0-1)"
        })
        st.markdown("#### Dati orari (giorno selezionato)")
        st.dataframe(show.style.format({
            "T aria (°C)":"{:.1f}", "Td (°C)":"{:.1f}", "UR (%)":"{:.0f}",
            "Vento (m/s)":"{:.1f}", "Nuvolosità (0-1)":"{:.2f}",
            "Prp (mm/h)":"{:.2f}", "Neve (mm/h)":"{:.2f}", "Pioggia (mm/h)":"{:.2f}",
            "T neve superficie (°C)":"{:.1f}", "T neve 0-5mm (°C)":"{:.1f}",
            "H2O liquida (0-1)":"{:.2f}", "scorrevolezza":"{:.0f}", "affidabilita_%":"{:.0f}"
        }), use_container_width=True)

        # ---- grafici compatti
        t = day_df["dt"]
        fig1 = plt.figure(figsize=(7.5,2.8), dpi=140)
        plt.plot(t,day_df["T2m"],label="T aria")
        plt.plot(t,day_df["T_surf"],label="T neve superf.")
        plt.plot(t,day_df["T_top5"],label="T neve 0–5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(7.5,2.6), dpi=140)
        plt.bar(t, day_df["prp_mmph"])
        plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        st.download_button("Scarica CSV (tutte le ore, 7 giorni)",
                           data=res.drop(columns=["dt"]).to_csv(index=False),
                           file_name="telemark_forecast_with_snow.csv",
                           mime="text/csv")

        # ---- blocchi A/B/C sul giorno scelto
        def window_slice(D: pd.DataFrame, s: time, e: time):
            W = D[(D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
            return W if not W.empty else D.head(6)

        st.markdown("### Risultati per blocchi A · B · C")
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}

        for L,(s,e) in blocks.items():
            W = window_slice(day_df, s, e)
            t_med = float(W["T_surf"].mean())
            gi = float(W["scorrevolezza"].mean())
            rel = float(W["affidabilita_%"].mean())
            cond = W["condizione"].mode().iloc[0] if not W["condizione"].empty else "-"

            # banner
            tone = "good" if gi>=66 else ("mid" if gi>=40 else "bad")
            st.markdown(f"#### Blocco {L} — {s.strftime('%H:%M')} → {e.strftime('%H:%M')}")
            st.markdown(
                f"<div class='banner {tone}'>"
                f"<div class='badge'>Condizione: <b>{cond}</b></div>"
                f"<div class='badge'>T neve media: <b>{t_med:.1f}°C</b></div>"
                f"<div class='badge'>Indice di scorrevolezza: <b>{gi:.0f}/100</b></div>"
                f"<div class='badge'>Affidabilità: <b>{rel:.0f}%</b></div>"
                f"</div>", unsafe_allow_html=True
            )

            # wax (8 marchi)
            st.markdown("**Sciolina consigliata (per T_surf media del blocco):**")
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(name,col,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(
                    f"<div class='brand'><div style='width:10px;height:10px;border-radius:3px;background:{col}'></div>"
                    f"<div><div class='muted' style='font-size:.8rem'>{name}</div>"
                    f"<div style='font-weight:800;color:#e5faff'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )
            for i,(name,col,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><div style='width:10px;height:10px;border-radius:3px;background:{col}'></div>"
                    f"<div><div class='muted' style='font-size:.8rem'>{name}</div>"
                    f"<div style='font-weight:800;color:#e5faff'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )

            # struttura – solo nome, niente immagini
            st.markdown(f"**Struttura consigliata:** {structure_name_for_t(t_med)}")

            # angoli per specialità (SIDE/BASE) – come prima
            def tune_for(t_surf, discipline):
                if t_surf <= -10:
                    base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
                elif t_surf <= -3:
                    base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
                else:
                    base = 0.8 if t_surf <= 0.5 else 1.0
                    side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
                return side_map.get(discipline, 88.0), base

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = tune_for(t_med, d)
                rows.append([d, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
