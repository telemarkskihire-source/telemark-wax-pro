# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, math, base64
from datetime import time, date, datetime
from streamlit_searchbox import st_searchbox

# ================== PAGE / THEME (dark) ==================
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#e5e7eb"   # light text
MUTED   = "#9ca3af"   # secondary
CARD    = "#111827"   # slate-900
BG      = "#0b1220"   # dark gradient top

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 600px at 10% -10%, #0e1a33 0%, {BG} 38%, #0a0f1a 100%); }}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4,h5,label,span,div,p {{ color:{ACCENT}; }}
.small {{ color:{MUTED}; font-size:.85rem }}
.card {{ background:{CARD}; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:14px; box-shadow:0 10px 24px rgba(0,0,0,.35); }}
.badge {{ display:inline-block; border:1px solid {PRIMARY}66; color:#d1fbff; background:{PRIMARY}22; padding:.25rem .5rem; border-radius:999px; font-size:.78rem; }}
.kpi {{ display:flex; gap:10px; align-items:center; background:rgba(16,191,207,.08); border:1px dashed rgba(16,191,207,.45);
       padding:.5rem .75rem; border-radius:12px; }}
.kpi .lab {{ color:#8fd9e1; font-size:.78rem }}
.kpi .val {{ font-weight:800; }}
.banner {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:.6rem .8rem; }}
.brand {{ display:flex;align-items:center;gap:.6rem; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07);
         border-radius:12px; padding:.4rem .6rem; }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.08); margin: .6rem 0; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")

# ================== HELPERS ==================
def flag(cc: str) -> str:
    try:
        cc = cc.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(addr: dict, fallback: str) -> str:
    """Short, human label: place, region — CC"""
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    return (", ".join(parts) + (f" — {cc}" if cc else "")).strip()

def nominatim_search(q: str):
    if not q or len(q) < 2: return []
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": q, "format": "json", "limit": 12, "addressdetails": 1},
                         headers={"User-Agent": "telemark-wax-pro/1.0"}, timeout=8)
        r.raise_for_status()
        out = []; st.session_state._opt = {}
        for it in r.json():
            addr = it.get("address", {}) or {}
            lat = float(it.get("lat", 0)); lon = float(it.get("lon", 0))
            label = f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._opt[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

def get_elev(lat: float, lon: float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": lat, "longitude": lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if js and js.get("elevation"): return float(js["elevation"][0])
    except Exception:
        pass
    return None

def om_forecast(lat, lon, tzname="Europe/Rome"):
    """Open-Meteo hourly with local timezone; NOTE: times arrive LOCAL (no tz info), so we keep them naive."""
    params = dict(
        latitude=lat, longitude=lon, timezone=tzname, forecast_days=7,
        hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover," \
               "windspeed_10m,weathercode,is_day"
    )
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def precip_type(row):
    prp, rain, snow = row["precipitation"], row.get("rain",0.0), row.get("snowfall",0.0)
    if pd.isna(prp) or prp <= 0: return "none"
    if rain>0 and snow>0: return "mixed"
    if snow>0 and rain==0: return "snow"
    if rain>0 and snow==0: return "rain"
    # fallback by weathercode families
    try:
        code = int(row.get("weathercode",0))
    except: code = 0
    if code in {71,73,75,77,85,86}: return "snow"
    if code in {51,53,55,61,63,65,80,81,82}: return "rain"
    return "mixed"

def build_df(js, horizon_hours: int):
    H = pd.DataFrame(js["hourly"])
    H["time"] = pd.to_datetime(H["time"])  # local naive datetime by tz parameter
    now_local = pd.Timestamp.now().floor("H")
    H = H[H["time"] >= now_local].head(horizon_hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = H["time"]
    out["T2m"]  = H["temperature_2m"].astype(float)
    out["rh"]   = H["relative_humidity_2m"].astype(float)  # %
    out["td"]   = H["dew_point_2m"].astype(float)
    out["cloud"] = (H["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (H["windspeed_10m"].astype(float)/3.6).clip(lower=0)  # m/s
    out["is_day"] = H["is_day"].astype(int)
    out["precipitation"] = H["precipitation"].astype(float)
    out["rain"] = H.get("rain", 0.0)
    out["snowfall"] = H.get("snowfall", 0.0)
    out["weathercode"] = H.get("weathercode", 0)
    out["prp_type"] = out.apply(precip_type, axis=1)
    return out

# ---------- Snow-surface & top-5mm model ----------
def snow_model(df: pd.DataFrame, dt_hours: float = 1.0) -> pd.DataFrame:
    """Heuristic energy-balance style model producing T_surf & T_top5."""
    D = df.copy()
    # 1) 'wet' flag (strong clamp to 0°C)
    rain = D["prp_type"].isin(["rain","mixed"])
    snow = D["prp_type"].eq("snow")
    sun  = D["is_day"].eq(1)
    tw   = (D["T2m"] + D["td"]) / 2.0
    wet  = (rain | (D["T2m"]>0) | (sun & (D["cloud"]<0.35) & (D["T2m"]>=-3))
            | (snow & ((D["T2m"]>=-1) | tw.ge(-0.5))))
    T_surf = pd.Series(index=D.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - D["cloud"]).clip(0,1); windc = D["wind"].clip(upper=7.0)
    # radiative & convective cooling heuristic [°C]
    drad = (1.8 + 3.2*clear - 0.35*windc).clip(0.4, 5.0)
    T_surf.loc[dry] = D.loc[dry,"T2m"] - drad.loc[dry]

    # Sunny-but-cold clamp (avoid unrealistically cold surface in sun)
    sunny_cold = sun & dry & D["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (D["T2m"] + 0.6*(1.0 - D["cloud"]))[sunny_cold],
        pd.Series(-0.7, index=D.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # 2) top 5 mm relax to surface with weather-dependent time constants
    tau = pd.Series(6.0, index=D.index, dtype=float)
    tau.loc[rain | snow | (D["wind"]>=6)] = 3.0
    tau.loc[(~sun) & (D["wind"]<2) & (D["cloud"]<0.3)] = 9.0
    alpha = pd.Series(1.0 - math.e**(-dt_hours / tau), index=D.index)

    T_top5 = pd.Series(index=D.index, dtype=float)
    if len(D) > 0:
        T_top5.iloc[0] = min(D["T2m"].iloc[0], 0.0)  # initial state
        for i in range(1, len(D)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    D["T_surf"] = T_surf
    D["T_top5"] = T_top5
    return D

# ---------- Qualitative snow state + reliability ----------
def snow_condition(row) -> str:
    t = row["T_surf"]; prp = row["prp_type"]; rh = row["rh"]; wind = row["wind"]; snowmm = row.get("snowfall",0.0)
    if prp=="rain" or t>=-0.2: return "bagnata"
    if prp=="mixed": return "umida"
    if prp=="snow" and snowmm>=0.5:
        return "neve nuova"
    if t<=-8: return "fredda/secca"
    if wind>=8 and t<=-3: return "ventata/granulosa"
    return "trasformata"

def reliability_slice(df: pd.DataFrame) -> int:
    """0–100: nearer term & simpler weather ⇒ higher confidence."""
    if df.empty: return 0
    # penalties: far-in-time, high wind, high precip, convective sky
    horizon_pen = max(0, 100 - len(df)*0.5)                  # ~0.5pt per ora
    wind_pen    = min(25, df["wind"].mean()*2.0)
    prp_pen     = min(20, df["precipitation"].mean()*6.0)
    sky_bonus   = (1.0 - df["cloud"].mean()) * 10.0
    raw = 75 - wind_pen - prp_pen + sky_bonus - (100 - horizon_pen)
    return int(max(10, min(95, 60 + raw)))

def glide_index(df: pd.DataFrame) -> int:
    """Indice di scorrevolezza 0–100 (alto = scivola bene)"""
    if df.empty: return 0
    # best around -1.0…0.0 with some moisture and low wind
    t = df["T_surf"].mean()
    rh = df["rh"].mean()/100
    wind = df["wind"].mean()
    near0 = max(0, 1 - abs(t + 0.7)/3.0)         # peak near -0.7°C
    moist = min(1.0, 0.3 + 0.7*rh)               # prefer humid air
    calm  = max(0, 1 - wind/10.0)
    score = 100 * (0.5*near0 + 0.35*moist + 0.15*calm)
    return int(max(5, min(98, score)))

# ---------- Window slice for a chosen date ----------
def slice_day(res: pd.DataFrame, sel_date: date, t0: time, t1: time) -> pd.DataFrame:
    D = res.copy()
    D["date"] = D["time"].dt.date
    D["clock"] = D["time"].dt.time
    S = D[(D["date"]==sel_date) & (D["clock"]>=t0) & (D["clock"]<=t1)]
    return S if not S.empty else D.head(6)

# ================== WAX BRANDS (8) ==================
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Universal Cold",-12,-6),("Universal Medium",-7,-2),("Universal Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [
    ("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),
    ("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)
]
def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ================== UI – 1) LOCATION ==================
st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi e premi Invio… (es. Champoluc, Plateau Rosa, Cervinia)",
    clear_on_submit=False,
    default=None,
)

if selected and "|||" in selected and "_opt" in st.session_state:
    lat, lon, label = st.session_state._opt[selected]
    st.session_state.lat, st.session_state.lon, st.session_state.label = lat, lon, label

lat  = st.session_state.get("lat", 45.831)
lon  = st.session_state.get("lon", 7.730)
label= st.session_state.get("label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
elev = get_elev(lat, lon)
st.markdown(f"<div class='kpi'><span class='lab'>Località</span>"
            f"<span class='val'>{label}</span>"
            f"<span class='lab'>Altitudine</span><span class='val'>{int(elev)} m</span></div>", unsafe_allow_html=True)

# Allow choosing which date to apply A/B/C windows
st.subheader("2) Finestre orarie A · B · C")
colD, colH = st.columns([1,2])
with colD:
    sel_day = st.date_input("Giorno", value=date.today(),
                            help="Puoi scegliere giorni successivi per fissare le finestre A/B/C")
with colH:
    horizon = st.slider("Ore previsione (orizzonte)", 12, 168, 72, 12)

c1,c2,c3 = st.columns(3)
with c1:
    A_s = st.time_input("Inizio A", time(9,0));   A_e = st.time_input("Fine A", time(11,0))
with c2:
    B_s = st.time_input("Inizio B", time(11,0));  B_e = st.time_input("Fine B", time(13,0))
with c3:
    C_s = st.time_input("Inizio C", time(13,0));  C_e = st.time_input("Fine C", time(16,0))

# ================== 3) FETCH & CALC ==================
st.subheader("3) Dati meteo & calcolo")
if st.button("Scarica/aggiorna previsioni", type="primary"):
    try:
        js = om_forecast(lat, lon, "Europe/Rome")
        base = build_df(js, horizon)
        res  = snow_model(base, dt_hours=1.0)

        # --- tidy table (più chiara) ---
        tidy = res[["time","T2m","td","rh","cloud","wind","precipitation","prp_type","T_surf","T_top5"]].copy()
        tidy.rename(columns={
            "time":"Ora locale", "T2m":"Aria (°C)", "td":"Dew (°C)", "rh":"UR (%)",
            "cloud":"Nuvolosità (0-1)", "wind":"Vento (m/s)", "precipitation":"Prp (mm/h)",
            "prp_type":"Tipo prp", "T_surf":"Neve superficie (°C)", "T_top5":"Neve top 5mm (°C)"
        }, inplace=True)
        st.dataframe(tidy, use_container_width=True)

        # --- Chart rapide ---
        import matplotlib.pyplot as plt
        t = res["time"]
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria")
        plt.plot(t,res["T_surf"],label="T neve (surf)")
        plt.plot(t,res["T_top5"],label="T neve (top5mm)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        # ================== Blocchi A/B/C ==================
        for L,(s,e) in {"A":(A_s,A_e),"B":(B_s,B_e),"C":(C_s,C_e)}.items():
            st.markdown(f"---\n### Blocco {L}")
            W = slice_day(res, sel_day, s, e)
            t_med  = float(W["T_surf"].mean())
            cond   = snow_condition(W.iloc[0]) if not W.empty else "n/d"
            aff    = reliability_slice(W)
            glide  = glide_index(W)

            st.markdown(
                f"<div class='banner'>"
                f"**T_neve media {L}: {t_med:.1f}°C** · "
                f"**Condizione:** {cond} · "
                f"**Affidabilità:** {aff}% · "
                f"**Indice di scorrevolezza:** {glide}/100"
                f"</div>", unsafe_allow_html=True
            )

            # Scioline – 8 marchi
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(b,bands) in enumerate(BRANDS[:4]):
                rec = pick_wax(bands, t_med); cols1[i].markdown(f"<div class='brand'><b>{b}</b> · {rec}</div>", unsafe_allow_html=True)
            for i,(b,bands) in enumerate(BRANDS[4:]):
                rec = pick_wax(bands, t_med); cols2[i].markdown(f"<div class='brand'><b>{b}</b> · {rec}</div>", unsafe_allow_html=True)

            # Strutture & angoli – tabella 4 specialità (solo nomi struttura, niente immagini)
            def tune_for(t_surf, d):
                if t_surf <= -10:
                    fam = "Lineare fine (freddo/secco)"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
                elif t_surf <= -3:
                    fam = "Incrociata / onda leggera (universale)"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
                else:
                    fam = "Scarico diagonale / V (umido/caldo)"; base = 0.8 if t_surf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                return fam, side, base

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","SIDE (°)","BASE (°)"]))

        # CSV download
        st.download_button("Scarica CSV calcolo", data=res.to_csv(index=False),
                           file_name="telemark_wax_calc.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
