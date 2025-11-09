# telemark_pro_app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time, datetime, timedelta, date
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- THEME --------------------
PRIMARY = "#10bfcf"   # Telemark turquoise
ACCENT  = "#f97316"   # orange for highlights
OK      = "#22c55e"
WARN    = "#f59e0b"
BAD     = "#ef4444"
TEXT    = "#e5e7eb"
BG1     = "#0b1220"
BG2     = "#0f172a"
BORDER  = "rgba(255,255,255,.10)"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --primary:{PRIMARY}; --accent:{ACCENT}; }}
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 600px at 30% -10%, #122033 0%, {BG1} 40%), linear-gradient(180deg,{BG1} 0%, {BG2} 100%); }}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color:{TEXT}; }}
hr {{ border:none;border-top:1px solid {BORDER}; margin:.6rem 0 .4rem }}
.card {{ background: rgba(255,255,255,.03); border:1px solid {BORDER}; border-radius:16px; padding:14px; }}
.badge {{ display:inline-block; border:1px solid {BORDER}; background:rgba(16,191,207,.08);
         padding:.35rem .55rem; border-radius:999px; font-size:.78rem; color:#bfeaff; }}
.brand {{ display:flex;align-items:center;gap:.75rem;background:rgba(255,255,255,.03);
          border:1px solid {BORDER};border-radius:12px;padding:.5rem .75rem; }}
.brand img {{ height:22px; }}
.kpi {{ display:flex;gap:.5rem;align-items:center;background:rgba(0,0,0,.25);
       border:1px dashed {BORDER}; padding:.4rem .6rem; border-radius:10px; }}
.kpi .lab {{ font-size:.78rem; opacity:.8 }}
.kpi .val {{ font-size:1rem; font-weight:800 }}
.banner {{
  border:1px solid {BORDER}; border-radius:14px; padding:.65rem .9rem; display:flex; gap:.7rem; align-items:center;
  background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.03));
}}
.banner.ok {{ box-shadow:0 0 0 1px {OK} inset; }}
.banner.warn {{ box-shadow:0 0 0 1px {WARN} inset; }}
.banner.bad {{ box-shadow:0 0 0 1px {BAD} inset; }}
.small {{ font-size:.86rem; opacity:.9 }}
table tbody tr td, table thead tr th {{ color:{TEXT}; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")

# -------------------- HELPERS --------------------
def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

COUNTRY_LIST = [
    ("IT","Italia"),("CH","Svizzera"),("FR","Francia"),
    ("AT","Austria"),("DE","Germania"),("SE","Svezia"),
    ("NO","Norvegia"),("FI","Finlandia")
]

def concise_label(addr:dict, disp:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or addr.get("municipality") or disp.split(",")[0])
    region = addr.get("state") or addr.get("region") or addr.get("province") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, region] if p]
    short = ", ".join(parts)
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: 
        return []
    ccodes = st.session_state.get("country_code","")
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1, "countrycodes": ccodes.lower()},
            headers={"User-Agent":"telemark-wax-pro/1.0"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._options = {}
        out = []
        for it in r.json():
            addr = it.get("address",{}) or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = addr.get("country_code","")
            lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
            key = f"{flag(cc)}  {label_short} ||| {lat:.5f},{lon:.5f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"addr":addr,"label_short":label_short,"cc":cc}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); j = r.json()
        if j and "elevation" in j and j["elevation"]:
            return float(j["elevation"][0])
    except: pass
    return None

def fetch_open_meteo(lat, lon, tzname):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,dew_point_2m,relativehumidity_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status(); return r.json()

# precipitation type
def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(r):
        prp = r.precipitation
        rain = getattr(r,"rain",0.0); snow = getattr(r,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(r,"weathercode",0)) if pd.notna(getattr(r,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours, tzname):
    H = pd.DataFrame(js["hourly"])
    H["time"] = pd.to_datetime(H["time"])                    # tz-naive in local tz string from API
    now_local = pd.Timestamp.now(tz=tz.gettz(tzname)).floor("H").tz_localize(None)
    H = H[H["time"] >= now_local].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = H["time"]
    out["T2m"] = H["temperature_2m"].astype(float)
    out["td"]  = H["dew_point_2m"].astype(float)
    out["rh"]  = H["relativehumidity_2m"].astype(float)      # %
    out["cloud"] = (H["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (H["windspeed_10m"].astype(float)/3.6).round(3)   # m/s
    out["sunup"] = H["is_day"].astype(int)
    out["prp_mmph"] = H["precipitation"].astype(float)
    extra = H[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

# --- Snow surface temperature model (compact, stable) ---
def compute_snow_temperature(df: pd.DataFrame, tzname:str, dt_hours=1.0) -> pd.DataFrame:
    X = df.copy()
    # radiative + ventilation cooling estimate (°C)
    clear = (1.0 - X["cloud"]).clip(0,1)
    windc = X["wind"].clip(upper=7.0)
    rad_cool = (1.1 + 2.6*clear - 0.25*windc).clip(0.3, 4.2)  # typical night enhancement

    # wetness weights: move surface towards 0°C without forcing a hard 0
    rain = X["prp_type"].str.lower().eq("rain")
    mixed = X["prp_type"].str.lower().eq("mixed")
    snow  = X["prp_type"].str.lower().eq("snow")
    sunup = X["sunup"].astype(int).eq(1)
    near0 = X["T2m"].between(-0.8, 0.8)

    # target surface temperature
    Ts_dry   = X["T2m"] - rad_cool
    wet_push = np.zeros(len(X))
    wet_push[rain|mixed] = 0.9
    wet_push[snow & X["T2m"].gt(-1.0)] = 0.6
    wet_push[(sunup & X["T2m"].gt(-3) & (X["cloud"]<0.35))] = np.maximum(wet_push[(sunup & X["T2m"].gt(-3) & (X["cloud"]<0.35))], 0.3)
    Ts_target = (1-wet_push)*Ts_dry + wet_push*np.minimum(0.0, X["T2m"]*0.35)

    # relaxation to target (top ~5mm)
    tau = np.full(len(X), 6.0)        # hours
    tau[rain|snow|mixed] = 3.0
    tau[(~sunup) & (X["wind"]<2) & (X["cloud"]<0.3)] = 8.0
    alpha = 1.0 - np.exp(-dt_hours/np.maximum(tau, 0.5))     # 0..1

    T_top = np.zeros(len(X))
    if len(X)>0:
        T_top[0] = np.minimum(X["T2m"].iloc[0], 0.0)
        for i in range(1,len(X)):
            T_top[i] = T_top[i-1] + alpha[i]*(Ts_target.iloc[i] - T_top[i-1])

    X["T_surf"] = np.minimum(0.0, T_top)                     # never above 0
    # simple glide index (0..100): best ~ -6/-3, penalize wet (rh high & near0) and heavy precip
    base = 70 - 6*np.abs(X["T_surf"].clip(-12,2) + 4.5)      # peak around -4.5
    wet_pen = (X["rh"]/100.0)*np.clip(0.8 - np.abs(X["T_surf"]+0.2), 0, 0.8)*40
    prp_pen = np.clip(X["prp_mmph"], 0, 2.0)*12
    glide = np.clip(base - wet_pen - prp_pen, 0, 100)
    X["glide_idx"] = glide.round(0)

    return X

# --- Window slicing by chosen date ---
def window_slice(res, tzname, target_date: date, s: time, e: time):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    mask = (D["dt"].dt.date == target_date) & (D["dt"].dt.time >= s) & (D["dt"].dt.time <= e)
    W = D.loc[mask]
    return W if not W.empty else D.iloc[:0]

# -------------------- WAX bands & structures (names only) --------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
BRANDS = [("Swix","assets/brands/swix.png", SWIX),
          ("Toko","assets/brands/toko.png", TOKO),
          ("Vola","assets/brands/vola.png", VOLA),
          ("Rode","assets/brands/rode.png", RODE)]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_or_text(name, path):
    if os.path.exists(path):
        b64 = base64.b64encode(open(path,"rb").read()).decode("utf-8")
        return f"<img src='data:image/png;base64,{b64}'/>"
    return f"<div style='font-weight:700'>{name}</div>"

def tune_structure_name(t_surf):
    if t_surf <= -10:   return "Linear Fine (freddo/secco)"
    if t_surf <= -3:    return "Cross Hatch / Universale leggera"
    return "Diagonal / Scarico caldo-umido"

def snow_descriptor(window_df: pd.DataFrame) -> tuple[str,str,float]:
    if window_df.empty:
        return ("Dati insufficienti","warn",50.0)
    Tm  = float(window_df["T_surf"].mean())
    rhm = float(window_df["rh"].mean())
    prp = float(window_df["prp_mmph"].mean())
    snow_rate = float((window_df["prp_type"].str.lower()=="snow").astype(int).mean())

    # condizioni
    if prp>0.2 and snow_rate>0.5 and Tm<=-1.0:
        label = "Neve nuova/soffice"; tone="ok"
    elif Tm>-0.5 and (rhm>85 or prp>0.2):
        label = "Bagnata/primaverile"; tone="bad"
    elif Tm<-8:
        label = "Freddo/Secco"; tone="warn"
    else:
        label = "Trasformata/Compatta"; tone="ok"

    # affidabilità (più alta con cielo stabile, poco prp, orizzonte breve)
    cc_var = float(window_df["cloud"].std()) if len(window_df)>1 else 0.2
    horizon_h = len(window_df)
    reliab = 85 - 35*cc_var - 15*np.clip(prp,0,1) - 0.1*horizon_h
    reliab = float(np.clip(reliab, 35, 95))
    return (label, tone, reliab)

# -------------------- UI: 1) Località --------------------
st.subheader("1) Località")
colA, colB = st.columns([1,2.2])
with colA:
    c_label = st.selectbox("Paese", [f"{flag(cc)} {name} ({cc})" for cc,name in COUNTRY_LIST], index=0)
    st.session_state["country_code"] = c_label.split("(")[-1].strip(")")

with colB:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Scrivi e premi Invio… es. Champoluc, Plateau Rosa, Cervinia",
        clear_on_submit=False,
        default=None
    )

# default/fallback
lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
label_short = st.session_state.get("label_short", "Champoluc, Valle d’Aosta — IT")
cc = st.session_state.get("cc", "IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, label_short, cc = info["lat"], info["lon"], info["label_short"], info["cc"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon
        st.session_state["label_short"]=label_short; st.session_state["cc"]=cc

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {flag(cc)} {label_short}{alt_txt}")

# -------------------- UI: 2) Giorno + Finestre --------------------
st.subheader("2) Giorno e finestre A · B · C")
left, right = st.columns([1.3,2.7])

with left:
    tzname = "Europe/Rome"  # fisso; niente toggle
    # scelta giorno (oggi + 6)
    today = date.today()
    days = [today + timedelta(days=i) for i in range(0,7)]
    day_sel = st.selectbox("Giorno", [d.strftime("%a %d %b") for d in days], index=0)
    target_date = days[[d.strftime("%a %d %b") for d in days].index(day_sel)]

with right:
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

# orizzonte (per tabella/plot): massimo 24h per il giorno scelto
hours = st.slider("Orizzonte orario (max per il giorno scelto)", 6, 24, 12, 6)

# -------------------- UI: 3) Meteo + Calcolo --------------------
st.subheader("3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")
if go:
    try:
        js  = fetch_open_meteo(lat, lon, tzname)
        src = build_df(js, hours=24*7, tzname=tzname)     # scarico lungo, poi filtro
        res = compute_snow_temperature(src, tzname, dt_hours=1.0)

        # tabella compatta per l’orizzonte del giorno scelto
        horizon = window_slice(res, tzname, target_date, time(0,0), time(23,59))
        horizon = horizon.head(hours).reset_index(drop=True)

        if horizon.empty:
            st.warning("Nessun dato disponibile per il giorno selezionato.")
        else:
            st.success(f"Dati per **{label_short}** ({target_date.strftime('%a %d %b')}) caricati.")

            # tabella chiara
            show = horizon[["time","T2m","td","rh","wind","prp_mmph","prp_type","T_surf","glide_idx"]].copy()
            show.columns = ["Ora locale","T aria (°C)","Dew-point (°C)","Umidità (%)","Vento (m/s)","Prec. (mm/h)","Tipo","T neve (°C)","Indice di scorrevolezza"]
            show["Ora locale"] = pd.to_datetime(show["Ora locale"]).dt.strftime("%H:%M")
            numeric_cols = ["T aria (°C)","Dew-point (°C)","Umidità (%)","Vento (m/s)","Prec. (mm/h)","T neve (°C)","Indice di scorrevolezza"]
            show[numeric_cols] = show[numeric_cols].apply(pd.to_numeric, errors="coerce")
            show["T aria (°C)"] = show["T aria (°C)"].round(1)
            show["Dew-point (°C)"] = show["Dew-point (°C)"].round(1)
            show["Umidità (%)"] = show["Umidità (%)"].round(0)
            show["Vento (m/s)"] = show["Vento (m/s)"].round(1)
            show["Prec. (mm/h)"] = show["Prec. (mm/h)"].round(2)
            show["T neve (°C)"] = show["T neve (°C)"].round(1)
            st.dataframe(show, use_container_width=True)

            # grafici sintetici
            t = pd.to_datetime(horizon["time"])
            fig1 = plt.figure(); plt.plot(t,horizon["T2m"],label="T aria"); plt.plot(t,horizon["T_surf"],label="T neve"); plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
            fig2 = plt.figure(); plt.bar(t,horizon["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

            # --- Blocchi A/B/C ---
            blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
            for L,(s,e) in blocks.items():
                st.markdown(f"---\n### Blocco {L}")
                W = window_slice(res, tzname, target_date, s, e)

                if W.empty:
                    st.info("Nessun dato in questa finestra.")
                    continue

                t_med = float(W["T_surf"].mean())
                rh_med = float(W["rh"].mean())
                gi_med = float(W["glide_idx"].mean())
                st.markdown(
                    f"<div class='kpi'><div class='lab'>T_surf medio</div><div class='val'>{t_med:.1f}°C</div>"
                    f"<div class='lab'>Umidità</div><div class='val'>{rh_med:.0f}%</div>"
                    f"<div class='lab'>Indice di scorrevolezza</div><div class='val'>{gi_med:.0f}</div></div>",
                    unsafe_allow_html=True
                )

                # banner condizioni + affidabilità
                label, tone, reliab = snow_descriptor(W)
                tone_cls = {"ok":"ok","warn":"warn","bad":"bad"}.get(tone,"warn")
                st.markdown(f"<div class='banner {tone_cls}'><b>Condizioni:</b> {label} · <span class='small'>Affidabilità {reliab:.0f}%</span></div>", unsafe_allow_html=True)

                # scioline (4 brand)
                cols1 = st.columns(4)
                for i,(name,path,bands) in enumerate(BRANDS):
                    rec = pick(bands, t_med)
                    cols1[i].markdown(
                        f"<div class='brand'>{logo_or_text(name,path)}<div><div class='small'>{name}</div><div style='font-weight:800'>{rec}</div></div></div>",
                        unsafe_allow_html=True
                    )

                # struttura consigliata
                st.markdown(f"**Struttura consigliata:** {tune_structure_name(t_med)}")

                # angoli per discipline (tabella fissa, niente toggle)
                def tune_for(t, d):
                    if t <= -10:
                        base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
                    elif t <= -3:
                        base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
                    else:
                        base = 0.8 if t<=0.5 else 1.0
                        side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
                    return side, base

                rows=[]
                for d in ["SL","GS","SG","DH"]:
                    side,base = tune_for(t_med, d)
                    rows.append([d, f"{side:.1f}°", f"{base:.1f}°"])
                st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"]))

            # export csv
            st.download_button("Scarica CSV (orizzonte giorno)", data=horizon.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
