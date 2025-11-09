# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox  # dropdown live, stile meteoblue

# ------------------------ PAGE & THEME (dark + colori impattanti) ------------------------
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#60a5fa"   # blu acceso per KPI
DANGER  = "#f97316"   # arancio per caldo/umido
OK      = "#22c55e"   # verde
TEXT    = "#e5e7eb"
BG      = "#0b1220"   # scuro profondo

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --card-bg: rgba(255,255,255,.03);
  --card-b: rgba(255,255,255,.10);
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% -10%, #0f1a32 0%, {BG} 35%, #070b15 100%);
}}
.block-container {{ padding-top: .9rem; }}
h1,h2,h3,h4,h5,label, p, span, div {{ color:{TEXT}; }}
.badge {{
  display:inline-flex; gap:.4rem; align-items:center;
  border:1px solid rgba(255,255,255,.18); padding:.3rem .6rem; border-radius:999px;
  background:linear-gradient(90deg, rgba(16,191,207,.12), rgba(96,165,250,.10));
  font-size:.78rem; opacity:.95
}}
.card {{
  background:var(--card-bg); border:1px solid var(--card-b); border-radius:16px; padding:14px;
  box-shadow: 0 12px 28px rgba(0,0,0,.35);
}}
.kpi {{
  display:flex; gap:10px; align-items:baseline; padding:10px 12px; border-radius:12px;
  background:linear-gradient(90deg, rgba(96,165,250,.14), rgba(16,191,207,.10));
  border:1px dashed rgba(96,165,250,.45);
}}
.kpi .lab {{ font-size:.80rem; color:#c7d2fe }}
.kpi .val {{ font-weight:800; font-size:1.05rem; color:#fff }}
.banner {{
  padding:.65rem .8rem; border-radius:12px; margin:.35rem 0 .6rem;
  border:1px solid rgba(255,255,255,.16);
  background:linear-gradient(90deg, rgba(34,197,94,.12), rgba(16,185,129,.10));
  font-size:.92rem;
}}
.banner.wet {{
  background:linear-gradient(90deg, rgba(249,115,22,.14), rgba(234,179,8,.10));
  border-color:rgba(249,115,22,.45);
}}
.banner.cold {{
  background:linear-gradient(90deg, rgba(59,130,246,.16), rgba(16,185,129,.08));
  border-color:rgba(59,130,246,.45);
}}
.ci-wrap {{
  display:flex; align-items:center; gap:.6rem; margin:.25rem 0 .6rem;
}}
.ci-bar {{
  height:12px; width:220px; border-radius:6px; overflow:hidden;
  border:1px solid rgba(255,255,255,.18);
  background: linear-gradient(90deg,#0ea5e9 0%, #6366f1 30%, #ef4444 65%, #f59e0b 100%);
}}
.ci-marker {{
  height:16px; width:2px; background:#fff; margin-left:-1px; border-radius:2px;
  box-shadow:0 0 8px rgba(255,255,255,.8);
}}
.brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px;
         background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); }}
.brand img {{ height:22px; }}
.styled-table td, .styled-table th {{
  padding:.45rem .55rem; border-bottom:1px solid rgba(255,255,255,.12);
}}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Altitudine · A/B/C · Umidità · Indice cromatico · Banner condizioni · Affidabilità</span>", unsafe_allow_html=True)

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
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
        ); r.raise_for_status()
        st.session_state._options = {}
        out = []
        for item in r.json():
            addr = item.get("address",{}) or {}
            label_short = concise_label(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag_emoji(cc)}  {label_short}"
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
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except:
        pass
    return None

# Magnus formula per RH da T e Td (°C)
def rel_humidity(T, Td):
    try:
        a, b = 17.625, 243.04
        gamma_Td = (a*Td)/(b+Td)
        gamma_T  = (a*T)/(b+T)
        rh = 100.0 * math.exp(gamma_Td - gamma_T)
        return max(0.0, min(100.0, rh))
    except Exception:
        return None

# ------------------------ METEO PIPELINE ------------------------
def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
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

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    out["RH"]  = [rel_humidity(t, d) for t, d in zip(out["T2m"], out["td"])]
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    """Modello semplificato con umido/asciutto, radiazione/vento e rilassamento top-5 mm."""
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1

    # indice 'bagnato' più sensibile a temperatura, dewpoint e tipo precip
    tw = (df["T2m"] + df["td"]) / 2.0
    rh = pd.to_numeric(df["RH"]).fillna(70.0)
    wet = (
        rain |
        (df["T2m"] > 0.3) |
        (snow & (df["T2m"] >= -1.0)) |
        (tw >= -0.4) |
        (rh > 92)
    )

    # superficie: clamp a 0°C quando bagnato; altrimenti sottraggo “raffreddamento” radiativo/vento
    T_surf = pd.Series(index=df.index, dtype=float)
    T_surf.loc[wet] = 0.0
    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=6.0)
    # coeff radiativo/convettivo
    drad = (1.2 + 2.7*clear - 0.25*windc).clip(0.4, 4.2)
    T_surf.loc[dry] = (df["T2m"] - drad)[dry]

    # sole freddo: limite a -0.5°C se aria tra -10 e 0 con cielo poco nuvoloso
    sunny_cold = sunup & dry & df["T2m"].between(-10, 0, inclusive="both") & (df["cloud"]<0.35)
    T_surf.loc[sunny_cold] = pd.concat([
        (df["T2m"] + 0.5*(1.0 - df["cloud"]))[sunny_cold],
        pd.Series(-0.5, index=df.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # rilassamento per i primi 5 mm
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)  # ore
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = (1.0 - (math.e ** (-dt_hours / tau))).clip(0.05, 0.9)
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0) if wet.iloc[0] else min(T_surf.iloc[0], df["T2m"].iloc[0])
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    return df

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ------------------------ CLASSIFICHE, BANNER, AFFIDABILITÀ ------------------------
def condition_label(t_surf_mean: float, rh_mean: float, prp_any: bool):
    """Restituisce (classe, css_class)"""
    if prp_any and t_surf_mean > -0.5:
        return ("Neve bagnata / trasformata", "banner wet")
    if t_surf_mean >= -1.0 and rh_mean >= 85:
        return ("Neve umida / nuova", "banner wet")
    if t_surf_mean <= -8:
        return ("Neve molto fredda / secca", "banner cold")
    if t_surf_mean <= -3:
        return ("Neve fredda / compatta", "banner cold")
    return ("Neve universale / mista", "banner")

def reliability_score(df_block: pd.DataFrame):
    """0–100% in base a dispersione meteo e segnali chiari."""
    if df_block.empty: return 0
    stdT = float(df_block["T2m"].std() or 0)
    cloud_var = float(df_block["cloud"].std() or 0)
    wind_m = float(df_block["wind"].mean() or 0)
    prp = (df_block["prp_mmph"]>0.05).mean()
    base = 88.0
    base -= min(stdT*6, 18)           # instabilità termica
    base -= min(cloud_var*18, 18)     # variabilità nuvole
    base -= min(max(0,wind_m-5)*2.5, 15)  # vento alto
    base -= min(prp*22, 22)           # precipitazioni elevate
    return int(max(35, min(98, base))) # clamp

def color_index_position(temp_c: float):
    """mappa T_surf alla posizione (0..1) nella barra blu→viola→rosso→giallo"""
    # ancoraggi indicativi: -18°C (0.0), -8°C (0.3), -2°C (0.65), +4°C (1.0)
    x = (temp_c + 18) / 22  # grezzo
    return max(0.0, min(1.0, x))

# ------------------------ WAX & STRUTTURE (nomi; niente immagini) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]
BRAND_BANDS = [
    ("Swix"      ,"#ef4444", SWIX),
    ("Toko"      ,"#f59e0b", TOKO),
    ("Vola"      ,"#3b82f6", VOLA),
    ("Rode"      ,"#22c55e", RODE),
    ("Holmenkol" ,"#06b6d4", HOLM),
    ("Maplus"    ,"#f97316", MAPL),
    ("Start"     ,"#eab308", START),
    ("Skigo"     ,"#a855f7", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_for(t_surf, discipline):
    # Solo nomi struttura + angoli SIDE/BASE
    if t_surf <= -10:
        fam = "Lineare fine (freddo/secco)"
        base = 0.5; side = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}.get(discipline,88.0)
    elif t_surf <= -3:
        fam = "Incrociata / leggera onda (universale)"
        base = 0.7; side = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}.get(discipline,88.0)
    else:
        fam = "Scarico diagonale / V (umido/caldo)"
        base = 0.8 if t_surf <= 0.5 else 1.0
        side = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}.get(discipline,88.0)
    return fam, side, base

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ 1) RICERCA LOCALITÀ ------------------------
st.subheader("1) Cerca località")
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
st.markdown(f"<div class='kpi'><span class='lab'>Località</span><span class='val'>{place_label}{alt_txt}</span></div>", unsafe_allow_html=True)

# ------------------------ 2) Finestre A/B/C ------------------------
st.subheader("2) Finestre orarie A · B · C (oggi)")
c1, c2, c3 = st.columns(3)
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

# ------------------------ 3) Meteo + raccomandazioni ------------------------
st.subheader("3) Scarica dati meteo & calcola")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        # Tabella meteo ripulita (solo colonne principali)
        tb = res[["time","T2m","td","RH","T_surf","T_top5","prp_mmph","prp_type","cloud","wind"]].copy()
        tb.columns = ["Time","T (°C)","Td (°C)","RH (%)","Snow surf (°C)","Top 5mm (°C)","Prp (mm/h)","Prp type","Cloud (0-1)","Wind (m/s)"]
        st.markdown("**Dati previsione (ridotti)**")
        st.dataframe(tb, use_container_width=True)

        # Grafici compatti
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve sup."); plt.plot(t,res["T_top5"],label="T top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV risultato", data=tb.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # BLOCCHI A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n### Blocco {L}")

            W = window_slice(res, "Europe/Rome", s, e)
            t_med  = float(W["T_surf"].mean())
            rh_med = float(pd.to_numeric(W["RH"]).mean())
            prp_any = bool((W["prp_mmph"]>0.05).any())

            # Banner condizioni + affidabilità
            cond_text, cond_css = condition_label(t_med, rh_med, prp_any)
            score = reliability_score(W)
            st.markdown(f"<div class='{cond_css}'>Condizioni stimate: <b>{cond_text}</b> · Affidabilità: <b>{score}%</b></div>", unsafe_allow_html=True)

            # Indice cromatico (senza toggle): marcatore sulla barra
            pos = color_index_position(t_med)  # 0..1
            left = int(pos*220)
            st.markdown(
                f"<div class='ci-wrap'>"
                f"<div class='ci-bar'><div class='ci-marker' style='margin-left:{left}px'></div></div>"
                f"<div style='font-size:.9rem;opacity:.9'>T_surf medio {L}: <b>{t_med:.1f}°C</b></div>"
                f"</div>", unsafe_allow_html=True
            )

            # Marche sciolina (8)
            cols = st.columns(4); cols2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # Strutture (solo nome) + angoli per discipline
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
