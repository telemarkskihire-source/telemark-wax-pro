# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time, date, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ======================= THEME / UI =======================
PRIMARY = "#10bfcf"   # turchese Telemark
BG      = "#0b1220"   # sfondo scuro
PANEL   = "#111827"   # card scura
TEXT    = "#e5e7eb"   # testo
MUTED   = "#93a4c0"   # testo secondario
GOOD    = "#22c55e"
WARN    = "#f59e0b"
BAD     = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")

st.markdown(f"""
<style>
:root {{
  --primary:{PRIMARY};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% -10%, #182339 0%, {BG} 45%, #0a0f1c 100%);
}}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5,h6, label, p, span, div {{ color:{TEXT}; }}
hr {{ border:none; border-top:1px solid rgba(148,163,184,.15); margin: .8rem 0; }}
.card {{
  background:{PANEL}; border:1px solid rgba(148,163,184,.18);
  border-radius:16px; padding:16px; box-shadow: 0 12px 30px rgba(0,0,0,.35);
}}
.kpi {{
  display:flex; gap:.5rem; align-items:center;
  padding:.45rem .7rem; border-radius:999px; font-size:.85rem; font-weight:700;
  border:1px dashed rgba(148,163,184,.35); background:rgba(148,163,184,.06);
}}
.chip {{
  display:inline-flex; align-items:center; gap:.5rem;
  padding:.35rem .6rem; border-radius:999px; font-weight:700; font-size:.84rem;
  border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.04);
}}
.badge {{
  display:inline-block; padding:.25rem .55rem; border-radius:8px;
  background:rgba(16,191,207,.12); border:1px solid rgba(16,191,207,.5);
  color:#a5f3fc; font-size:.78rem; font-weight:700;
}}
.brand {{
  display:flex; align-items:center; gap:.6rem; padding:.55rem .7rem; border-radius:12px;
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.09);
}}
.brand img {{ height:22px; }}
.table-box table {{ color:{TEXT}; }}
.small {{ color:{MUTED}; font-size:.85rem }}
h1.title {{ letter-spacing:.4px; }}
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='title'>Telemark · Pro Wax & Tune</h1>", unsafe_allow_html=True)

# ======================= HELPERS =======================
def flag(cc:str)->str:
    try:
        cc = cc.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    if cc: s += f" — {cc}"
    return s

# ---- Geosearch (Nominatim) with optional country filter ----
def nominatim_search(q:str):
    if not q or len(q)<2: 
        return []
    try:
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        cc = st.session_state.get("country_filter","")
        if cc and cc!="*": params["countrycodes"] = cc.lower()
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent":"telemark-wax-pro/1.1"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._geo = {}
        out = []
        for item in r.json():
            addr = item.get("address",{}) or {}
            short = concise_label(addr, item.get("display_name",""))
            lab = f"{flag(addr.get('country_code',''))}  {short}"
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{lab}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo[key] = (lat,lon,lab,addr)
            out.append(key)
        return out
    except:
        return []

def get_elev(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if js and js.get("elevation"): return float(js["elevation"][0])
    except:
        pass
    return None

# ---- Forecast fetch ----
def fetch_open_meteo(lat, lon, tzname="Europe/Rome", ndays=7):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly": ",".join([
                "temperature_2m","dew_point_2m","relative_humidity_2m",
                "precipitation","rain","snowfall","cloudcover",
                "windspeed_10m","is_day","weathercode"
            ]),
            "forecast_days": ndays
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

# ---- DataFrame builder ----
def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation
        rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    out = pd.DataFrame()
    out["time"]  = df["time"]
    out["T2m"]   = df["temperature_2m"].astype(float)
    out["td"]    = df["dew_point_2m"].astype(float)
    out["RH"]    = df["relative_humidity_2m"].astype(float)  # %
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0, upper=20) # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["rain"] = df["rain"].astype(float)
    out["snow"] = df["snowfall"].astype(float)
    return out

# ---- Wet-bulb (Stull approx) ----
def wet_bulb_stull(T, RH):
    # T in °C, RH in %
    # Guard rails on RH and T
    T = T.clip(-50, 50); RH = RH.clip(1, 100)
    # vectorized formula
    a = (T * (pd.Series(RH).pipe(lambda r: (0.151977*(r+8.313659)).pow(0.5)).pipe(pd.Series).apply(math.atan)))
    b = pd.Series(T + RH).apply(math.atan)
    c = pd.Series(RH - 1.676331).apply(math.atan)
    d = 0.00391838 * (pd.Series(RH).pow(1.5)) * pd.Series(RH*0+1).apply(lambda _: math.atan(0.023101*RH))
    # The above attempt is messy in pandas; do a safe loop instead:
    TW = []
    for t,r in zip(T.tolist(), RH.tolist()):
        TW.append(
            t*math.atan(0.151977*math.sqrt(r+8.313659))
            + math.atan(t+r)
            - math.atan(r-1.676331)
            + 0.00391838*(r**1.5)*math.atan(0.023101*r)
            - 4.686035
        )
    return pd.Series(TW, index=T.index)

# ---- Snow temperature / physics-inspired heuristic ----
def compute_snow_temperature(df):
    d = df.copy()
    # Base radiative/convective offset: stronger at night & clear skies
    night = d["sunup"]==0
    clear = 1.0 - d["cloud"]
    # cooling factor (°C) ~ radiative + a bit of convective (wind)
    cool = (1.0 + 3.2*clear) * (night.astype(float)) + (0.25*clear)*(~night).astype(float)
    cool += 0.12 * d["wind"].clip(upper=8)  # wind helps cooling a bit

    # starting "candidate" surface temperature (without melting clamp)
    T_candidate = d["T2m"] - cool

    # wet forcing toward 0°C if conditions allow melting
    TW = wet_bulb_stull(d["T2m"], d["RH"])
    wet_mask = (
        (d["T2m"] >= -0.5) |
        (d["rain"] > 0.05) |
        (d["prp_type"].isin(["rain","mixed"])) |
        (TW >= -0.2)
    )
    # If snowing but air is mildly cold, the surface hovers near 0 to -1 depending on TW
    snow_mask = (d["snow"] > 0.05) | (d["prp_type"]=="snow")

    T_surf = T_candidate.copy()
    # clamp: snow surface cannot exceed 0 (unless we allow slush film = 0)
    T_surf = T_surf.clip(upper=0.0)

    # Bring wet conditions up toward 0°C (exponential blend)
    T_surf[wet_mask] = 0.0*0.7 + T_surf[wet_mask]*0.3
    # During snowfall with mild temps (TW>-2), pull toward -0.8..0 depending on TW
    if (~TW.isna()).any():
        adj = (-0.8 + (TW.clip(-4,0)/4.0)*0.8)  # TW=-4→-0.8 ; TW=0→0.0
        T_surf[snow_mask] = (0.6*adj[snow_mask] + 0.4*T_surf[snow_mask]).clip(upper=0.0)

    # Smooth over time (top ~5 mm response)
    T_top5 = pd.Series(index=d.index, dtype=float)
    tau = pd.Series(6.0, index=d.index)  # hours
    tau.loc[wet_mask | snow_mask | (d["wind"]>=6)] = 3.0
    alpha = 1.0 - (pd.np.exp(-1.0 / tau))  # dt=1h
    if len(d)>0:
        T_top5.iloc[0] = min(d["T2m"].iloc[0], 0.0)
        for i in range(1, len(d)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    d["T_wetbulb"] = TW
    d["T_surf"] = T_surf
    d["T_top5"] = T_top5
    return d

# ---- Window slice by selected date and times ----
def window_slice(res, tzname, s, e, the_date):
    tloc = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = tloc
    W = D[(D["dt"].dt.date == the_date) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W

# ---- Classification / banner ----
def classify_block(W: pd.DataFrame):
    if W.empty:
        return "Dati insufficienti", 0.0, "—", "—"
    t = float(W["T_surf"].mean())
    rh = float(W["RH"].mean())
    snow = float(W["snow"].sum())
    rain = float(W["rain"].sum())
    wind = float(W["wind"].mean())
    cloud = float(W["cloud"].mean())
    # Consistenza neve
    if t <= -8:
        cond = "Polverosa molto fredda"
        structure = "Lineare fine (S1)"
        glide = 62
    elif t <= -3:
        cond = "Secca / compatta fredda"
        structure = "Universale incrociata (S1)"
        glide = 78
    elif t <= -1:
        cond = "Trasformata / primaverile fredda"
        structure = "Wave leggera (S2)"
        glide = 82
    elif t <= 0.1:
        if rh>85 or rain>0:
            cond = "Bagnata / primaverile"
            structure = "Scarico diagonale o Thumb (S2)"
            glide = 68
        else:
            cond = "Umida prossima a 0°C"
            structure = "Wave / Thumb (S2)"
            glide = 74
    else:
        cond = "Slush caldo"
        structure = "Scarico diagonale marcato (S2)"
        glide = 58

    # Aggiustamenti
    if snow>1.0 and t>-4:
        cond += " + Neve nuova"
        glide -= 4
    if wind>10 and t<=-4:
        cond += " + Vento (windbuff)"
        glide -= 2
    glide = int(max(35, min(92, glide)))

    # Affidabilità (orizzonte, coerenza, nuvolosità come proxy incertezza)
    horizon_h = len(W)
    variability = float(W["T_surf"].std(skipna=True) or 0.0)
    base_rel = 88 if horizon_h<=4 else 80 if horizon_h<=8 else 72
    base_rel -= int(variability*4)
    base_rel -= int((1.0-cloud)*6)  # cielo variabile peggiora un po'
    reliability = int(max(35, min(95, base_rel)))

    return cond, t, structure, reliability, glide

# ---- Wax bands / brands ----
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRAND_BANDS = [
    ("Swix"     , "#ef4444", SWIX),
    ("Toko"     , "#f59e0b", TOKO),
    ("Vola"     , "#3b82f6", VOLA),
    ("Rode"     , "#22c55e", RODE),
    ("Holmenkol", "#06b6d4", HOLM),
    ("Maplus"   , "#f97316", MAPL),
    ("Start"    , "#eab308", START),
    ("Skigo"    , "#a855f7", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='140' height='30'><rect width='140' height='30' rx='6' fill='{color}'/><text x='12' y='20' font-size='14' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ======================= CONTROLS =======================
with st.container():
    cA, cB = st.columns([1.1, 2.2])
    with cA:
        st.markdown("#### 1) Località")
        country = st.selectbox("Paese (ISO-2, opzionale)", ["*", "IT","FR","CH","AT","DE","NO","SE","FI","US","CA"], index=1)
        st.session_state["country_filter"] = country
        selected = st_searchbox(
            nominatim_search,
            key="place",
            placeholder="Digita e scegli… (es. Champoluc, Plateau Rosa)",
            clear_on_submit=False,
            default=None
        )
        # decode selection
        if selected and "|||" in selected and "_geo" in st.session_state:
            lat, lon, label, addr = st.session_state._geo.get(selected, (45.831,7.730,"Champoluc — IT",{}))
            st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat,lon,label
    with cB:
        st.markdown("#### 2) Data & Finestre")
        sel_date = st.date_input("Giorno", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))
        c1,c2,c3 = st.columns(3)
        with c1:
            A_start = st.time_input("Inizio A", time(9, 0), key="A_s"); A_end = st.time_input("Fine A", time(11, 0), key="A_e")
        with c2:
            B_start = st.time_input("Inizio B", time(11, 0), key="B_s"); B_end = st.time_input("Fine B", time(13, 0), key="B_e")
        with c3:
            C_start = st.time_input("Inizio C", time(13, 0), key="C_s"); C_end = st.time_input("Fine C", time(16, 0), key="C_e")

# defaults if nothing yet
lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "🇮🇹  Champoluc — IT")
elev = get_elev(lat, lon)
st.markdown(f"<div class='chip'>📍 {label} · Altitudine: <b>{int(elev) if elev is not None else '—'}</b> m</div>", unsafe_allow_html=True)

# ======================= LOAD & COMPUTE =======================
st.markdown("### 3) Meteo & Analisi neve")
hours_horizon = st.slider("Ore previsione (da ora)", 12, 168, 72, 12, help="Orizzonte massimo caricato (viene poi filtrato per giorno e fasce orarie).")

if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js)
        # taglia a orizzonte richiesto
        now0 = pd.Timestamp.now().floor("H")
        src = src[src["time"] >= now0].head(hours_horizon).reset_index(drop=True)
        res = compute_snow_temperature(src)

        st.success("Dati caricati.")
        # tabella snella
        show = res[["time","T2m","td","RH","T_wetbulb","T_surf","T_top5","prp_mmph","prp_type","snow","rain","cloud","wind","sunup"]].copy()
        show.columns = ["Ora","T aria","T rugiada","UR %","T wet-bulb","T neve (superf.)","T neve (5mm)","Prec mm/h","Tipo prc","Neve mm/h","Pioggia mm/h","Nuvole","Vento m/s","Giorno"]
        st.markdown("<div class='card table-box'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, height=320)
        st.markdown("</div>", unsafe_allow_html=True)

        # grafici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(figsize=(7.5,2.8))
        plt.plot(t,res["T2m"],label="T aria")
        plt.plot(t,res["T_surf"],label="T neve (superf.)")
        plt.plot(t,res["T_top5"],label="T neve (5mm)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(7.5,2.2))
        plt.bar(t,res["prp_mmph"])
        plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        st.download_button("Scarica CSV analisi", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # Blocchi A/B/C sul giorno scelto
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L} — {sel_date.strftime('%d %b %Y')}")
            W = window_slice(res, "Europe/Rome", s, e, sel_date)
            if W is None or W.empty:
                st.info("Nessun dato in questa finestra.")
                continue

            cond, tmean, structure, reliability, glide = classify_block(W)
            # banner sintetico
            color = GOOD if reliability>=80 else WARN if reliability>=60 else BAD
            st.markdown(
                f"<div class='card' style='display:flex;gap:12px;align-items:center;'>"
                f"<div class='kpi' style='border-color:{color};'><span>🏷️</span> {cond}</div>"
                f"<div class='chip'>T neve media: <b>{tmean:.1f}°C</b></div>"
                f"<div class='chip'>Struttura consigliata: <b>{structure}</b></div>"
                f"<div class='chip' style='border-color:{color};'>Affidabilità: <b style='color:{color}'>{reliability}%</b></div>"
                f"<div class='chip'>Indice di scorrevolezza: <b>{glide}/100</b></div>"
                f"</div>", unsafe_allow_html=True
            )

            # Wax cards (8 brand)
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, tmean)
                cols1[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div class='small'>{brand}</div><div style='font-weight:800'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, tmean)
                cols2[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div class='small'>{brand}</div><div style='font-weight:800'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )

            # Discipline table (angoli + struttura nominale)
            def tune_for(t_surf, discipline):
                if t_surf <= -10:
                    fam = "Lineare fine (S1)"
                    base = 0.5; side_map = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}
                elif t_surf <= -3:
                    fam = "Incrociata leggera / Wave leggera (S1)"
                    base = 0.7; side_map = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}
                else:
                    fam = "Scarico diagonale / Thumb (S2)"
                    base = 0.8 if t_surf<=0.5 else 1.0
                    side_map = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}
                return fam, side_map.get(discipline,88.0), base

            rows=[]
            for dsc in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(tmean, dsc)
                rows.append([dsc, fam, f"{side:.1f}°", f"{base:.1f}°"])
            df_tune = pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"])
            st.table(df_tune)

    except Exception as e:
        st.error(f"Errore: {e}")
