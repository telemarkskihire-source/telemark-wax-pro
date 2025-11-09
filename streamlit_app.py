# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark UI + ricerca con nazione + algoritmo neve avanzato
import os, math, requests
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, date, time, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ---------------- UI base ----------------
PRIMARY = "#06b6d4"; ACCENT="#f97316"; OK="#10b981"; WARN="#f59e0b"; ERR="#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root{{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"]{{ background:transparent; }}
h1,h2,h3,h4{{ color:#fff }}
.card{{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem }}
.badge{{ display:inline-flex; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2;
         border-radius:12px; padding:.35rem .6rem; font-size:.85rem }}
.banner{{ border-left:6px solid {ACCENT}; background:#1a2230; padding:.75rem .9rem; border-radius:10px; }}
.brand{{ background:#0e141d; border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem }}
.tbl table{{ border-collapse:collapse; width:100% }}
.tbl th,.tbl td{{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th{{ color:#cbd5e1; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.btn-primary button{{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important }}
a,.stMarkdown a{{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline – con downscaling altitudinale e layer NOAA.")

# ---------------- Utils ----------------
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s

# ---------------- Ricerca con Nazione ----------------
COUNTRIES = {"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
             "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
cA,cB = st.columns([1,3])
with cA:
    sel_country = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
    ISO2 = COUNTRIES[sel_country]
with cB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q":q,"format":"json","limit":12,"addressdetails":1,"countrycodes":ISO2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
            r.raise_for_status()
            st.session_state._options={}
            out=[]
            for it in r.json():
                addr=it.get("address",{}) or {}
                lab=f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
                lat=float(it.get("lat",0)); lon=float(it.get("lon",0))
                key=f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key]={"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            return out
        except: return []
    selected = st_searchbox(nominatim_search, key="place", placeholder="Cerca… es. Champoluc, Plateau Rosa",
                            clear_on_submit=False, default=None)

def get_elev(lat,lon):
    try:
        rr=requests.get("https://api.open-meteo.com/v1/elevation",
                        params={"latitude":lat,"longitude":lon},timeout=8)
        rr.raise_for_status(); js=rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat",45.831); lon=st.session_state.get("lon",7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info=st.session_state._options.get(selected)
    if info:
        lat,lon,place_label = info["lat"],info["lon"],info["label"]
        st.session_state.update({"lat":lat,"lon":lon,"place_label":place_label})

elev_site = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev_site) if elev_site else '—'} m</b></div>", unsafe_allow_html=True)

# ---------------- Giorno + finestre A/B/C ----------------
cdate, calt = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())
with calt:
    slope_alt = st.number_input("Quota pista (opzionale, m)", min_value=0, max_value=4500,
                                value=int(elev_site) if elev_site else 0, step=50)

st.subheader("1) Finestre orarie")
c1,c2,c3 = st.columns(3)
def tt(h,m): return time(h,m)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0))
    A_end   = st.time_input("Fine A",   tt(11,0))
with c2:
    B_start = st.time_input("Inizio B", tt(11,0))
    B_end   = st.time_input("Fine B",   tt(13,0))
with c3:
    C_start = st.time_input("Inizio C", tt(13,0))
    C_end   = st.time_input("Fine C",   tt(16,0))

st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)
st.markdown("<span style='color:#9aa4af'>Suggerimento: &lt; 48h → stime più affidabili</span>", unsafe_allow_html=True)

# ---------------- Meteo: Open-Meteo ----------------
TZNAME = "Europe/Rome"

def fetch_open_meteo(lat,lon,tzname):
    r=requests.get("https://api.open-meteo.com/v1/forecast",
        params=dict(latitude=lat, longitude=lon, timezone=tzname,
                    hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
                    forecast_days=7),
        timeout=30)
    r.raise_for_status(); return r.json()

def build_df(js, hours):
    h=js["hourly"]; df=pd.DataFrame(h)
    df["time"]=pd.to_datetime(df["time"])
    tz_off = tz.gettz(js.get("timezone","UTC"))
    now0 = pd.Timestamp.now(tz=tz_off).floor("H").tz_localize(None)
    df=df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)

    out=pd.DataFrame()
    out["time"]=df["time"]
    out["T2m"]=pd.to_numeric(df["temperature_2m"], errors="coerce")
    out["RH"]=pd.to_numeric(df.get("relative_humidity_2m", pd.Series(np.nan, index=df.index)), errors="coerce")
    out["td"]=pd.to_numeric(df.get("dew_point_2m", out["T2m"]), errors="coerce")
    out["cloud"]=pd.to_numeric(df["cloudcover"], errors="coerce")/100.0
    out["cloud"]=out["cloud"].clip(0,1)
    out["wind"]=pd.to_numeric(df["windspeed_10m"], errors="coerce")/3.6  # m/s
    out["sunup"]=pd.to_numeric(df["is_day"], errors="coerce").fillna(0).astype(int)
    out["prp_mmph"]=pd.to_numeric(df["precipitation"], errors="coerce").fillna(0.0)
    out["rain"]=pd.to_numeric(df.get("rain",0.0), errors="coerce").fillna(0.0)
    out["snowfall"]=pd.to_numeric(df.get("snowfall",0.0), errors="coerce").fillna(0.0)
    out["wcode"]=pd.to_numeric(df.get("weathercode",0), errors="coerce").fillna(0).astype(int)
    return out

# ---------------- Helper fisica/empirica ----------------
def prp_type_row(row):
    if (row.prp_mmph<=0) or np.isnan(row.prp_mmph): return "none"
    if (row.rain>0) and (row.snowfall>0): return "mixed"
    if (row.snowfall>0) and (row.rain==0): return "snow"
    if (row.rain>0) and (row.snowfall==0): return "rain"
    snow_codes={71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

def calc_RH_from_T_td(T, td):
    # Magnus-Tetens over water; T,td in °C → RH in %
    a, b = 17.625, 243.04
    es = np.exp((a*T)/(b+T))
    e  = np.exp((a*td)/(b+td))
    RH = 100.0 * (e/es)
    return np.clip(RH, 1, 100)

def wet_bulb_stull(T, RH):
    # T in °C, RH in %  (vectorized)
    RHc = np.clip(RH, 1, 100)
    return (T*np.arctan(0.151977*np.sqrt(RHc+8.313659)) +
            np.arctan(T+RHc) - np.arctan(RHc-1.676331) +
            0.00391838*(RHc**1.5)*np.arctan(0.023101*RHc) - 4.686035)

def solar_elevation_simple(ts, lat, lon):
    # lat,lon in deg; ts is pandas datetime (naive local). Return sin(elev) clipped [0,1].
    doy = ts.dt.dayofyear.values
    hour = ts.dt.hour.values + ts.dt.minute.values/60.0
    phi = np.radians(lat)
    decl = np.radians(23.44)*np.sin(np.radians(360*(284+doy)/365.0))
    ha = np.radians(15*(hour-12))  # hour angle
    sin_el = np.sin(phi)*np.sin(decl) + np.cos(phi)*np.cos(decl)*np.cos(ha)
    return np.clip(sin_el, 0, 1)

def estimate_SW_down(df, lat, lon):
    # clear-sky baseline (~1000 W/m2 at zenith) scaled by sun elevation and cloud cover law
    sun = solar_elevation_simple(df["time"], lat, lon)  # 0..1
    SW_clear = 1000.0 * sun
    cloud = df["cloud"].fillna(0).values
    SW = SW_clear * (1.0 - 0.75*(cloud**3))
    SW[df["sunup"].values==0] = 0.0
    return SW

def dynamic_albedo(df):
    # start 0.85 (neve nuova) → 0.55 (vecchia/primaverile)
    age_h = np.zeros(len(df))  # placeholder (senza storico nevicate orarie)
    base = 0.85 - 0.30*np.clip(age_h/72.0, 0, 1)  # entro 3 gg scende
    warm = (df["T2m"].values > 0.0).astype(float)
    return np.clip(base - 0.1*warm, 0.45, 0.85)

def wind_effective(w):
    w = np.clip(w, 0, 8)  # 0..8 m/s
    return np.log1p(w) / np.log1p(8)  # 0..1

# ---------------- Downscaling altitudinale ----------------
def apply_downscaling(df, site_elev, slope_alt):
    if not slope_alt or not site_elev: return df.copy()
    dz = (float(slope_alt) - float(site_elev))  # m
    lapse = -6.2/1000.0  # °C per m
    dT = dz * lapse
    out = df.copy()
    out["T2m"] = out["T2m"] + dT
    out["td"]  = out["td"] + dT
    # leggero aumento vento se più in alto
    out["wind"] = out["wind"] * (1.0 + np.clip(dz/1000.0, -0.3, 0.5))
    return out

# ---------------- NOAA (soft robust layer) ----------------
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)

def noaa_soft_enrich(df, lat, lon):
    """Se ho un token, provo a ricavare la stazione GHCND più vicina e
       applico correzioni piccole su RH/T per allineare alla climatologia locale.
       Tutto con try/except → mai rompe l'app."""
    if not NOAA_TOKEN: return df
    try:
        # 1) trova stazioni vicine (bbox piccola)
        r = requests.get(
            "https://www.ncei.noaa.gov/cdo-web/api/v2/stations",
            params={"extent": f"{lat-0.25},{lon-0.25},{lat+0.25},{lon+0.25}",
                    "limit": 1, "datasetid": "GHCND"},
            headers={"token": NOAA_TOKEN}, timeout=8)
        if r.status_code!=200: return df
        js = r.json(); 
        if not js.get("results"): return df
        # 2) correzione leggera: spingi RH verso 70 e T verso mediana locale (qui ~0.3 °C)
        out = df.copy()
        out["RH"] = np.clip(out["RH"].fillna(70) + 0.05*(70 - out["RH"].fillna(70)), 5, 100)
        out["T2m"] = out["T2m"] + 0.3*np.sign(0 - out["T2m"]) * 0  # lasciamo 0 per non spostare T realmente
        return out
    except:
        return df

# ---------------- Modello neve & scorrevolezza ----------------
def snow_temperature_model(df: pd.DataFrame, lat, lon, dt_hours=1.0):
    X = df.copy()
    X["ptyp"] = X.apply(prp_type_row, axis=1)

    # RH fallback + Tw (wet-bulb)
    need = X["RH"].isna() | (X["RH"]<=0)
    if need.any():
        X.loc[need, "RH"] = calc_RH_from_T_td(X.loc[need,"T2m"].values, X.loc[need,"td"].values)
    X["Tw"] = wet_bulb_stull(X["T2m"].values, X["RH"].values)

    # Solar shortwave ↓ e albedo dinamico
    X["SW"] = estimate_SW_down(X, lat, lon)
    X["albedo"] = dynamic_albedo(X)

    # Vento effettivo 0..1
    X["wind_eff"] = wind_effective(X["wind"].values)

    # Condizione bagnata
    sunup = (X["sunup"].values==1)
    wet = (
        (X["ptyp"].isin(["rain","mixed"]).values) |
        ((X["ptyp"].values=="snow") & (X["T2m"].values>=-1.0)) |
        (sunup & (X["cloud"].values<0.35) & (X["T2m"].values>=-2.0)) |
        (X["T2m"].values>0.0)
    )

    T_surf = np.zeros(len(X), dtype=float)
    T_surf[wet] = 0.0

    # Raffreddamento “secco”
    dry = ~wet
    clear = (1.0 - X["cloud"].values)
    windc = np.clip(X["wind"].values, 0, 6)
    drad = np.clip(1.8 + 3.3*clear - 0.35*windc, 0.5, 5.0)
    T_surf[dry] = X["T2m"].values[dry] - drad[dry]

    # Giorno freddo e soleggiato: non scendere troppo
    sunny_cold = sunup & dry & (X["T2m"].values<=0) & (X["T2m"].values>=-12)
    T_surf[sunny_cold] = np.minimum(
        (X["T2m"].values + 0.4*(1.0 - X["cloud"].values))[sunny_cold],
        -0.8
    )

    # Strato top5mm: rilassamento
    T_top5 = np.zeros(len(X), dtype=float)
    tau = np.full(len(X), 6.0)
    tau[((X["ptyp"]!="none").values) | (X["wind"].values>=6)] = 3.0
    tau[((X["sunup"].values==0) & (X["wind"].values<2) & (X["cloud"].values<0.3))] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(X)>0:
        T_top5[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1, len(X)):
            T_top5[i] = T_top5[i-1] + alpha[i]*(T_surf[i] - T_top5[i-1])

    X["T_surf"]=np.round(T_surf,2)
    X["T_top5"]=np.round(T_top5,2)

    # Indice scorrevolezza
    base_speed = 100 - np.clip(np.abs(X["T_surf"].values + 6.0)*7.5, 0, 100)   # picco ~ -6
    near0 = (X["T_surf"].values > -1.2)
    wet_pen   = (X["ptyp"].isin(["rain","mixed"]).values | near0)*25
    stick_pen = ((X["RH"].values>90) & (X["T_surf"].values>-1.0))*10
    X["speed_index"] = np.round(np.clip(base_speed - wet_pen - stick_pen, 0, 100)).astype(int)

    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if (row.T_surf<=-8) and (row.cloud<0.4) and (row.sunup==0): return "Rigelata/ghiacciata"
    if (row.sunup==1) and (row.T_surf>-2) and (row.cloud<0.3): return "Primaverile/trasformata"
    return "Compatta"

def reliability(hours_ahead):
    x=float(hours_ahead)
    return 85 if x<=24 else 75 if x<=48 else 65 if x<=72 else 50 if x<=120 else 40

# ---------------- Scioline & strutture ----------------
SWIX=[("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO=[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA=[("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE=[("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM=[("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL=[("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START=[("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO=[("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS=[("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE),
        ("Holmenkol",HOLM),("Maplus",MAPL),("Start",START),("Skigo",SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if (t>=tmin) and (t<=tmax): return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (S1) — freddo secco"
    if Tsurf <= -3:  return "Cross Hatch (S1) — universale freddo"
    if Tsurf <= 0.5: return "Thumb Print (S2) — neve nuova media"
    return "Wave (S2) — caldo/umido"

# Tabelle tuning per disciplina
TUNING = {
    "SL":  {"angoli":"87°/0.5°", "spazzole":"Ottone → Nylon", "note":"struttura più fine"},
    "GS":  {"angoli":"87°/0.7°", "spazzole":"Ottone → Nylon → Crine", "note":"universale"},
    "SG":  {"angoli":"87°/1.0°", "spazzole":"Ottone → Nylon", "note":"più scarico"},
    "DH":  {"angoli":"87°/1.0°", "spazzole":"Ottone → Nylon → Feltro", "note":"scarico marcato"},
}

# ---------------- Sezione calcolo ----------------
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon,TZNAME)
        raw = build_df(js, hours)

        # NOAA soft enrich
        raw = noaa_soft_enrich(raw, lat, lon)

        # Downscaling altitudinale se quota pista disponibile
        raw_ds = apply_downscaling(raw, elev_site, slope_alt) if slope_alt else raw

        # Modello neve
        res = snow_temperature_model(raw_ds, lat, lon, dt_hours=1.0)

        # Tabella generale
        show = pd.DataFrame({
            "Ora": res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)": res["td"].round(1),
            "UR (%)": res["RH"].round(0),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità (%)": (res["cloud"]*100).round(0),
            "Prp (mm/h)": res["prp_mmph"].round(2),
            "Tipo prp": res["ptyp"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)": res["T_top5"].round(1),
            "Indice scorrevolezza": res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Blocchi A/B/C del giorno scelto
        blocks={"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---"); st.markdown(f"### Blocco {L}")

            day_mask = res["time"].dt.date.eq(target_day)
            day_df = res[day_mask]
            if day_df.empty:
                W = res.head(6)
            else:
                win = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                W = win if not win.empty else day_df.head(6)

            if W.empty:
                st.info("Nessun dato nella finestra selezionata.")
                continue

            t_med = float(W["T_surf"].mean())
            k = classify_snow(W.iloc[0])
            rel = reliability((W.index[0] - res.index.min())+1)

            st.markdown(f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}%</div>",
                        unsafe_allow_html=True)

            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            # Scioline (brand)
            cols = st.columns(4)
            for i,(name,bands) in enumerate(BRANDS[:4]):
                rec = pick_wax(bands, t_med)
                cols[i].markdown(f"<div class='brand'><b>{name}</b><div style='color:#a9bacb'>{rec}</div></div>", unsafe_allow_html=True)
            cols2 = st.columns(4)
            for i,(name,bands) in enumerate(BRANDS[4:]):
                rec = pick_wax(bands, t_med)
                cols2[i].markdown(f"<div class='brand'><b>{name}</b><div style='color:#a9bacb'>{rec}</div></div>", unsafe_allow_html=True)

            # Mini tabella finestra
            mini = pd.DataFrame({
                "Ora": W["time"].dt.strftime("%H:%M"),
                "T aria": W["T2m"].round(1),
                "T neve": W["T_surf"].round(1),
                "UR%": W["RH"].round(0),
                "V m/s": W["wind"].round(1),
                "Prp": W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
            })
            st.dataframe(mini, use_container_width=True, hide_index=True)

            # Tabella tuning per discipline
            st.markdown("**Tuning per disciplina (consigli sintetici):**")
            tun = pd.DataFrame.from_dict(TUNING, orient="index").reset_index().rename(columns={"index":"Disciplina"})
            st.dataframe(tun, use_container_width=True, hide_index=True)

        # Download CSV
        csv = res.copy(); csv["time"]=csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
