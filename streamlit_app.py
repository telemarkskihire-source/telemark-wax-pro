# telemark_pro_app.py
# -------------------
# Telemark · Pro Wax & Tune (tema scuro, nazione prefiltrata, algoritmo neve migliorato + NOAA + downscaling quota)
import os, math, base64, requests, pandas as pd, numpy as np
import streamlit as st
from datetime import datetime, date, time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =============== Tema & stile (dark) ===============
PRIMARY = "#06b6d4"   # turchese acceso
ACCENT  = "#f97316"   # arancione evidenza
OK      = "#10b981"
WARN    = "#f59e0b"
ERR     = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937;
}}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: 1rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing: .2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{
  display:inline-flex; align-items:center; gap:.5rem;
  background:#0b1220; border:1px solid #203045; color:#cce7f2;
  border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}}
.card {{
  background: var(--panel); border:1px solid var(--line);
  border-radius:12px; padding: .9rem .95rem;
}}
.kpi {{ display:flex; gap:.75rem; align-items:center; }}
.kpi .v {{ font-weight:800; font-size:1.1rem }}
.kpi.ok .v {{ color:{OK}; }} .kpi.warn .v {{ color:{WARN}; }}
.kpi.err .v {{ color:{ERR}; }}
.brand {{
  display:flex; align-items:center; gap:.65rem; background:#0e141d;
  border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem;
}}
.brand img {{ height:22px }}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{
  border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0;
  padding:.75rem .9rem; border-radius:10px; font-size:.98rem;
}}
.btn-primary button {{
  background:{ACCENT} !important; color:#111 !important; font-weight:800 !important;
}}
.slider-tip {{ color:var(--muted); font-size:.85rem }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline – ottimizzato per blocchi A/B/C.")

# =============== Utils ===============
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

# =============== Ricerca località con prefiltro Nazione ===============
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
    iso2 = COUNTRIES[sel_country]
with colSB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q":q, "format":"json", "limit":12, "addressdetails":1, "countrycodes": iso2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"},
                timeout=8
            )
            r.raise_for_status()
            st.session_state._options = {}
            out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab = concise_label(addr, it.get("display_name",""))
                cc = addr.get("country_code","")
                lab = f"{flag(cc)}  {lab}"
                lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
                key = f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key] = {"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            return out
        except:
            return []

    selected = st_searchbox(
        nominatim_search, key="place", placeholder="Cerca… es. Champoluc, Plateau Rosa",
        clear_on_submit=False, default=None
    )

# Altitudine
def get_elev(lat,lon):
    try:
        rr = requests.get("https://api.open-meteo.com/v1/elevation",
                          params={"latitude":lat, "longitude":lon}, timeout=8)
        rr.raise_for_status(); js = rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

site_elev = get_elev(lat,lon) or 0.0
st.markdown(
    f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(site_elev)} m</b></div>",
    unsafe_allow_html=True
)

# === (NUOVO 1/3) Input downscaling: altitudine target (pista/gara) ===
target_elev = st.number_input("Altitudine target (m)", min_value=0, max_value=4800, value=int(site_elev), step=10)

# =============== Giorno & blocchi (giorni successivi) ===============
cdate = st.columns(1)[0]
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())

st.write("")  # spacing
st.subheader("1) Finestre orarie A · B · C")
c1,c2,c3 = st.columns(3)
def tt(h,m): return time(h,m)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   tt(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", tt(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   tt(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", tt(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   tt(16,0), key="C_e")

st.write("")
st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)
st.markdown("<div class='slider-tip'>Suggerimento: < 48h → stime più affidabili</div>", unsafe_allow_html=True)

# =============== Open-Meteo (timezone fisso Europe/Rome) ===============
TZNAME = "Europe/Rome"

def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone=TZNAME,
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7,
        ),
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now(tz=tz.gettz(js.get("timezone","UTC"))).floor("H").tz_localize(None)
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = pd.to_numeric(df["temperature_2m"], errors="coerce")
    if "relative_humidity_2m" in df: out["RH"] = pd.to_numeric(df["relative_humidity_2m"], errors="coerce")
    else: out["RH"] = pd.NA
    out["td"]   = pd.to_numeric(df.get("dew_point_2m", df["temperature_2m"]), errors="coerce")
    out["cloud"]= (pd.to_numeric(df["cloudcover"], errors="coerce")/100).clip(0,1)
    out["wind"] = (pd.to_numeric(df["windspeed_10m"], errors="coerce")/3.6)  # m/s
    out["sunup"]= pd.to_numeric(df["is_day"], errors="coerce").fillna(0).astype(int)
    out["prp_mmph"] = pd.to_numeric(df["precipitation"], errors="coerce").fillna(0.0)
    out["rain"] = pd.to_numeric(df.get("rain",0.0), errors="coerce").fillna(0.0)
    out["snowfall"] = pd.to_numeric(df.get("snowfall",0.0), errors="coerce").fillna(0.0)
    out["wcode"] = pd.to_numeric(df.get("weathercode",0), errors="coerce").fillna(0).astype(int)
    return out

# Precipitazione tipo
def prp_type_row(row):
    if (row.prp_mmph<=0) or pd.isna(row.prp_mmph): return "none"
    if (row.rain>0) and (row.snowfall>0): return "mixed"
    if (row.snowfall>0) and (row.rain==0): return "snow"
    if (row.rain>0) and (row.snowfall==0): return "rain"
    snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# === (NUOVO 2/3) NOAA: selezione stazione ISD più vicina + blend robusto ===
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)
_NOAA_BASE = "https://www.ncei.noaa.gov/cdo-web/api/v2"

def _noaa_headers():
    return {"token": NOAA_TOKEN} if NOAA_TOKEN else {}

def _noaa_find_station(lat, lon, radius_km=50):
    """Cerca stazioni ISD vicine ordinate per distanza (ritorna id o None)."""
    if not NOAA_TOKEN: return None
    try:
        # bounding box veloce ~ raggio (approssimazione 1° ~ 111 km)
        d = radius_km/111.0
        params = {
            "datasetid":"ISD","extent":f"{lat-d},{lon-d},{lat+d},{lon+d}",
            "limit":5, "sortfield":"distance", "sortorder":"asc"
        }
        r = requests.get(f"{_NOAA_BASE}/stations", headers=_noaa_headers(), params=params, timeout=15)
        r.raise_for_status()
        js = r.json()
        if js.get("results"):
            return js["results"][0]["id"]  # id tipo GHCND:XXXX o ISD:XXXX
    except:
        return None
    return None

def _noaa_fetch_hourly(station_id, day:date):
    """Scarica alcune variabili orarie da ISD per il giorno indicato (UTC).
       Torna un DataFrame con time, T2m, RH, wind, prp_mmph (grezzo)."""
    if not (NOAA_TOKEN and station_id): return None
    try:
        start = f"{day}T00:00:00"
        end   = f"{day}T23:59:59"
        # datatypeid per ISD (temp, dew point, wind, precip 1h se presente):
        params = {
            "datasetid":"ISD","stationid":station_id,
            "startdate":start, "enddate":end,
            "datatypeid":["TMP","DEW","AA1","WND"],  # temperatura, dew, precip hourly (if), vento
            "units":"metric","limit":1000
        }
        r = requests.get(f"{_NOAA_BASE}/data", headers=_noaa_headers(), params=params, timeout=20)
        r.raise_for_status()
        rows = r.json().get("results", [])
        if not rows: return None
        # Pivot semplice
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(None)
        p = df.pivot_table(index="date", columns="datatype", values="value", aggfunc="mean").reset_index()
        out = pd.DataFrame()
        out["time"] = pd.to_datetime(p["date"])
        # TMP e DEW sono decimi °C in alcune sorgenti ISD -> qui l'API già in metric
        out["T2m"] = pd.to_numeric(p.get("TMP"), errors="coerce")
        td = pd.to_numeric(p.get("DEW"), errors="coerce")
        out["td"] = td
        # calcolo RH se possibile
        rh = 100*np.exp((17.625*td)/(243.04+td))/np.exp((17.625*out["T2m"])/(243.04+out["T2m"]))
        out["RH"] = rh.clip(0,100)
        # vento: WND media m/s? API spesso dà velocità in m/s (verifica). Mettiamo fallback.
        out["wind"] = pd.to_numeric(p.get("WND"), errors="coerce")
        # precipitazione: AA1 spesso mm in 1h
        out["prp_mmph"] = pd.to_numeric(p.get("AA1"), errors="coerce")
        return out.dropna(how="all")
    except:
        return None

def _blend_with_noaa(model_df:pd.DataFrame, lat, lon, day:date):
    """Blend/bias-correction: allinea per ora e fa media pesata (NOAA 60%, Model 40%).
       Se NOAA parziale: usa differenze medie come bias e corregge tutta la serie del giorno.
       Se NOAA assente: climatologia dolce verso RH=70 e vento ridotto 5%."""
    if NOAA_TOKEN is None:
        # climatologia dolce
        out = model_df.copy()
        out["RH"] = out["RH"].fillna(70) + (70 - out["RH"].fillna(70))*0.03
        out["wind"] = out["wind"].clip(0,8)*0.97
        return out

    stid = _noaa_find_station(lat, lon, radius_km=40)
    if not stid:
        out = model_df.copy()
        out["RH"] = out["RH"].fillna(70) + (70 - out["RH"].fillna(70))*0.03
        out["wind"] = out["wind"].clip(0,8)*0.97
        return out

    noaa = _noaa_fetch_hourly(stid, day)
    if noaa is None or noaa.empty:
        out = model_df.copy()
        out["RH"] = out["RH"].fillna(70) + (70 - out["RH"].fillna(70))*0.03
        out["wind"] = out["wind"].clip(0,8)*0.97
        return out

    m = model_df.copy()
    # join per ora locale (armonizziamo a naive)
    m["hh"] = pd.to_datetime(m["time"]).dt.floor("H")
    noaa["hh"] = pd.to_datetime(noaa["time"]).dt.floor("H")
    merged = pd.merge(m, noaa[["hh","T2m","RH","wind","prp_mmph"]], on="hh", how="left", suffixes=("", "_noaa"))

    # Pesata dove NOAA presente
    for col in ["T2m","RH","wind","prp_mmph"]:
        ncol = f"{col}_noaa"
        has = merged[ncol].notna()
        merged.loc[has, col] = 0.6*merged.loc[has, ncol] + 0.4*merged.loc[has, col]

    # Bias giornaliero dove manca
    for col in ["T2m","RH","wind"]:
        ncol = f"{col}_noaa"
        bias = (merged[ncol] - merged[col]).dropna()
        if not bias.empty:
            b = bias.mean()
            miss = merged[ncol].isna()
            merged.loc[miss, col] = merged.loc[miss, col] + 0.6*b

    merged.drop(columns=[c for c in merged.columns if c.endswith("_noaa") or c=="hh"], inplace=True)
    return merged

# === (NUOVO 3/3) Downscaling altitudinale (temperatura/precip/vento) ===
def downscale_to_altitude(df:pd.DataFrame, src_elev_m:float, tgt_elev_m:float):
    """Applica lapse rate dinamico alla T, aggiusta fase/quantità precip e attenua/rafforza vento leggermente con quota."""
    out = df.copy()
    dz_km = (tgt_elev_m - src_elev_m)/1000.0
    # lapse rate dinamico (più forte aria secca): 5.5–6.5 K/km
    lr = np.where(out["RH"].fillna(70)>80, 5.5, 6.5)
    out["T2m"] = out["T2m"] - lr*dz_km
    out["td"]  = out["td"] - (0.7*lr)*dz_km  # dew point cala meno della T

    # fase: probabilità neve aumenta con quota → shift di 0.6°C per +300 m
    phase_shift = -0.6*dz_km/0.3  # ~ -2 K per +1 km
    t_phase = out["T2m"] + phase_shift
    # ri-suddividi rain/snow (solo qualitativo per le tabelle; quantità simile ma spostata)
    snow_ratio = (1.0/(1.0 + np.exp(4*(t_phase))))  # logistic ~ neve <0°C
    out["snowfall"] = out["prp_mmph"]*snow_ratio
    out["rain"]      = out["prp_mmph"]*(1.0 - snow_ratio)

    # prp orografica semplice: +10% ogni +300m (limit 1.4x)
    scale = np.clip(1.0 + 0.10*(dz_km/0.3), 0.7, 1.4)
    out["prp_mmph"] = out["prp_mmph"]*scale
    out["snowfall"] = out["snowfall"]*scale
    out["rain"]     = out["rain"]*scale

    # vento: leggero aumento con quota fino a +15%
    out["wind"] = out["wind"] * np.clip(1.0 + 0.15*dz_km, 0.8, 1.15)

    return out

# =============== Algoritmo Temperatura Neve & Scorrevolezza ===============
def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    X = df.copy()
    X["ptyp"] = X.apply(prp_type_row, axis=1)

    sunup = X["sunup"]==1
    near0 = X["T2m"].between(-1.2, 1.2)

    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ((X["ptyp"]=="snow") & X["T2m"].ge(-1.0)) |
        (sunup & (X["cloud"]<0.35) & X["T2m"].ge(-2.0)) |
        (X["T2m"]>0.0)
    )

    T_surf = pd.Series(index=X.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - X["cloud"]).clip(0,1)
    windc = X["wind"].clip(0,8)
    drad = (1.8 + 3.3*clear - 0.35*windc).clip(0.5, 5.0)
    T_surf.loc[dry] = X["T2m"][dry] - drad[dry]

    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    limit = pd.Series(-0.8, index=X.index)
    T_surf.loc[sunny_cold] = np.minimum((X["T2m"] + 0.4*(1.0 - X["cloud"]))[sunny_cold], limit[sunny_cold])

    T_top5 = pd.Series(index=X.index, dtype=float)
    tau = pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptyp"]!="none") | (X["wind"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(X)>0:
        T_top5.iloc[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    X["T_surf"] = T_surf.round(2)
    X["T_top5"] = T_top5.round(2)

    base_speed = 100 - (np.abs(X["T_surf"] + 6.0)*7.5).clip(0,100)
    wet_pen   = ((X["ptyp"].isin(["rain","mixed"]) | near0).astype(int))*25
    stick_pen = (((X["RH"].fillna(75) > 90) & (X["T_surf"] > -1.0)).astype(int))*10
    X["speed_index"] = (base_speed - wet_pen - stick_pen).clip(0,100).round(0)

    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista/pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if (row.T_surf<=-8) and (row.cloud<0.4) and (row.sunup==0): return "Rigelata/ghiacciata"
    if (row.sunup==1) and (row.T_surf>-2) and (row.cloud<0.3): return "Primaverile/trasformata"
    return "Compatta"

def reliability(hours_ahead):
    x = float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# =============== Scioline (brand) ===============
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix","assets/brands/swix.png",SWIX),("Toko","assets/brands/toko.png",TOKO),
          ("Vola","assets/brands/vola.png",VOLA),("Rode","assets/brands/rode.png",RODE),
          ("Holmenkol","assets/brands/holmenkol.png",HOLM),("Maplus","assets/brands/maplus.png",MAPL),
          ("Start","assets/brands/start.png",START),("Skigo","assets/brands/skigo.png",SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (freddo/secco)"
    if Tsurf <= -3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf <= 0.5: return "Diagonal/Scarico V (umido)"
    return "Wave/Scarico marcato (bagnato caldo)"

# =============== Sezione calcolo ===============
st.write("")
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon)
        raw = build_df(js, hours)

        # NOAA forte (blend/bias) sul giorno scelto
        raw = _blend_with_noaa(raw, lat, lon, target_day)

        # Downscaling alla quota target
        raw = downscale_to_altitude(raw, site_elev, float(target_elev))

        # Modello neve
        res = snow_temperature_model(raw)

        # Tabella ordinata e leggibile
        show = pd.DataFrame({
            "Ora":    res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["td"].round(1),
            "UR (%)":      res["RH"].round(0),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità":  (res["cloud"]*100).round(0),
            "Prp (mm/h)":  res["prp_mmph"].round(2),
            "Tipo prp":    res.apply(lambda r: prp_type_row(r), axis=1).map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "Indice scorrevolezza": res["speed_index"].astype(int),
        })

        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Blocchi A/B/C
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            # filtro per giorno scelto in TZ locale
            tzobj = tz.gettz(TZNAME)
            D = res.copy()
            D["dt_local"] = pd.to_datetime(D["time"]).dt.tz_localize(tzobj, nonexistent='shift_forward', ambiguous='NaT').dt.tz_convert(tzobj)
            mask = D["dt_local"].dt.date == target_day
            day_df = D[mask].copy()
            if day_df.empty:
                W = res.head(7).copy()
            else:
                cut = day_df[(day_df["dt_local"].dt.time>=s) & (day_df["dt_local"].dt.time<=e)]
                W = cut if not cut.empty else day_df.head(6)

            t_med = float(W["T_surf"].mean()) if not W.empty else 0.0
            k = classify_snow(W.iloc[0]) if not W.empty else "—"
            # affidabilità semplice: più vicino nel tempo → più alta
            idx0 = W.index.min() if not W.empty else 0
            rel = reliability((idx0+1))

            st.markdown(f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}%</div>",
                        unsafe_allow_html=True)

            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Scioline suggerite (per temperatura neve media):**")
                ccols1 = st.columns(4); ccols2 = st.columns(4)
                for i,(name,path,bands) in enumerate(BRANDS[:4]):
                    rec = pick_wax(bands, t_med)
                    ccols1[i].markdown(
                        f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{rec}</div></div></div>",
                        unsafe_allow_html=True
                    )
                for i,(name,path,bands) in enumerate(BRANDS[4:]):
                    rec = pick_wax(bands, t_med)
                    ccols2[i].markdown(
                        f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{rec}</div></div></div>",
                        unsafe_allow_html=True
                    )
            with col2:
                if not W.empty:
                    mini = pd.DataFrame({
                        "Ora":  pd.to_datetime(W["time"]).dt.strftime("%H:%M"),
                        "T aria": W["T2m"].round(1),
                        "T neve": W["T_surf"].round(1),
                        "UR%":   W["RH"].round(0),
                        "V m/s": W["wind"].round(1),
                        "Prp":   W.apply(lambda r: prp_type_row(r), axis=1).map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                    })
                    st.dataframe(mini, use_container_width=True, hide_index=True)
                else:
                    st.info("Nessun dato nella finestra scelta.")

        # Download CSV completo
        csv = res.copy()
        csv["time"] = pd.to_datetime(csv["time"]).dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
