# telemark_pro_app.py
import math, base64, os
from datetime import date, time, datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ------------------------- THEME -------------------------
ACCENT = "#10bfcf"  # Telemark turquoise
DANGER = "#ef4444"
OK     = "#22c55e"
MUTED  = "#94a3b8"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --acc:{ACCENT}; --muted:{MUTED}; --ok:{OK}; --bad:{DANGER};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: #0b1220;
}}
.block-container {{ padding-top: 0.75rem; }}
h1,h2,h3, label, p, span, div {{ color:#eef2ff; }}
.small, .muted {{ color:var(--muted); font-size:.9rem }}
.badge {{
  display:inline-flex; gap:.35rem; align-items:center;
  background: rgba(16,191,207,.10); color:#e2f8fb;
  border:1px solid rgba(16,191,207,.35);
  padding:.25rem .55rem; border-radius:999px; font-size:.78rem; font-weight:600;
}}
.card {{
  background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
  border-radius:14px; padding:14px;
}}
.kpi {{
  display:flex; gap:8px; align-items:center; justify-content:space-between;
  background: linear-gradient(180deg, rgba(16,191,207,.10), rgba(255,255,255,.04));
  border:1px solid rgba(16,191,207,.30); padding:10px 12px; border-radius:12px;
}}
.kpi .lab {{ color:#a5b4fc; font-size:.82rem }}
.kpi .val {{ font-weight:800; font-size:1.05rem }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.10); margin:.5rem 0 1rem }}
.stSlider > div > div > div[role=slider] {{ background: var(--acc) !important; border: 2px solid white; }}
.stButton>button {{ background: #ef4444; border:0; color:white; font-weight:700 }}
.brand {{
  display:flex;align-items:center;gap:.75rem;background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:.5rem .75rem;
}}
.brand .name {{ color:#e2e8f0; font-size:.86rem }}
.brand .rec {{ font-weight:800 }}
.banner {{
  background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.12);
  border-left:5px solid var(--acc); padding:10px 12px; border-radius:12px;
}}
</style>
""", unsafe_allow_html=True)

st.markdown("<h2>Telemark · Pro Wax & Tune</h2>", unsafe_allow_html=True)

# ------------------------- HELPERS -------------------------
COUNTRIES = {
    "Italia": "Italy", "Svizzera": "Switzerland", "Francia": "France",
    "Austria": "Austria", "Germania":"Germany", "Norvegia":"Norway",
    "Svezia":"Sweden"
}

def flag(cc:str)->str:
    try:
        cc = cc.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # Nome breve + regione
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    out = f"{name}, {admin1}".strip().strip(", ")
    if cc: out += f" — {cc}"
    return out

def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        e = r.json().get("elevation",[None])[0]
        return int(e) if e is not None else None
    except:
        return None

def nominatim_search(q:str):
    if not q or len(q)<2: return []
    country = st.session_state.get("country_name","")
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
            params={"q": f"{q}, {country}" if country else q, "format":"json",
                    "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
        r.raise_for_status()
        st.session_state._opts = {}
        out=[]
        for it in r.json():
            addr = it.get("address") or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = (addr.get("country_code") or "").upper()
            lat = float(it["lat"]); lon = float(it["lon"])
            key = f"{flag(cc)} {label_short}|||{lat:.6f},{lon:.6f}"
            st.session_state._opts[key] = {"lat":lat,"lon":lon,"addr":addr,"label":label_short}
            out.append(key)
        return out
    except:
        return []

def fetch_open_meteo(lat, lon):
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "hourly": ",".join([
            "temperature_2m","dew_point_2m","relative_humidity_2m",
            "precipitation","rain","snowfall","cloudcover",
            "windspeed_10m","is_day","weathercode"
        ]),
        "forecast_days": 7
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def prp_type_row(row):
    prp = float(row.get("precipitation",0) or 0)
    rain = float(row.get("rain",0) or 0)
    snow = float(row.get("snowfall",0) or 0)
    if prp<=0: return "none"
    if rain>0 and snow>0: return "mixed"
    if snow>0: return "snow"
    if rain>0: return "rain"
    return "mixed"

def build_df(js:dict)->pd.DataFrame:
    h = js["hourly"]
    df = pd.DataFrame(h)
    # orari già in timezone locale "auto"
    df["time"] = pd.to_datetime(df["time"])  # naive, locale
    df.rename(columns={
        "temperature_2m":"T2m",
        "dew_point_2m":"Td",
        "relative_humidity_2m":"RH",
        "cloudcover":"cloud",
        "windspeed_10m":"wind",
        "is_day":"sunup"
    }, inplace=True)
    df["cloud"] = (df["cloud"].astype(float)/100.0).clip(0,1)
    df["wind"]  = (df["wind"].astype(float)/3.6).clip(lower=0)   # m/s
    df["RH"]    = df["RH"].astype(float).clip(0,100)
    df["T2m"]   = df["T2m"].astype(float)
    df["Td"]    = df["Td"].astype(float)
    df["sunup"] = df["sunup"].astype(int)
    df["precipitation"] = df["precipitation"].astype(float)
    df["rain"] = df["rain"].astype(float)
    df["snowfall"] = df["snowfall"].astype(float)
    df["prp_type"] = df.apply(prp_type_row, axis=1)
    return df

# --- Snow/Surface model (semplificato ma fisico) ---
def compute_surface(df:pd.DataFrame)->pd.DataFrame:
    out = df.copy()
    # probabilità di bagnato (0..1) usando T vicino a 0, Td, RH, prp, is_day, cloud
    x = (
        0.9*(out["T2m"]/2.5).clip(-4,4) +           # più caldo => più bagnato
        0.8*((out["Td"]+1.0)/2.0).clip(-4,4) +       # Td vicino 0 => bagnato
        0.8*((out["RH"]-80)/10).clip(-4,4) +         # RH alta
        1.2*(out["precipitation"]>0).astype(int) +   # precipitazione
        0.6*((out["prp_type"]=="rain") | (out["prp_type"]=="mixed")).astype(int) +
        0.3*(out["sunup"]==1).astype(int)*(1.0-out["cloud"]).clip(0,1)  # radiazione
    )
    wet_p = 1/(1+pd.Series((-x).apply(math.exp)))  # logistic
    wet_p = wet_p.clip(0,1)

    # base: T_surf tende a 0°C se bagnato, altrimenti scende sotto T2m con raffreddamento radiativo
    clear = (1.0 - out["cloud"]).clip(0,1)
    windc = out["wind"].clip(upper=8.0)
    # coeff di raffreddamento notturno/sereno e diurno/nuvoloso
    rad_cool = (1.3 + 3.2*clear - 0.25*windc).clip(0.3, 4.8)
    T_surf_dry = out["T2m"] - rad_cool                                  # secco
    T_surf = (1-wet_p)*T_surf_dry + wet_p*0.0                           # mix bagnato→0

    # Relaxation verso T_surf per i primi 5mm (inerzia)
    tau = pd.Series(6.0, index=out.index)
    tau.loc[(out["precipitation"]>0) | (out["wind"]>=6)] = 3.0
    tau.loc[(out["sunup"]==0) & (out["wind"]<2) & (out["cloud"]<0.3)] = 8.0
    alpha = 1.0 - pd.Series(((-1.0/tau).apply(math.exp)))
    T_top5 = pd.Series(index=out.index, dtype=float)
    if len(out)>0:
        T_top5.iloc[0] = min(out["T2m"].iloc[0], 0.0)
        for i in range(1, len(out)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    out["wet_p"]   = wet_p
    out["T_surf"]  = T_surf.round(2)
    out["T_top5"]  = T_top5.round(2)
    # stima acqua libera (%) ~ funzione di wet_p e T sopra -0.5
    wl = (wet_p * (out["T_surf"]+0.5).clip(lower=0) * 20).clip(0,30)
    out["water_free_%"] = wl.round(1)
    return out

def classify_snow_row(r):
    if r["precipitation"]>0 and r["prp_type"]=="snow" and r["T_surf"]<=-1:
        return "Polvere fredda"
    if r["precipitation"]>0 and r["prp_type"]=="snow" and r["T_surf"]>-1:
        return "Neve nuova umida"
    if r["wet_p"]>0.7 and r["T_surf"]>-0.2:
        return "Bagnata/Primaverile"
    if r["wet_p"]>0.4 and r["T_surf"]>-1.0:
        return "Trasformata umida"
    if r["sunup"]==0 and r["T_surf"]<-2 and r["water_free_%"]<2:
        return "Rigelata"
    if r["snowfall"]==0 and r["precipitation"]==0 and -2<=r["T_surf"]<=0 and r["wind"]>5:
        return "Crosta/compattata"
    return "Trasformata"

def reliability_row(r):
    base = 0.65
    base += 0.15*(r["precipitation"]>0)
    base += 0.10*(r["cloud"]>0.5)
    base -= 0.10*(r["wind"]>7)
    base -= 0.10*(abs(r["T2m"]-r["Td"])>5)
    return int((100*max(0.35, min(0.95, base))))

def glide_index_row(r):
    # 0-100, più alto = più scorrevole
    g = 35 + 1.6*r["water_free_%"] + 0.8*max(0, -r["T_surf"]) + 1.2*min(8, r["wind"])
    g -= 8.0*(r["snowfall"]>0)  # neve nuova più “frenante”
    return int(max(5, min(98, g)))

# --------------------- WAX BANDS -------------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Warm",-2,10)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),
          ("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def tune_for(t_surf, disc):
    # struttura (solo nome) + angoli suggeriti
    if t_surf <= -10:
        structure = "Lineare fine (freddo/secco)"
        base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}.get(disc,88.0)
    elif t_surf <= -3:
        structure = "Cross/Universale"
        base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}.get(disc,88.0)
    else:
        structure = "Diagonale/V (umido/caldo)"
        base = 0.8 if t_surf<=0.5 else 1.0
        side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}.get(disc,88.0)
    return structure, side, base

# --------------------- UI: Ricerca -----------------------
st.markdown("### 1) Località")
c1, c2 = st.columns([1,3])
with c1:
    country_it = st.selectbox("Nazione (per restringere la ricerca)", list(COUNTRIES.keys()), index=0)
    st.session_state["country_name"] = COUNTRIES[country_it]
with c2:
    selected = st_searchbox(nominatim_search, key="place", placeholder="Digita e premi invio… (es. Plateau Rosa, Champoluc, Cervinia)", clear_on_submit=False, default=None)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
label = st.session_state.get("label","Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected, None)
    if info:
        lat, lon, label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["label"]=label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{elev} m**" if elev else ""
st.markdown(f"<div class='banner'>📍 <b>{label}</b>{alt_txt}</div>", unsafe_allow_html=True)

# --------------------- Finestre + Giorno ------------------
st.markdown("### 2) Finestre orarie A · B · C (giorno scelto)")
cdate, chz = st.columns([1,1])
with cdate:
    target_day = st.date_input("Giorno di riferimento", value=date.today())
with chz:
    hours = st.slider("Orizzonte orario (max per il giorno scelto)", 6, 24, 12, 6)

c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

# --------------------- Meteo & Calcolo -------------------
st.markdown("### 3) Meteo & Analisi neve")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js  = fetch_open_meteo(lat, lon)
        src = build_df(js)
        # filtro per il giorno scelto
        day0 = pd.Timestamp.combine(target_day, time(0,0))
        day1 = day0 + pd.Timedelta(hours=hours)
        srcd = src[(src["time"]>=day0) & (src["time"]<day1)].reset_index(drop=True)
        if srcd.empty:
            st.warning("Nessun dato per il giorno/orizzonte selezionato.")
        else:
            res = compute_surface(srcd)
            # classificazioni, affidabilità, indice scorrevolezza
            res["condizione"]  = res.apply(classify_snow_row, axis=1)
            res["affidabilità_%"] = res.apply(reliability_row, axis=1)
            res["indice_scorrevolezza"] = res.apply(glide_index_row, axis=1)

            st.success(f"Dati caricati per **{label}** ({len(res)} ore).")
            # tabella compatta
            show = res[["time","T2m","Td","RH","cloud","wind","precipitation","snowfall","prp_type","T_surf","T_top5","water_free_%","condizione","affidabilità_%","indice_scorrevolezza"]].copy()
            show.rename(columns={
                "time":"Ora", "RH":"RH (%)","cloud":"Nuvolosità (0-1)","wind":"Vento (m/s)",
                "precipitation":"Prp (mm/h)","snowfall":"Neve (cm/h)","prp_type":"Tipo prp",
                "T2m":"T aria (°C)","Td":"Td (°C)","T_surf":"T superficie (°C)","T_top5":"T top 5mm (°C)",
                "water_free_%":"Acqua libera (%)"
            }, inplace=True)
            st.dataframe(show, use_container_width=True, hide_index=True)

            # Banner sintetico sul primo valore utile (medie finestra)
            def window_slice(df:pd.DataFrame, s:time, e:time)->pd.DataFrame:
                D = df.copy()
                D["t"] = pd.to_datetime(D["time"])
                mask = (D["t"].dt.time>=s) & (D["t"].dt.time<=e)
                return D[mask] if mask.any() else D.head(6)

            blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
            for L,(s,e) in blocks.items():
                W = window_slice(res, s, e)
                t_med = float(W["T_surf"].mean())
                cond  = W["condizione"].mode().iat[0] if not W.empty else "N/D"
                aff   = int(W["affidabilità_%"].mean()) if not W.empty else 0
                glide = int(W["indice_scorrevolezza"].mean()) if not W.empty else 0

                st.markdown(f"---\n#### Blocco {L}")
                st.markdown(f"<div class='banner'>⛷️ <b>Condizione prevalente:</b> {cond} · "
                            f"<b>T_surf media:</b> {t_med:.1f}°C · "
                            f"<b>Affidabilità:</b> {aff}% · "
                            f"<b>Indice di scorrevolezza:</b> {glide}/100</div>",
                            unsafe_allow_html=True)

                # Wax cards per marchi
                cols1 = st.columns(4); cols2 = st.columns(4)
                brands_rows = [cols1, cols2]
                b_iter = iter(BRANDS)
                for row in brands_rows:
                    for i in range(4):
                        try:
                            name, bands = next(b_iter)
                        except StopIteration:
                            break
                        rec = pick(bands, t_med)
                        row[i].markdown(f"<div class='brand'><div class='name'>{name}</div>"
                                        f"<div class='rec'>{rec}</div></div>", unsafe_allow_html=True)

                # Strutture + angoli per 4 discipline
                rows=[]
                for d in ["SL","GS","SG","DH"]:
                    sname, side, base = tune_for(t_med, d)
                    rows.append([d, sname, f"{side:.1f}°", f"{base:.1f}°"])
                st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura consigliata","Lamina SIDE (°)","Lamina BASE (°)"]))
    except Exception as e:
        st.error(f"Errore: {e}")
