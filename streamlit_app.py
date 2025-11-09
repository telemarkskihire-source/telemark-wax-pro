# telemark_pro_app.py
# — Telemark · Pro Wax & Tune (dark, nation prefilter, robust algorithms) —

import math
import base64
from datetime import date, time, datetime, timedelta

import pandas as pd
import numpy as np
import requests
import streamlit as st
import matplotlib.pyplot as plt
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ============================== THEME / UI ==============================
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#f43f5e"   # hot pink/red for CTAs
OK      = "#22c55e"
WARN    = "#f59e0b"
TEXT    = "#e5e7eb"
BG0     = "#0b1220"   # deep night
BG1     = "#0f172a"   # slate-900

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg0:{BG0}; --bg1:{BG1}; --txt:{TEXT}; --primary:{PRIMARY}; --accent:{ACCENT};
}}
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1100px 500px at 10% -10%, #11182755, transparent),
              linear-gradient(180deg, var(--bg0) 0%, var(--bg1) 50%, #0b1220 100%);
}}
.block-container {{ padding-top: 0.6rem; }}
* {{ color: var(--txt) !important; }}
h1,h2,h3,h4 {{ letter-spacing: .2px; }}
.card {{
  background: rgba(15,23,42,.55);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 16px; padding: 14px;
  box-shadow: 0 8px 30px rgba(0,0,0,.35);
}}
.badge {{
  display:inline-flex; align-items:center; gap:.45rem;
  background: linear-gradient(90deg, {PRIMARY}33, {PRIMARY}14);
  border: 1px solid {PRIMARY}66; color:#e6fbff !important;
  padding:.28rem .6rem; border-radius:999px; font-size:.78rem;
}}
.kpi {{
  display:flex; align-items:center; gap:.5rem; padding:.45rem .6rem;
  border-radius:999px; background:#0ea5b714; border:1px dashed #22d3ee99;
}}
.cta > button {{ background:{ACCENT}; border:none; }}
.cta > button:hover {{ filter:brightness(1.07); }}
hr.sep {{ border:none; border-top:1px solid rgba(255,255,255,.08); margin: .8rem 0; }}
.table small {{ opacity:.75; }}
.brand {{ display:flex;align-items:center;gap:.6rem;background:#ffffff0f;
          border:1px solid #ffffff22;border-radius:12px;padding:.5rem .7rem }}
.brand img {{ height:22px }}
.banner {{
  border-radius: 14px; padding: 10px 12px; margin:.4rem 0 0.2rem 0;
  border:1px solid rgba(255,255,255,.08);
}}
.banner.ok {{ background:#16a34a26 }}
.banner.warn {{ background:#f59e0b26 }}
.banner.bad {{ background:#ef444426 }}
</style>
""", unsafe_allow_html=True)

st.markdown("# Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Dark · Meteo + Snow Science · Consigli A/B/C · Scioline multi-brand</span>", unsafe_allow_html=True)

# ============================== HELPERS ==============================
def flag(cc:str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str) -> str:
    # Short: name, region — CC
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s

# ----- SEARCH (Nominatim) with Nation prefilter -----
COUNTRIES = {
    "Italia": "Italy", "Francia":"France", "Svizzera":"Switzerland",
    "Austria":"Austria", "Germania":"Germany", "Norvegia":"Norway",
    "Svezia":"Sweden"
}
col1, col2 = st.columns([1,3])
with col1:
    country_h = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
with col2:
    st.caption("Suggerimento: scrivi *Plateau Rosa, Cervinia, Sestriere…*")

def nominatim_search(q:str):
    if not q or len(q) < 2: 
        return []
    try:
        full_q = f"{q}, {COUNTRIES[country_h]}"
        r = requests.get("https://nominatim.openstreetmap.org/search",
            params={"q": full_q, "format":"json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.1"}, timeout=8)
        r.raise_for_status()
        st.session_state._opts = {}
        st.session_state._last_query = full_q
        out=[]
        for it in r.json():
            addr = it.get("address",{}) or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag(cc)}  {label_short}"
            lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._opts[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
            out.append(key)
        return out
    except:
        return []

st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (Invio userà il primo risultato)",
    clear_on_submit=False, default=None
)

# elevation helper
def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        return float(js["elevation"][0]) if js and js.get("elevation") else None
    except:
        return None

# state for place
if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    if info:
        st.session_state["sel_lat"]=info["lat"]
        st.session_state["sel_lon"]=info["lon"]
        st.session_state["sel_label"]=info["label"]

lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
place_label = st.session_state.get("sel_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""

st.markdown(f"<div class='card kpi'><div>📍 <b>{place_label}</b>{alt_txt}</div></div>", unsafe_allow_html=True)

# ============================== TIME CONTROLS ==============================
st.subheader("2) Finestre e orizzonte")
colA, colB, colC = st.columns(3)
with colA:
    target_day = st.date_input("Giorno di riferimento", value=date.today(), min_value=date.today()-timedelta(days=0), max_value=date.today()+timedata := timedelta(days=6))
with colB:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with colC:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")

colD, colE = st.columns(2)
with colD:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")
with colE:
    # hours available for chosen day
    tz_rome = tz.gettz("Europe/Rome")
    now_ro  = pd.Timestamp.now(tz=tz_rome)
    start_of_day = pd.Timestamp.combine(target_day, time(0,0)).replace(tzinfo=tz_rome)
    end_of_day   = start_of_day + pd.Timedelta(hours=24)
    if target_day == now_ro.date():
        max_hours = int(((end_of_day - now_ro).total_seconds()//3600) or 1)
        min_hours = 6
    else:
        max_hours = 24; min_hours = 6
    hours = st.slider(f"Orizzonte orario (max per il giorno scelto)",
                      min_value=min_hours, max_value=max_hours, value=min(12,max_hours))

# ============================== DATA / ALGORITHMS ==============================
def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    params = dict(
        latitude=lat, longitude=lon, timezone=tzname, forecast_days=7,
        hourly="temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,precipitation_probability,"
               "rain,snowfall,cloudcover,shortwave_radiation,pressure_msl,"
               "windspeed_10m,windgusts_10m,is_day,weathercode"
    )
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def _precip_type_row(row):
    prp   = row.get("precipitation", 0.0)
    rain  = row.get("rain", 0.0)
    snow  = row.get("snowfall", 0.0)
    code  = int(row.get("weathercode", 0) or 0)
    if prp<=0: return "none"
    if rain>0 and snow>0: return "mixed"
    if snow>0 and rain==0: return "snow"
    if rain>0 and snow==0: return "rain"
    # fallback by code
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    if code in snow_codes: return "snow"
    if code in rain_codes: return "rain"
    return "mixed"

def build_df(js, hours, target_day):
    h = js["hourly"]; df = pd.DataFrame(h)
    # tz-aware parse
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(tz.gettz(js.get("timezone","Europe/Rome")), nonexistent='shift_forward', ambiguous='NaT')
    # slice for chosen day & horizon
    tzname = js.get("timezone", "Europe/Rome")
    tzobj = tz.gettz(tzname)
    start_d = pd.Timestamp.combine(target_day, time(0,0)).replace(tzinfo=tzobj)
    end_d   = start_d + pd.Timedelta(hours=24)
    df = df[(df["time"]>=start_d) & (df["time"]<end_d)].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"]   = df["time"]
    out["T2m"]    = df["temperature_2m"].astype(float)
    out["Td"]     = df["dew_point_2m"].astype(float)
    out["RH"]     = df["relative_humidity_2m"].astype(float)  # %
    out["cloud"]  = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]   = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)  # m/s
    out["gust"]   = (df["windgusts_10m"].astype(float)/3.6).clip(lower=0)
    out["rad_sw"] = df.get("shortwave_radiation", pd.Series([0]*len(df))).astype(float)  # W/m2
    out["prp"]    = df["precipitation"].astype(float)
    out["rain"]   = df["rain"].astype(float)
    out["snow"]   = df["snowfall"].astype(float)
    out["pprob"]  = df.get("precipitation_probability", pd.Series([np.nan]*len(df))).astype(float)
    out["is_day"] = df["is_day"].astype(int)
    out["wcode"]  = df["weathercode"].astype(int)

    # precip type
    out["prp_type"] = df[["precipitation","rain","snowfall","weathercode"]].apply(
        lambda r: _precip_type_row(r), axis=1
    )
    return out

def compute_snow_temp(df: pd.DataFrame, dt_hours=1.0) -> pd.DataFrame:
    """Heuristic snow surface & top-5mm temp using bulk terms: radiation, turbulent,
       precipitation phase and liquid water presence. Uses only available predictors."""
    X = df.copy()
    # liquid water presence proxy
    sunup = X["is_day"].eq(1)
    liquid = (X["prp_type"].isin(["rain","mixed"])) | (X["T2m"] > 0.0) | ((X["snow"]>0) & (X["T2m"]>-1))
    # radiative-cooling term (clear nights stronger)
    clear = (1.0 - X["cloud"]).clip(0,1)
    windc = X["wind"].clip(upper=8.0)
    # convert RH to absolute gradient proxy via dewpoint
    tw = (X["T2m"] + X["Td"]) / 2.0

    # base surface target temperature
    T_target = pd.Series(index=X.index, dtype=float)
    # Wet/near-0 regime pinned at melting
    T_target[ liquid ] = 0.0
    # Dry regime: air temp minus a cooling bonus (clear-night radiative, weak wind yields stronger drop)
    cool_bonus = (1.8 + 3.2*clear - 0.25*windc).clip(0.4, 5.5)
    T_target[ ~liquid ] = X["T2m"][~liquid] - cool_bonus[~liquid]
    # Sunny cold daytime may warm slightly but capped below 0
    sunny_cold = sunup & (~liquid) & X["T2m"].between(-15,0, inclusive="both")
    T_target[sunny_cold] = np.minimum(
        (X["T2m"] + 0.7*(1.0 - X["cloud"]))[sunniest := sunny_cold],
        pd.Series(-0.3, index=X.index)[sunniest]
    )

    # time response to get top-5 mm smoothing (variable tau)
    tau = pd.Series(6.0, index=X.index, dtype=float)  # hours
    tau.loc[ liquid | (X["wind"]>=6) | (X["snow"]>0) ] = 3.0
    tau.loc[ (X["is_day"].eq(0)) & (X["wind"]<2) & (X["cloud"]<0.3) ] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)

    T_surf = pd.Series(index=X.index, dtype=float)
    T_top5 = pd.Series(index=X.index, dtype=float)
    if len(X) > 0:
        # initialize with min(air,0)
        T_top5.iloc[0] = min(float(X["T2m"].iloc[0]), 0.0)
        T_surf.iloc[0] = float(T_target.iloc[0])
        for i in range(1, len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_target.iloc[i] - T_top5.iloc[i-1])
            T_surf.iloc[i] = T_target.iloc[i]
    X["T_surf"] = T_surf
    X["T_top5"] = T_top5
    return X

def snow_condition_row(t_surf, prp_t, rh, rad, wind, snowmm):
    # simple rule-set for human label
    if prp_t == "snow" and snowmm > 0.2 and t_surf > -1.5:
        return "Neve fresca / nuova"
    if prp_t in ["rain","mixed"] or t_surf >= -0.2:
        return "Bagnata / primaverile"
    if t_surf <= -8:
        return "Molto fredda e secca"
    if wind >= 6 and t_surf <= -2:
        return "Ventata / compattata"
    if rad > 400 and t_surf < 0 and rh < 70:
        return "Trasformata / granulosa"
    return "Compatta / dura"

def reliability_row(hh_ahead, pprob, cloud):
    base = 85 if hh_ahead <= 12 else 70 if hh_ahead <= 24 else 60
    if np.isnan(pprob): 
        adj = -5
    else:
        adj = - (pprob/100)*15  # high precip prob => lower reliability
    adj += -5*abs(0.5 - cloud)  # extremes of clear or overcast slightly less certain
    return int(np.clip(base + adj, 30, 95))

def glide_index_row(t_surf, rh, prp_t, rad):
    """Indice di scorrevolezza 0–100 (alto = più scorrevole)."""
    base = 50
    # near 0°C with some liquid water improves glide
    if -1.2 <= t_surf <= 0.2:
        base += 18
    elif t_surf < -8:
        base -= 12
    # humidity/radiation contribution
    base += (min(rh,100)-50)/8
    base += min(rad, 600)/1200*10
    # penalties
    if prp_t == "snow": base -= 6
    if prp_t == "rain": base -= 4
    return int(np.clip(base, 5, 95))

# ============================== WAX BANDS ==============================
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]

BRANDS = [
    ("Swix","https://upload.wikimedia.org/wikipedia/commons/7/70/Swix_logo.svg", SWIX),
    ("Toko","https://upload.wikimedia.org/wikipedia/commons/6/6f/Toko_logo.svg", TOKO),
    ("Vola","https://upload.wikimedia.org/wikipedia/commons/3/3a/Vola_Skis_logo.svg", VOLA),
    ("Rode","https://www.rodewax.it/wp-content/uploads/2020/10/logo-rode.png", RODE),
    ("Holmenkol","https://upload.wikimedia.org/wikipedia/commons/7/79/Holmenkol_Logo.svg", HOLM),
    ("Maplus","https://www.maplus.it/wp-content/uploads/2020/09/logo-maplus.svg", MAPL),
    ("Start","https://www.startskiwax.com/img/start-logo.svg", START),
    ("Skigo","https://www.skigo.se/wp-content/uploads/2018/10/skigo-logo.svg", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ============================== ACTION ==============================
st.subheader("3) Meteo & Analisi neve")
st.markdown("<div class='badge'>Scarica i dati quindi leggi raccomandazioni e tabelle</div>", unsafe_allow_html=True)

go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        # fallback: if user pressed without selecting, use first search result from last query
        if "sel_lat" not in st.session_state and st.session_state.get("_opts"):
            first_key = list(st.session_state._opts.keys())[0]
            info = st.session_state._opts[first_key]
            lat, lon, place_label = info["lat"], info["lon"], info["label"]
            st.session_state["sel_lat"]=lat; st.session_state["sel_lon"]=lon; st.session_state["sel_label"]=place_label

        js  = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours, target_day)
        res = compute_snow_temp(src, dt_hours=1.0)

        # Human-friendly banners by hour rows (A/B/C computed later)
        # Summary table
        disp = res.copy()
        disp["Ora"] = disp["time"].dt.strftime("%d/%m %H:%M")
        disp["T aria (°C)"] = disp["T2m"].round(1)
        disp["T neve sup (°C)"] = disp["T_surf"].round(1)
        disp["Umidità (%)"] = disp["RH"].round(0)
        disp["Prp (mm/h)"] = disp["prp"].round(2)
        disp["Vento (m/s)"] = disp["wind"].round(1)
        disp["Cielo"] = (disp["cloud"]*100).round(0).astype(int).astype(str) + "%"
        # derived
        conds=[]; rels=[]; glide=[]
        start_time = disp["time"].iloc[0]
        for i,r in disp.iterrows():
            hh = int((r["time"] - start_time).total_seconds()/3600)
            c = snow_condition_row(r["T_surf"], r["prp_type"], r["RH"], r["rad_sw"], r["wind"], r["snow"])
            conds.append(c)
            rels.append(reliability_row(hh, r["pprob"], r["cloud"]))
            glide.append(glide_index_row(r["T_surf"], r["RH"], r["prp_type"], r["rad_sw"]))
        disp["Condizione neve"] = conds
        disp["Affidabilità (%)"] = rels
        disp["Indice di scorrevolezza"] = glide

        # show table compact
        show = disp[["Ora","T aria (°C)","T neve sup (°C)","Umidità (%)","Prp (mm/h)","Vento (m/s)","Cielo","Condizione neve","Affidabilità (%)","Indice di scorrevolezza"]]
        st.dataframe(show, use_container_width=True)

        # quick plots
        t = res["time"]
        fig1 = plt.figure()
        plt.plot(t,res["T2m"],label="T aria")
        plt.plot(t,res["T_surf"],label="T neve (sup)")
        plt.plot(t,res["T_top5"],label="T neve (0–5mm)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure()
        plt.bar(t,res["prp"], label="Prp mm/h")
        plt.title("Precipitazione"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        # ========== WINDOWS A/B/C ==========
        def slice_window(s: time, e: time):
            mask = (res["time"].dt.time>=s) & (res["time"].dt.time<=e)
            W = res[mask]
            return W if not W.empty else res.head(6)

        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"### Blocco {L} — {s.strftime('%H:%M')}–{e.strftime('%H:%M')}")
            W = slice_window(s,e)
            t_med = float(W["T_surf"].mean())
            rh_med = float(W["RH"].mean())
            wind_m = float(W["wind"].mean())
            prp_t  = W["prp_type"].value_counts().idxmax()
            cond   = snow_condition_row(t_med, prp_t, rh_med, float(W["rad_sw"].mean()), wind_m, float(W["snow"].mean()))
            glide_m= int(np.mean([glide_index_row(r["T_surf"], r["RH"], r["prp_type"], r["rad_sw"]) for _,r in W.iterrows()]))
            rel_m  = int(np.mean([reliability_row(i, r["pprob"], r["cloud"]) for i,(_,r) in enumerate(W.iterrows())]))

            banner_cls = "ok" if "fresca" in cond or glide_m>=65 else "warn" if glide_m>=45 else "bad"
            st.markdown(f"<div class='banner {banner_cls}'>"
                        f"<b>Condizione prevalente:</b> {cond} · "
                        f"<b>T neve media:</b> {t_med:.1f}°C · "
                        f"<b>Indice di scorrevolezza:</b> {glide_m}/100 · "
                        f"<b>Affidabilità:</b> {rel_m}%"
                        f"</div>", unsafe_allow_html=True)

            # Wax cards per brand
            cols1 = st.columns(4); cols2 = st.columns(4)
            allcols = list(cols1)+list(cols2)
            for i,(name,logo_url,bands) in enumerate(BRANDS):
                rec = pick(bands, t_med)
                html = (f"<div class='brand'><img src='{logo_url}'/>"
                        f"<div><div style='opacity:.8;font-size:.78rem'>{name}</div>"
                        f"<div style='font-weight:800'>{rec}</div></div></div>")
                allcols[i].markdown(html, unsafe_allow_html=True)

            # Struttura & angoli (solo nomi, niente immagini)
            def tune_for(t_surf, d):
                if t_surf <= -10:
                    fam = "Lineare fine (freddo/secco)"; base=0.5; sides={"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}
                elif t_surf <= -3:
                    fam = "Incrociata universale / leggera onda"; base=0.7; sides={"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}
                else:
                    fam = "Scarico diagonale/V (umido/caldo)"; base=0.8 if t_surf<=0.5 else 1.0; sides={"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}
                return fam, sides.get(d,88.0), base
            fam_gs, _, _ = tune_for(t_med, "GS")
            st.caption(f"Struttura consigliata (riferimento GS): **{fam_gs}**")
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE","Lamina BASE"]))

        # export
        st.download_button("Scarica CSV completo", data=disp.to_csv(index=False), file_name="telemark_forecast.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
