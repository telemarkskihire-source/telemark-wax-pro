# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math, datetime as dt
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =============== PAGE THEME (dark, colori vivi) ===============
PRIMARY = "#10bfcf"   # turchese Telemark
ACCENT  = "#22d3ee"   # azzurro vivo
WARN    = "#f59e0b"   # giallo
DANGER  = "#ef4444"   # rosso
OK      = "#22c55e"   # verde
BG      = "#0b1220"   # sfondo scuro
CARD    = "#0f172a"   # card dark
TEXT    = "#e5e7eb"   # testo chiaro

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --primary:{PRIMARY};
  --accent:{ACCENT};
  --bg:{BG};
  --card:{CARD};
  --text:{TEXT};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: linear-gradient(180deg, {BG} 0%, #0a0f1a 100%);
}}
.block-container {{ padding-top: 0.6rem; padding-bottom: 2rem; }}

h1,h2,h3,h4,h5, label, p, span, div {{ color:{TEXT}; }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.08); }}

.card {{
  background:{CARD};
  border:1px solid rgba(255,255,255,.10);
  border-radius:16px;
  padding:14px 16px;
  box-shadow:0 10px 22px rgba(0,0,0,.35);
}}
.brand {{
  display:flex; align-items:center; gap:.75rem;
  background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.10);
  border-radius:12px; padding:.5rem .75rem;
}}
.badge {{
  display:inline-block; background:rgba(16,191,207,.15); color:{ACCENT};
  border:1px solid rgba(16,191,207,.45);
  padding:.25rem .6rem; border-radius:999px; font-size:.78rem
}}
.banner {{
  background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.10);
  border-radius:12px; padding:.6rem .8rem; margin:.4rem 0 .2rem 0;
}}
.kpi {{
  display:flex; gap:10px; align-items:center;
  background:rgba(16,191,207,.10);
  border:1px dashed rgba(16,191,207,.45);
  padding:.45rem .65rem; border-radius:12px; font-size:.9rem;
}}
.kpi .lab {{ color:#93c5fd; opacity:.9; }}
.kpi .val {{ font-weight:800; }}

.dataframe tbody tr:hover {{
  background-color: rgba(255,255,255,.04) !important;
}}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")

# =============== UTILS ===============
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def concise_label_from_address(addr:dict, display:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or display.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: return []
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
            label_short = concise_label_from_address(addr, item.get("display_name",""))
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

def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,relative_humidity_2m,windspeed_10m,is_day,weathercode",
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
    out["time"]  = df["time"]
    out["T2m"]   = df["temperature_2m"].astype(float)
    out["td"]    = df["dew_point_2m"].astype(float)
    # se l'API non restituisce RH usiamo formula da T e Td
    if "relative_humidity_2m" in df.columns:
        out["rh"] = df["relative_humidity_2m"].astype(float)
    else:
        # Magnus-Tetens
        def rh_from_t_td(T, Td):
            a,b = 17.625, 243.04
            es = 6.1094*np.exp(a*T/(b+T))
            e  = 6.1094*np.exp(a*Td/(b+Td))
            return np.clip(100*e/es, 1, 100)
        out["rh"] = rh_from_t_td(out["T2m"], out["td"])
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["snowfall"] = extra["snowfall"].astype(float)
    out["rain"]     = extra["rain"].astype(float)
    return out

# neve superficiale più realistica (evita 0 fisso)
def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1

    # quota "bagnato": funzione morbida di T>0, pioggia e RH
    warm = (df["T2m"] > 0).astype(float)
    wet_intensity = (df["rain"].fillna(0) + 0.5*df["prp_mmph"]).clip(0, 3)/3.0
    rh_factor = (df["rh"].clip(60,100)-60)/40.0
    wet_frac = np.clip(0.4*warm + 0.5*wet_intensity + 0.2*rh_factor + 0.2*(snow & df["T2m"].ge(-1)).astype(float), 0, 1)

    # radiazione/vento: raffredda la superficie a secco
    clear = (1.0 - df["cloud"]).clip(0,1)
    windc = df["wind"].clip(upper=6.0)
    drad = (1.2 + 3.0*clear - 0.25*windc).clip(0.4, 4.0)

    # T_surf: mix tra 0°C (bagnato) e T2m - drad (secco)
    T_dry = df["T2m"] - drad
    T_wet = np.clip( -0.5 + 0.5*(1-wet_frac), -0.5, 0.0)   # tra -0.5 e 0.0
    T_surf = (wet_frac*T_wet) + ((1-wet_frac)*T_dry)
    # se molto freddo e soleggiato diurno, attenua l'eccesso di raffreddamento
    sunny_cold = sunup & (df["T2m"].between(-12, -2))
    T_surf[sunny_cold] = np.maximum(T_surf[sunny_cold], df["T2m"][sunny_cold] - 2.0)

    # strato 0-5 mm con inerzia
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)  # ore
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)  # base iniziale
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i] - T_top5.iloc[i-1])

    out = df.copy()
    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    out["wet_frac"] = wet_frac
    return out

def window_slice_by_date(res, tzname, day_date, s, e):
    t = res["time"].dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==day_date) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W

# =============== WAX BANDS & STRUTTURE (nomi) ===============
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]

BRANDS = [
    ("Swix", SWIX), ("Toko", TOKO), ("Vola", VOLA), ("Rode", RODE),
    ("Holmenkol", HOLM), ("Maplus", MAPL), ("Start", START), ("Skigo", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def structure_name_for(Tsurf):
    # nomi fissi (niente immagini)
    if Tsurf <= -10:
        return "Linear Fine (freddo/secco)"
    elif Tsurf <= -3:
        return "Cross Hatch / Wave leggera (universale)"
    else:
        return "Diagonal / V (umido/caldo)"

def angles_for(Tsurf, discipline):
    # Angolo SIDE (espresso direttamente in °) e BASE
    if Tsurf <= -10:
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif Tsurf <= -3:
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        base = 0.8 if Tsurf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return side_map.get(discipline, 88.0), base

# =============== CONDIZIONI + AFFIDABILITÀ + INDICE SCORREVOLEZZA ===============
def classify_conditions(W: pd.DataFrame):
    if W.empty:
        return "Dati insufficienti", 0.35, 40
    t = W["T_surf"].mean()
    prp = W["prp_mmph"].mean()
    typ = W["prp_type"].mode().iat[0] if not W["prp_type"].mode().empty else "none"
    rh  = W["rh"].mean()
    wind= W["wind"].mean()
    snowf = W["snowfall"].sum()

    # descrizione
    if typ in ("rain","mixed") or t>-0.3:
        desc = "Neve bagnata/calda"
    elif snowf>0.6 and t<0:
        desc = "Neve nuova"
    elif t<=-8:
        desc = "Neve molto fredda/secca"
    elif (prp<0.2) and (rh<70) and (-6<=t<=-2):
        desc = "Neve compatta/trasformata"
    else:
        desc = "Neve variabile"

    # affidabilità (0-1): più alta se bassa nuvolosità/precipitazione e coerenza segnali
    cloud = W["cloud"].mean()
    wet_var = W["wet_frac"].std() if "wet_frac" in W else 0.15
    base_rel = 0.85 - 0.35*cloud - 0.25*np.tanh(prp)
    base_rel -= 0.15*min(1,wet_var*3)
    base_rel = float(np.clip(base_rel, 0.2, 0.95))

    # indice di scorrevolezza (0-100): meglio con T_surf tra -8 e -2, bassa prp, vento moderato
    score = 55.0
    # temperatura “ideale”
    temp_bonus = 20.0 * np.exp(-((t+5.0)**2)/(2*2.5**2))  # gauss centrato a -5°C
    score += temp_bonus
    # penalità precipitazione
    score -= 18.0 * np.tanh(prp)
    # vento troppo alto peggiora
    score -= 8.0 * max(0.0, (wind-5)/5.0)
    # umidità molto alta o t vicino a 0 peggiora
    score -= 10.0 * max(0.0, (rh-90)/10.0)
    score -= 8.0 * max(0.0, t+0.5)
    score = int(np.clip(score, 5, 95))

    return desc, base_rel, score

# =============== UI: RICERCA LOCALITÀ + DATA ===============
st.markdown("### 1) Località e giorno")

selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi e scegli… (es. Champoluc, Plateau Rosa, Cervinia)",
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
st.markdown(f"<div class='kpi'><span class='lab'>Località:</span> <span class='val'>{place_label}</span>{alt_txt}</div>", unsafe_allow_html=True)

col_date, col_h = st.columns([1,1])
with col_date:
    day = st.date_input("Giorno", value=dt.date.today())
with col_h:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# =============== FINESTRE A/B/C ===============
st.markdown("### 2) Finestre orarie (oggi o giorno selezionato)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", dt.time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   dt.time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", dt.time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   dt.time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", dt.time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   dt.time(16,0), key="C_e")

# =============== RUN ===============
st.markdown("### 3) Meteo & tuning")
go = st.button("Scarica previsioni e calcola", type="primary")

if go:
    try:
        tzname = "Europe/Rome"
        js = fetch_open_meteo(lat, lon, tzname)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        st.success(f"Dati per **{place_label}** caricati.")
        # Tabella più chiara (campi essenziali, formattati)
        df_show = res.copy()
        df_show["Ora"] = df_show["time"].dt.tz_localize(tz.gettz(tzname)).dt.strftime("%d/%m %H:%M")
        df_show = df_show[["Ora","T2m","td","rh","cloud","wind","prp_mmph","prp_type","T_surf","T_top5"]]
        df_show = df_show.rename(columns={
            "T2m":"T aria (°C)",
            "td":"T rugiada (°C)",
            "rh":"UR (%)",
            "cloud":"Copertura",
            "wind":"Vento (m/s)",
            "prp_mmph":"Prec. (mm/h)",
            "prp_type":"Tipo",
            "T_surf":"T neve sup. (°C)",
            "T_top5":"T top 5 mm (°C)"
        })
        st.dataframe(
            df_show.style.format({
                "T aria (°C)":"{:.1f}","T rugiada (°C)":"{:.1f}",
                "UR (%)":"{:.0f}",
                "Copertura":"{:.0%}",
                "Vento (m/s)":"{:.1f}",
                "Prec. (mm/h)":"{:.2f}",
                "T neve sup. (°C)":"{:.1f}",
                "T top 5 mm (°C)":"{:.1f}",
            }),
            use_container_width=True, height=360
        )

        # Grafici rapidi
        t = res["time"]
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve sup."); plt.plot(t,res["T_top5"],label="T top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # Blocchi A/B/C per il giorno selezionato
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"---\n### Blocco {L} — {day.strftime('%d/%m/%Y')}")
            W = window_slice_by_date(res, tzname, day, s, e)
            if W.empty:
                st.info("Nessun dato nella finestra selezionata per questo giorno.")
                continue

            t_med = float(W["T_surf"].mean())
            desc, rel, glide = classify_conditions(W)

            # Banner condizioni + KPI
            st.markdown(f"<div class='banner'><b>Condizioni:</b> {desc} · <b>T neve media:</b> {t_med:.1f}°C</div>", unsafe_allow_html=True)
            kc1, kc2 = st.columns(2)
            with kc1:
                st.markdown(f"<div class='kpi'><span class='lab'>Indice di scorrevolezza:</span> <span class='val' style='color:{OK if glide>=60 else (WARN if glide>=40 else DANGER)}'>{glide}/100</span></div>", unsafe_allow_html=True)
            with kc2:
                st.markdown(f"<div class='kpi'><span class='lab'>Affidabilità stima:</span> <span class='val'>{int(rel*100)}%</span></div>", unsafe_allow_html=True)

            # Scioline: 8 marchi
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(name,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(f"<div class='brand'><div style='font-weight:800;color:{ACCENT}'>{name}</div><div>{rec}</div></div>", unsafe_allow_html=True)
            for i,(name,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(f"<div class='brand'><div style='font-weight:800;color:{ACCENT}'>{name}</div><div>{rec}</div></div>", unsafe_allow_html=True)

            # Struttura (solo nome) + Angoli per discipline
            st.markdown(f"**Struttura consigliata (nome):** {structure_name_for(t_med)}")

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = angles_for(t_med, d)
                rows.append([d, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
