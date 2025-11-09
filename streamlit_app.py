# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ========================= THEME (DARK) =========================
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#e2e8f0"   # text light
MUTED   = "#9ca3af"   # secondary
CARD    = "#0b1220"   # panels
BG      = "#0a0f1d"   # app bg
WARN    = "#f59e0b"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg: {BG};
  --card: {CARD};
  --txt: {ACCENT};
  --muted: {MUTED};
  --primary: {PRIMARY};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 800px at 20% -10%, #0d1730 0%, var(--bg) 45%);
}}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4, label, p, span, div {{ color: var(--txt); }}
hr {{ border: none; border-top: 1px solid #1f2937; margin: .75rem 0; }}
.card {{
  background: var(--card); border: 1px solid #1f2937; border-radius: 16px; padding: 14px;
  box-shadow: 0 10px 22px rgba(0,0,0,.25);
}}
.badge {{
  display: inline-block; border:1px solid rgba(255,255,255,.12);
  padding:.25rem .6rem; border-radius:999px; font-size:.78rem; color:var(--muted);
}}
.brand {{ display:flex; gap:.6rem; align-items:center; background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:.5rem .6rem; }}
.brand img {{ height:22px; }}
.kpi {{ display:flex; gap:8px; align-items:center; background:rgba(16,191,207,.06);
  border:1px dashed rgba(16,191,207,.45); padding:8px 10px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:#93c5fd; }}
.kpi .val {{ font-size:1rem; font-weight:800; }}
small, .muted {{ color:var(--muted); }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Altitudine · RH & Wet-bulb · Blocchi A/B/C · Marchi · Strutture (nomi) · Angoli</span>", unsafe_allow_html=True)

# ========================= HELPERS =========================
def flag_emoji(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc:
        short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
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
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{flag_emoji(cc)}  {label_short}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"label":f"{flag_emoji(cc)}  {label_short}"}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except: pass
    return None

def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

def _ptype(df):
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

def wet_bulb_stull(T, RH):
    # T[°C], RH[%] -> Tw[°C] (Stull 2011 approximate)
    RH = np.clip(RH, 1, 100)
    Tw = (T*np.arctan(0.151977*np.sqrt(RH+8.313659)) +
          np.arctan(T+RH) - np.arctan(RH-1.676331) +
          0.00391838*(RH**1.5)*np.arctan(0.023101*RH) - 4.686035)
    return Tw

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["RH"]   = df["relative_humidity_2m"].astype(float)
    out["td"]   = df["dew_point_2m"].astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp"]  = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["ptype"]= _ptype(extra)
    out["Tw"]   = wet_bulb_stull(out["T2m"].to_numpy(), out["RH"].to_numpy())
    return out

def compute_snow_T(out):
    out = out.copy()
    T = out["T2m"].to_numpy()
    RH = out["RH"].to_numpy()
    Tw = out["Tw"].to_numpy()
    cloud = out["cloud"].to_numpy()
    wind = out["wind"].to_numpy()
    sun  = (out["sunup"].to_numpy()==1)
    ptyp = out["ptype"].astype(str).str.lower().to_numpy()

    wet = (ptyp=="rain") | (ptyp=="mixed") | (T>0) | (Tw>-0.5) | ((ptyp=="snow") & (T>=-1))
    # Bagnato/umido → vicino a 0: usa Tw ma non sopra 0.2°C
    T_surf = np.where(wet, np.clip(Tw, -0.3, 0.1), np.nan)

    # Asciutto: raffreddamento radiativo/notturno + vento; limitiamo per fisica plausibile
    # k_radiative cresce con cielo sereno; k_wind raffredda Ulteriormente
    k_rad = 1.2 + 6.0*(1.0 - cloud)                # 1.2 .. 7.2
    k_w   = 0.20*np.clip(wind, 0, 8)               # 0 .. 1.6
    T_dry = T - (k_rad + k_w)

    # Giorno molto sereno e freddo: il sole può scaldare leggermente la superficie
    # (ma non oltre T-0.5)
    T_dry_day = np.where(sun, np.maximum(T_dry, T - 0.5), T_dry)
    T_dry_day = np.clip(T_dry_day, T - 12.0, 0.0)  # limiti fisici

    # Combina
    T_surf = np.where(np.isnan(T_surf), T_dry_day, T_surf)

    # Smorzamento nei primi 5 mm: costante di tempo variabile
    tau = np.full_like(T, 6.0, dtype=float)
    tau = np.where((ptyp=="snow") | (ptyp=="rain") | (wind>=6), 3.0, tau)
    tau = np.where((sun==0) & (wind<2) & (cloud<0.3), 8.0, tau)
    alpha = 1.0 - np.exp(-1.0/np.maximum(tau, 0.5))  # passo=1h

    T_top5 = np.empty_like(T_surf)
    if len(T)>0:
        T_top5[0] = min(T[0], 0.0)
        for i in range(1,len(T)):
            T_top5[i] = T_top5[i-1] + alpha[i]*(T_surf[i] - T_top5[i-1])

    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    return out

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ========================= WAX & TUNE TABLES =========================
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]

BRANDS = [
    ("Swix", SWIX),
    ("Toko", TOKO),
    ("Vola", VOLA),
    ("Rode", RODE),
    ("Holmenkol", HOLM),
    ("Maplus", MAPL),
    ("Start", START),
    ("Skigo", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_family_name(t_surf):
    if t_surf <= -10: return "Lineare fine (freddo/secco)"
    if t_surf <= -3:  return "Universale incrociata / leggera onda"
    return "Scarico diagonale / V (umido/caldo)"

def side_base_for(t_surf, discipline):
    if t_surf <= -10:
        base = 0.5; sm = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        base = 0.7; sm = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        base = 0.8 if t_surf <= 0.5 else 1.0
        sm = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return sm.get(discipline, 88.0), base

# ========================= UI: SEARCH =========================
st.markdown("### 1) Cerca località")
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

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {place_label}{alt_txt}")

# ========================= WINDOWS =========================
st.markdown("### 2) Finestre orarie A · B · C (oggi)")
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
st.markdown("### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js  = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_T(src)

        st.success(f"Dati per **{place_label}** caricati.")

        # ---- Tabella compatta e leggibile
        df = res.copy()
        df_show = pd.DataFrame({
            "Ora": pd.to_datetime(df["time"]).dt.strftime("%d/%m %H:%M"),
            "T aria (°C)": df["T2m"].round(1),
            "UR (%)": df["RH"].round(0),
            "T rugiada (°C)": df["td"].round(1),
            "T wet-bulb (°C)": df["Tw"].round(1),
            "Nuvolosità": (df["cloud"]*100).round(0).astype(int).astype(str) + "%",
            "Vento (m/s)": df["wind"].round(1),
            "Prec. (mm/h)": df["prp"].round(1),
            "Tipo": df["ptype"].str.capitalize(),
            "T_surf (°C)": df["T_surf"].round(1),
            "T_top5 (°C)": df["T_top5"].round(1),
        })
        st.dataframe(df_show, use_container_width=True, height=360)

        # ---- Blocchi A/B/C con riepilogo + consigli
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = window_slice(res, "Europe/Rome", s, e)
            if W.empty:
                st.info("Nessun dato nella finestra selezionata.")
                continue

            t_med  = float(W["T_surf"].mean())
            rh_med = float(W["RH"].mean())
            pr_med = float(W["prp"].mean())
            cl_med = float(W["cloud"].mean())*100

            k1,k2,k3,k4 = st.columns(4)
            k1.markdown(f"<div class='kpi'><span class='lab'>T_surf media</span><span class='val'>{t_med:.1f}°C</span></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi'><span class='lab'>UR media</span><span class='val'>{rh_med:.0f}%</span></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi'><span class='lab'>Prec. media</span><span class='val'>{pr_med:.1f} mm/h</span></div>", unsafe_allow_html=True)
            k4.markdown(f"<div class='kpi'><span class='lab'>Nuvolosità</span><span class='val'>{cl_med:.0f}%</span></div>", unsafe_allow_html=True)

            # Wax cards (testuali, impatto visivo)
            st.markdown("**Sciolina consigliata (per marca):**")
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(brand,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(
                    f"<div class='brand'><div style='font-weight:800;color:{PRIMARY}'>{brand}</div>"
                    f"<div class='muted' style='font-size:.85rem'>{rec}</div></div>", unsafe_allow_html=True
                )
            for i,(brand,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><div style='font-weight:800;color:{PRIMARY}'>{brand}</div>"
                    f"<div class='muted' style='font-size:.85rem'>{rec}</div></div>", unsafe_allow_html=True
                )

            # Struttura: solo nome famiglia + angoli per discipline
            fam_name = tune_family_name(t_med)
            st.markdown(f"**Struttura consigliata (famiglia):** {fam_name}")

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = side_base_for(t_med, d)
                rows.append([d, fam_name, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
