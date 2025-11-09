# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math, datetime as dt
import matplotlib.pyplot as plt
from datetime import time, date
from dateutil import tz
from streamlit_searchbox import st_searchbox  # dropdown live, no Enter

# ========================= THEME / STYLE =========================
PRIMARY = "#10bfcf"
BG      = "#0b1220"
CARD    = "#0f172a"
TEXT    = "#eaf2ff"
ACCENT  = "#60a5fa"
WARN    = "#f59e0b"
OK      = "#22c55e"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg: {BG};
  --card: {CARD};
  --text: {TEXT};
  --primary: {PRIMARY};
  --accent: {ACCENT};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: linear-gradient(180deg, var(--bg) 0%, #0b1328 100%);
}}
.block-container {{
  padding-top: .6rem; padding-bottom: 2rem;
}}
h1,h2,h3,h4,h5,p,span,div,label {{ color: var(--text); }}
.badge {{
  display:inline-flex; align-items:center; gap:.4rem;
  padding:.35rem .7rem; border-radius:999px;
  background: rgba(16,191,207,.12); border:1px solid rgba(16,191,207,.35);
  font-size:.8rem;
}}
.card {{
  background: var(--card); border:1px solid rgba(255,255,255,.08);
  border-radius:16px; padding:16px;
  box-shadow: 0 12px 30px rgba(0,0,0,.35);
}}
.kpi {{
  display:flex; gap:.6rem; align-items:center;
  background: rgba(96,165,250,.12); border:1px dashed rgba(96,165,250,.45);
  padding:.5rem .65rem; border-radius:12px; font-size:.9rem;
}}
.banner {{
  display:flex; gap:.6rem; align-items:center; justify-content:space-between;
  background: rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.12);
  padding:.65rem .8rem; border-radius:12px;
}}
.badge-ok {{ color:#bbf7d0; border-color:#34d399; }}
.badge-warn {{ color:#fde68a; border-color:#f59e0b; }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.08); margin:.75rem 0 }}
.small {{ opacity:.8; font-size:.85rem; }}
.table thead tr th {{ background: rgba(255,255,255,.04); }}
.brand {{
  display:flex; align-items:center; gap:.7rem; padding:.55rem .7rem;
  border-radius:12px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
}}
.brand img {{ height:22px; }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca super-rapida · Giorno selezionabile · Stato neve · Indice di scorrevolezza · 8 marchi</span>", unsafe_allow_html=True)

# ========================= HELPERS =========================
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

COUNTRY_CHOICES = {
    "Tutti": None, "IT · Italia": "it", "FR · France": "fr", "CH · Schweiz": "ch",
    "AT · Österreich": "at", "DE · Deutschland": "de"
}

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    short = ", ".join([p for p in [name, admin1] if p])
    return f"{short} — {cc}" if cc else short

def nominatim_search(q:str):
    """Live suggestions ad ogni tasto (no Enter). Rispetta filtro Paese se presente."""
    if not q or len(q) < 2:
        return []
    try:
        country = st.session_state.get("_country_filter")
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        if country:
            params["countrycodes"] = country
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params=params,
                         headers={"User-Agent":"telemark-wax-pro/1.2"},
                         timeout=8)
        r.raise_for_status()
        st.session_state._geo = {}
        out = []
        for it in r.json():
            addr = it.get("address",{}) or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = addr.get("country_code","") or ""
            lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
            label = f"{flag_emoji(cc)}  {label_short}"
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo[key] = (lat, lon, label, addr)
            out.append(key)
        return out
    except Exception:
        return []

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except:
        pass
    return None

# ========================= METEO / MODELLO =========================
def fetch_open_meteo(lat, lon, timezone_str="Europe/Rome"):
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","rain","snowfall","cloudcover",
            "windspeed_10m","is_day","weathercode","surface_pressure"
        ]),
        "forecast_days": 7,
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        p = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if p<=0 or pd.isna(p): return "none"
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
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    # RH (se manca, calcola da T e Td)
    if "relative_humidity_2m" in df:
        out["RH"] = df["relative_humidity_2m"].astype(float).clip(0,100)
    else:
        Td = df["dew_point_2m"].astype(float)
        T  = df["temperature_2m"].astype(float)
        # formula approssimata RH da T & Td
        out["RH"] = (100 - 5*(T - Td)).clip(0,100)
    out["Td"]   = df["dew_point_2m"].astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df["rain"].astype(float); out["snow"] = df["snowfall"].astype(float)
    out["prp_type"] = prp_type(df[["precipitation","rain","snowfall","weathercode"]].copy())
    out["Psurf"] = df.get("surface_pressure", pd.Series(np.nan, index=df.index)).astype(float)
    return out

def wet_bulb_stull(T, RH):
    """Bulbo umido in °C (Stull 2011), T in °C, RH in %."""
    RHc = np.clip(RH, 1, 100)
    Tw = T*np.arctan(0.151977*np.sqrt(RHc + 8.313659)) + np.arctan(T + RHc) \
         - np.arctan(RHc - 1.676331) + 0.00391838*(RHc**1.5)*np.arctan(0.023101*RHc) - 4.686035
    return Tw

def est_shortwave_Wm2(cloud, sunup):
    """Stima grezza SW_down da nuvolosità (clear-sky ~ 700 W/m2 di giorno)."""
    SW_clear = 700.0
    return np.where(sunup>0, SW_clear*(1 - 0.75*(cloud**3)), 0.0)

def energy_balance(df: pd.DataFrame):
    """Bilancio energetico semplice → T_surf e T_top5 non più 0 fisso."""
    X = df.copy()
    # componenti
    T = X["T2m"].astype(float)
    Td= X["Td"].astype(float)
    RH= X["RH"].astype(float)
    V = X["wind"].astype(float).clip(0, 8)  # vento effettivo
    C = X["cloud"].astype(float)
    sunup = X["sunup"].astype(int)

    Tw = pd.Series(wet_bulb_stull(T.values, RH.values), index=X.index)
    SW = pd.Series(est_shortwave_Wm2(C.values, sunup.values), index=X.index)

    # albedo dinamico (neve nuova→vecchia). proxy: ore da ultimo evento neve/pioggia
    snow_flag = (X["snow"]>0)
    rain_flag = (X["rain"]>0)
    last_event_idx = []
    last = -999
    for i,ev in enumerate((snow_flag|rain_flag).values):
        if ev: last = 0
        else: last = last + 1 if last>-999 else 999
        last_event_idx.append(last)
    last_event = pd.Series(last_event_idx, index=X.index).replace(999, 72)
    albedo = (0.55 + (0.85-0.55)*np.exp(-last_event/24.0)).clip(0.5,0.9)

    # coefficienti (tarabili con storico)
    k_rad = 0.012   # impatto radiazione (°C per 100 W/m2)
    k_conv= 0.35    # perdita convettiva (°C per m/s)
    k_vpd = 0.10    # effetto deficit vapore via (T - Tw)

    # T* target superficiale
    T_target = T - k_conv*V - k_vpd*(T - Tw) + k_rad*(SW/100.0) - 0.2*(1.0 - albedo)
    # pioggia/neve umida spingono a 0°C
    wet_force = ((X["prp_type"].isin(["rain","mixed"])) | ((X["prp_type"]=="snow") & (T>-2) & (RH>80))).astype(float)
    T_target = np.where(wet_force>0, np.minimum(T_target, 0.0), T_target)

    # inerzia superficiale (filtro esponenziale)
    tau = pd.Series(6.0, index=X.index)
    tau.loc[(sunup==0) & (V<2) & (C<0.3)] = 8.0
    tau.loc[(V>=6) | (X["prp_mmph"]>0)] = 3.0
    alpha = 1.0 - np.exp(-1.0 / tau)

    T_surf = pd.Series(index=X.index, dtype=float)
    if len(X)>0:
        T_surf.iloc[0] = np.minimum(T.iloc[0], 0.0) if wet_force.iloc[0]>0 else T_target.iloc[0]
        for i in range(1, len(X)):
            T_surf.iloc[i] = T_surf.iloc[i-1] + alpha.iloc[i]*(T_target.iloc[i] - T_surf.iloc[i-1])

    # strato 0–5 mm (più lento)
    tau5 = (tau + 2.0).clip(3.0, 12.0)
    alpha5 = 1.0 - np.exp(-1.0 / tau5)
    T_top5 = pd.Series(index=X.index, dtype=float)
    if len(X)>0:
        T_top5.iloc[0] = T_surf.iloc[0]
        for i in range(1, len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha5.iloc[i]*(T_surf.iloc[i] - T_top5.iloc[i-1])

    out = X.copy()
    out["Tw"] = Tw
    out["SW"] = SW
    out["albedo"] = albedo
    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    return out

def snow_state_and_glide(df_slice: pd.DataFrame):
    """Classifica stato neve + indice di scorrevolezza (0–100) + affidabilità."""
    if df_slice.empty:
        return "—", 0, "Bassa"
    T = df_slice["T2m"].mean()
    Ts= df_slice["T_surf"].mean()
    RH= df_slice["RH"].mean()
    SW= df_slice["SW"].mean()
    snow24 = (df_slice["snow"]>0).rolling(window=24, min_periods=1).sum().iloc[-1] if len(df_slice)>=24 else df_slice["snow"].sum()
    prp = df_slice["prp_mmph"].mean()
    wind = df_slice["wind"].mean()

    # regole semplici
    if prp>0 and df_slice["prp_type"].isin(["rain","mixed"]).mean()>0.2:
        state = "Pioggia/neve mista (bagnata)"
    elif snow24 >= 3.0 and T < -1.0 and wind < 5:
        state = "Neve nuova (fredda)"
    elif Ts <= -8:
        state = "Compatta fredda"
    elif -8 < Ts <= -3:
        state = "Trasformata secca"
    elif -3 < Ts <= 0.5 and RH>70 and SW>150:
        state = "Primaverile umida"
    elif Ts > 0.5 or prp>0:
        state = "Bagnata / granulosa"
    else:
        state = "Universale variabile"

    # indice di scorrevolezza (0–100)
    # max vicino a ~ -0.5°C (film d'acqua ottimale)
    s1 = 100 * np.exp(-((Ts + 0.5)/2.2)**2)
    s2 = np.clip((RH-40)/50*100, 0, 100) * 0.25           # umidità
    s3 = np.clip(SW/700, 0, 1) * 15                       # radiazione
    s4 = np.clip(1 - (abs(Ts)+0.5)/12, 0, 1) * 20        # penalità freddo estremo
    s5 = np.clip(1 - wind/10, 0, 1) * 10                 # vento forte frena
    glide = int(np.clip(s1 + s2 + s3 + s4 + s5, 0, 100))

    # affidabilità: bassa se varianza alta o precipitazione discontinua
    spread = df_slice["T_surf"].std()
    reliability = "Alta" if (spread<1.0 and prp<1.5) else ("Media" if spread<2.0 else "Bassa")
    return state, glide, reliability

def window_slice(res, tzname, day: date, s: time, e: time):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    mask = (D["dt"].dt.date == day) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)
    W = D[mask]
    return W

# ========================= WAX BANDS (8 marchi) =========================
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]

BRANDS = [
    ("Swix","swix", SWIX), ("Toko","toko", TOKO), ("Vola","vola", VOLA), ("Rode","rode", RODE),
    ("Holmenkol","holmenkol", HOLM), ("Maplus","maplus", MAPL), ("Start","start", START), ("Skigo","skigo", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def brand_logo_svg(text, color="#1f2937"):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='120' height='28'><rect width='120' height='28' rx='6' fill='{color}'/><text x='10' y='19' font-size='14' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ========================= UI: RICERCA =========================
st.markdown("### 1) Località & periodo")

cc_left, search_col, day_col, hours_col = st.columns([1,3,1.2,1.2])
with cc_left:
    cc_label = st.selectbox("Paese (facoltativo)", list(COUNTRY_CHOICES.keys()), index=0)
    st.session_state["_country_filter"] = COUNTRY_CHOICES[cc_label]

with search_col:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (es. Champoluc, Plateau Rosa, Sestriere)",
        clear_on_submit=False,
        default=None
    )

# decode selection -> lat,lon,label
if selected and "|||" in selected and "_geo" in st.session_state:
    lat, lon, label, addr = st.session_state._geo.get(selected, (45.831, 7.730, "Champoluc", {}))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label
else:
    lat = st.session_state.get("sel_lat", 45.831)
    lon = st.session_state.get("sel_lon", 7.730)
    label = st.session_state.get("sel_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

with day_col:
    today = dt.date.today()
    day = st.date_input("Giorno", value=today, min_value=today, max_value=today+dt.timedelta(days=6))
with hours_col:
    horizon = st.slider("Ore previsione", 24, 168, 96, 12)

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"<div class='kpi'><span>📍</span><span><b>{label}</b>{alt_txt}</span></div>", unsafe_allow_html=True)

# ========================= FINESTRE A/B/C =========================
st.markdown("### 2) Finestre orarie (giorno selezionato)")
ca, cb, cc = st.columns(3)
with ca:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with cb:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with cc:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

# ========================= RUN METEO + MODELLO =========================
st.markdown("### 3) Dati meteo & calcolo")
go = st.button("Scarica previsioni e calcola", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        raw = build_df(js, horizon)
        res = energy_balance(raw)

        st.success("Dati caricati e modello eseguito.")
        # Tabella compatta e chiara
        tbl = res.copy()
        tbl = tbl.rename(columns={
            "time":"Ora","T2m":"T aria (°C)","Td":"Td (°C)","RH":"UR (%)",
            "T_surf":"T neve (°C)","T_top5":"T top5 (°C)","prp_mmph":"Prec (mm/h)",
            "prp_type":"Tipo","wind":"Vento (m/s)","cloud":"Nuvolosità","SW":"SW (W/m²)"
        })
        tbl["Ora"] = pd.to_datetime(tbl["Ora"]).dt.strftime("%Y-%m-%d %H:%M")
        show_cols = ["Ora","T aria (°C)","Td (°C)","UR (%)","T neve (°C)","T top5 (°C)","Prec (mm/h)","Tipo","Vento (m/s)","Nuvolosità","SW (W/m²)"]
        st.dataframe(tbl[show_cols], use_container_width=True, height=300)

        # Grafici rapidi
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(figsize=(7,3))
        plt.plot(t, res["T2m"], label="T aria")
        plt.plot(t, res["T_surf"], label="T neve")
        plt.plot(t, res["T_top5"], label="T top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        # Download CSV
        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_snowT.csv", mime="text/csv")

        # Blocchi A/B/C
        for name,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n## Blocco {name}")
            W = window_slice(res, "Europe/Rome", day, s, e)
            if W.empty:
                st.info("Nessun dato in questa finestra per il giorno scelto.")
                continue

            # Stato neve + indice + affidabilità (banner)
            state, glide, reliab = snow_state_and_glide(W)
            color_class = "badge-ok" if reliab=="Alta" else ("badge-warn" if reliab=="Media" else "")
            st.markdown(
                f"<div class='banner'><div>❄️ <b>{state}</b></div>"
                f"<div>🏎️ Indice di scorrevolezza: <b>{glide}/100</b></div>"
                f"<div class='badge {color_class}'>Affidabilità: <b>{reliab}</b></div></div>",
                unsafe_allow_html=True
            )

            t_med = float(W["T_surf"].mean())
            st.markdown(f"<div class='kpi'><span>🌡️</span><span><b>T neve media {name}:</b> {t_med:.1f}°C</span></div>", unsafe_allow_html=True)

            # Tabellina discipline + struttura (solo nome) + angoli
            def tune_for(t_surf, d):
                if t_surf <= -10:
                    fam = "Linear fine (S1) – freddo/secco"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
                elif t_surf <= -3:
                    fam = "Cross hatch (S1) – universale freddo"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
                elif t_surf <= 0.5:
                    fam = "Wave (S2) – umido/neve trasformata"; base = 0.8; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                else:
                    fam = "Thumb print (S2) – bagnata/primaverile"; base = 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                return fam, side, base

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura (nome)","Lamina SIDE (°)","Lamina BASE (°)"]))

            # WAX 8 marchi (con tocco “secco/umido” via RH)
            cols1 = st.columns(4); cols2 = st.columns(4)
            RHm = float(W["RH"].mean())
            humid_tag = " (umido)" if RHm>=75 else (" (secco)" if RHm<=55 else "")
            brand_rows = BRANDS[:4], BRANDS[4:]
            for idx, row in enumerate(brand_rows):
                cols = cols1 if idx==0 else cols2
                for i,(brand,slug,bands) in enumerate(row):
                    rec = pick(bands, t_med)
                    badge = brand_logo_svg(brand.upper(), color="#1f2937")
                    cols[i].markdown(
                        f"<div class='brand'><img src='{badge}'/><div><div class='small'>{brand}</div>"
                        f"<div style='font-weight:800'>{rec}{humid_tag}</div></div></div>", unsafe_allow_html=True
                    )

    except Exception as e:
        st.error(f"Errore: {e}")
