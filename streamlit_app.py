# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ========================= THEME (DARK + VIVID) =========================
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#22d3ee"   # vivid cyan
GOOD    = "#34d399"   # green
WARN    = "#f59e0b"   # amber
BAD     = "#ef4444"   # red
BG      = "#0b1220"   # deep night
CARD    = "#0f172a"
TEXT    = "#e5e7eb"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg: {BG}; --card: {CARD}; --txt: {TEXT};
  --primary: {PRIMARY}; --accent: {ACCENT}; --good:{GOOD}; --warn:{WARN}; --bad:{BAD};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% 0%, #0c1a2f 0%, var(--bg) 50%), var(--bg);
}}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color: var(--txt); }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.08); margin: 1rem 0; }}
.card {{
  background: var(--card);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 12px 28px rgba(0,0,0,.35);
}}
.badge {{
  display:inline-flex; align-items:center; gap:.45rem;
  background: rgba(16,191,207,.12);
  color: #a5f3fc; border: 1px solid rgba(34,211,238,.35);
  padding: .28rem .6rem; border-radius: 999px; font-size: .78rem; letter-spacing:.2px;
}}
.kpi {{
  display:flex; gap:10px; align-items:center;
  background: rgba(34,211,238,.08);
  border: 1px dashed rgba(34,211,238,.35);
  padding: .5rem .7rem; border-radius: 12px;
}}
.kpi .lab {{ font-size:.78rem; color:#93c5fd; }}
.kpi .val {{ font-size:1rem; font-weight:800; }}
.small {{ font-size:.85rem; opacity:.85 }}
strong, b {{ color:#fff; }}
.dataframe tbody tr:hover {{ background: rgba(255,255,255,.03); }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca live · Altitudine · Finestre A/B/C · T° neve realistica · 8 marchi sciolina · Struttura & Angoli</span>", unsafe_allow_html=True)
st.write("")

# ========================= HELPERS =========================
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, display:str)->str:
    # Nome breve + admin1 + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or display.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc:
        short = f"{short} — {cc}"
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
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            # Altitudine
            alt = get_elevation(lat, lon)
            alt_txt = f" · {int(alt)} m" if alt is not None else ""
            label = f"{flag(cc)}  {label_short}{alt_txt}"
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

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["rain"] = df["rain"].astype(float)
    out["snowfall"] = df["snowfall"].astype(float)
    return out

# ========================= SNOW TEMPERATURE (improved) =========================
def compute_snow_temperature(df, dt_hours=1.0):
    """
    Modello migliorato:
    - Se bagnato -> T_surf non fissata a 0, ma tende a 0 con offset in funzione di T_wet e neve fresca.
    - Notte serena -> raffreddamento radiativo più forte.
    - Vento forte -> accoppiamento aria/superficie più rapido (tau più corto).
    - Filtro esponenziale su top 5 mm (T_top5) con tau variabile.
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])

    # flag
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1

    # dew/air mix come stima stato igrometrico
    tw = (df["T2m"] + df["td"]) / 2.0

    # --- Temperatura superficie "target" (non filtrata) ---
    Tsurf = pd.Series(index=df.index, dtype=float)

    # base radiativo: aria - (f(cloud,wind))
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=8.0)
    rad_cool = (1.2 + 3.2*clear - 0.25*windc).clip(0.4, 4.8)  # K
    base_dry = df["T2m"] - rad_cool

    # se notte serena molto fredda, limite inferiore un po’ più freddo
    night_clear = (~sunup) & (clear>0.6)
    base_dry.loc[night_clear] = base_dry.loc[night_clear] - 0.6

    # stato bagnato: tende a 0 ma:
    # - se nevica forte e aria fredda: può stare leggermente sotto 0 (sovrafusione ridotta)
    wet_mask = (rain | (df["T2m"]>0) | (snow & df["T2m"]>=-1) | (tw>-0.7))
    Twet = pd.Series(0.0, index=df.index)
    # neve fresca con aria fredda -> -0.3°C target
    cold_snow = snow & (df["T2m"]<=-2)
    Twet.loc[cold_snow] = -0.3
    # pioggia con aria >1°C -> +0.2°C target (pellicola acqua)
    warm_rain = rain & (df["T2m"]>=1.0)
    Twet.loc[warm_rain] = 0.2

    # comb: se bagnato usa T_wet; altrimenti base_dry
    Tsurf.loc[wet_mask] = Twet[wet_mask]
    Tsurf.loc[~wet_mask] = base_dry[~wet_mask]

    # clamp realistico
    Tsurf = Tsurf.clip(lower=-20, upper=1.0)

    # --- Filtro dinamico per i top 5 mm ---
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)   # ore
    # vento forte o precipitazione -> accoppiamento più rapido
    tau.loc[(df["wind"]>=6) | (rain) | (snow)] = 3.0
    # notte calma serena -> più lento (strato più isolato)
    tau.loc[(~sunup) & (df["wind"]<2) & (clear>0.6)] = 9.0

    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df)>0:
        # inizializza vicino alla superficie, ma non oltre lo 0 bagnato
        T_top5.iloc[0] = min(df["T2m"].iloc[0], Tsurf.iloc[0])
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (Tsurf.iloc[i] - T_top5.iloc[i-1])

    df["T_surf"] = Tsurf
    df["T_top5"] = T_top5
    return df

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ========================= WAX BANDS & BRANDS =========================
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
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ========================= STRUTTURA & ANGOLI =========================
def structure_for(t_surf):
    # Solo NOME della struttura (niente immagini)
    if t_surf <= -10:
        return "Lineare fine (freddo/secco)"
    elif t_surf <= -3:
        return "Blended/Cross universale"
    else:
        return "Diagonale / V (umido/caldo)"

def tune_for(t_surf, discipline):
    if t_surf <= -10:
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return side_map.get(discipline, 88.0), base

# ========================= UI: RICERCA LOCALITÀ =========================
st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi… es. Champoluc, Plateau Rosa, Sestriere",
    clear_on_submit=False,
    default=None
)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT · 1568 m")

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

st.markdown(f"<div class='kpi'><div class='lab'>Località</div><div class='val'>{place_label}</div></div>", unsafe_allow_html=True)

# ========================= FINESTRE A/B/C =========================
st.subheader("2) Finestre orarie A · B · C (oggi)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ========================= RUN =========================
st.subheader("3) Scarica dati meteo & calcola")
if st.button("Scarica e calcola", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        st.success(f"Dati per **{place_label}** caricati.")

        # ---- Tabella chiara (colonne essenziali + unità) ----
        table = res.copy()
        table = table[["time","T2m","T_surf","T_top5","prp_mmph","prp_type","wind","cloud","rain","snowfall"]]
        table = table.rename(columns={
            "time":"Ora (local)",
            "T2m":"T aria (°C)",
            "T_surf":"T neve superficie (°C)",
            "T_top5":"T neve top 5 mm (°C)",
            "prp_mmph":"Prec. (mm/h)",
            "prp_type":"Tipo precipitazione",
            "wind":"Vento (m/s)",
            "cloud":"Nuvolosità (0-1)",
            "rain":"Pioggia (mm/h)",
            "snowfall":"Neve (cm/h approx)"
        })
        st.dataframe(table, use_container_width=True, hide_index=True)

        # ---- Grafici rapidi ----
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(figsize=(8,3)); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve surf"); plt.plot(t,res["T_top5"],label="T neve top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)

        fig2 = plt.figure(figsize=(8,2.4)); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # ---- Blocchi A/B/C ----
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n### Blocco {L}")
            W = window_slice(res, "Europe/Rome", s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # Struttura (nome)
            st.markdown(f"**Struttura consigliata:** {structure_for(t_med)}")

            # Marchi sciolina (8) — cards semplici
            cols = st.columns(4)
            cols2 = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='card'><div style='color:#a5f3fc;font-size:.8rem'>{brand}</div>"
                    f"<div style='font-weight:800;font-size:1rem'>{rec}</div></div>", unsafe_allow_html=True
                )
            for i,(brand,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='card'><div style='color:#a5f3fc;font-size:.8rem'>{brand}</div>"
                    f"<div style='font-weight:800;font-size:1rem'>{rec}</div></div>", unsafe_allow_html=True
                )

            # Angoli per 4 discipline
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = tune_for(t_med, d)
                rows.append([d, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
