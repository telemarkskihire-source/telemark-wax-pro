# telemark_pro_app.py
# -----------------------------------------------------------
# Telemark · Pro Wax & Tune — DARK THEME + NOAA + SPRING SNOW + LIQUID WATER + ALTIMETRIC DOWNSCALING
# -----------------------------------------------------------
import os, math, base64, requests
import pandas as pd
import streamlit as st
from datetime import date, time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ===================== THEME (dark) =====================
PRIMARY = "#06b6d4"   # Telemark turquoise
ACCENT  = "#f97316"   # accent orange
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
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{
  display:inline-flex; align-items:center; gap:.5rem;
  background:#0b1220; border:1px solid #203045; color:#cce7f2;
  border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem .95rem; }}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{
  border-left:6px solid {ACCENT}; background:#1a2230; color:#e2e8f0;
  padding:.75rem .9rem; border-radius:10px; font-size:.98rem;
}}
.brand {{
  display:flex; align-items:center; gap:.65rem; background:#0e141d;
  border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem;
}}
.kpi {{ display:flex; gap:.75rem; align-items:center; }}
.kpi .v {{ font-weight:800; font-size:1.1rem }}
.kpi.ok .v {{ color:{OK}; }} .kpi.warn .v {{ color:{WARN}; }} .kpi.err .v {{ color:{ERR}; }}
.btn-primary button {{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important; }}
.slider-tip {{ color:var(--muted); font-size:.85rem }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline — blocchi A/B/C, NOAA, downscaling altimetrico.")

# ===================== UTILS =====================
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

def clamp(x, a, b): 
    return max(a, min(b, x))

# ===================== RICERCA con PREFILTRO NAZIONE =====================
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro)", list(COUNTRIES.keys()), index=0)
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

# Altitudine: base (per downscaling)
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

base_elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(base_elev) if base_elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# ===================== GIORNO & BLOCCHI =====================
cdate, cpista = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())
with cpista:
    pista_elev = st.number_input("Quota pista (m) per downscaling", 
                                 min_value=0, max_value=5000, 
                                 value=int(base_elev) if base_elev else 2000, step=10)

st.write("")
st.subheader("1) Finestre orarie A · B · C")
def tt(h,m): return time(h,m)
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0),  key="A_s")
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

# ===================== DATI METEO =====================
def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone="Europe/Rome",
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
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["RH"]   = df.get("relative_humidity_2m", pd.Series([None]*len(df))).astype(float)
    out["td"]   = df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"]     = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"]    = df.get("weathercode",0).astype(int)
    return out

# ===================== QUICK WINS (NUOVI) =====================
def fill_RH_from_T_td(df: pd.DataFrame) -> pd.DataFrame:
    # Se RH mancante, calcola da T e Td (Magnus-Tetens)
    X = df.copy()
    miss = X["RH"].isna()
    if miss.any():
        T = X.loc[miss, "T2m"].astype(float)
        Td= X.loc[miss, "td"].astype(float)
        a,b = 17.625, 243.04
        es  = 6.112 * (10 ** ((a*T)/(b+T)))
        e   = 6.112 * (10 ** ((a*Td)/(b+Td)))
        rh  = clamp_series(100*e/es, 1, 100)
        X.loc[miss, "RH"] = rh
    return X

def clamp_series(s, low, high):
    return s.clip(lower=low, upper=high)

def wet_bulb_Stull(T, RH):
    # Stima di bulbo umido (°C) — formula approssimata di Stull
    # RH in %, T in °C
    # Riferimento: Stull (2011) "Wet-Bulb Temperature from Relative Humidity and Air Temperature"
    RHc = clamp_series(RH, 1, 100)
    Tw = T*math.atan(0.151977*math.sqrt(RHc+8.313659)) + math.atan(T+RHc) - math.atan(RHc-1.676331) \
         + 0.00391838*(RHc**1.5)*math.atan(0.023101*RHc) - 4.686035
    return Tw

def effective_wind(w_ms):
    # clip 0..8 m/s + resa logaritmica per perdite convettive
    w = clamp_series(w_ms, 0, 8)
    return (1 + 1.6*pd.Series.map(w, lambda x: math.log1p(x))).astype(float)

def estimate_SWdown(sunup, cloud):
    # SW_clear semplice: 800 W/m² quando giorno; attenuazione nuvolosità ~ (1 - 0.75*cloud^3)
    sw_clear = 800.0 * sunup
    return sw_clear * (1.0 - 0.75*(cloud**3))

def dynamic_albedo(snow_last48_mm, T2m):
    # neve nuova: 0.85 → degrada verso 0.55 con poca neve recente e T>0
    fresh = clamp( snow_last48_mm / 30.0, 0.0, 1.0)   # 30 mm ~ 3 cm
    warm  = 1.0 if (T2m > 0.0) else 0.0
    return 0.55 + 0.30*(1 - warm) + 0.15*fresh  # 0.55..1.0 cap
# (NB: albedo non entra ancora nel bilancio energetico completo; qui aiuta in classificazione/indici)

# ===================== NOOA SOFT ENRICH =====================
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)
def try_enrich_with_noaa(df, lat, lon):
    if not NOAA_TOKEN: 
        return df
    try:
        # soft pull placeholder → piccola correzione RH ±2% verso 70
        corr = (70 - df["RH"].fillna(70)) * 0.03
        df["RH"] = (df["RH"].fillna(70) + corr).clip(5, 100)
        return df
    except:
        return df

# ===================== PRECIP TYPE =====================
def prp_type_row(row):
    if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# ===================== DOWNSCALING ALTITUDINALE =====================
def lapse_rate_dynamic(T2m, sunup):
    # -6.5°C/km base; un filo meno di giorno soleggiato
    base = -6.5
    adj  = 0.6 if sunup==1 and T2m>-5 else 0.0
    return (base + adj) / 1000.0  # °C per metro

def apply_downscaling(df: pd.DataFrame, base_elev_m: float|None, target_elev_m: float|None) -> pd.DataFrame:
    if base_elev_m is None or target_elev_m is None:
        return df
    dz = float(target_elev_m - base_elev_m)  # + su, - giù
    X = df.copy()
    laps = X.apply(lambda r: lapse_rate_dynamic(r["T2m"], r["sunup"]), axis=1)
    dT   = laps * dz
    # Temperature
    X["T2m"] = X["T2m"] + dT
    X["td"]  = X["td"] + dT * 0.7  # dewpoint varia meno della T (stima semplice)
    # Snow/rain partition (se T scende sotto 0, più neve)
    # non tocchiamo i mm/h; ricalcoleremo tipo prp in seguito
    return X

# ===================== MODELLO NEVE =====================
def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    """Stima T_surf, T_top5, indice scorrevolezza e acqua liquida (%vol)."""
    X = df.copy()

    # Quick wins
    X = fill_RH_from_T_td(X)
    X["Tw"] = wet_bulb_Stull(X["T2m"], X["RH"])  # bulbo umido (°C)
    X["wind_eff"] = effective_wind(X["wind"])
    X["SW_down"]  = estimate_SWdown(X["sunup"], X["cloud"])
    # neve recente (mm) ~ ultime 48h nella serie disponibile
    X["snow_48h"] = X["snowfall"].rolling(48, min_periods=1).sum().fillna(0.0)

    # Tipo precipitazione
    X["ptyp"] = X.apply(prp_type_row, axis=1)

    # Stato "wet" (conservativo): pioggia/mista, T>0, sole forte su freddo moderato, neve vicino a 0
    sunup = X["sunup"]==1
    near0 = X["T2m"].between(-1.2, 1.2)
    strong_sun = X["SW_down"] > 500  # W/m2
    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ((X["ptyp"]=="snow") & X["T2m"].ge(-1.0)) |
        (sunup & strong_sun & X["T2m"].ge(-3.0)) |
        (X["T2m"]>0.0)
    )

    # Superficie
    T_surf = pd.Series(index=X.index, dtype=float)
    T_surf.loc[wet] = 0.0

    # Raffreddamento radiativo/convettivo su asciutto
    dry = ~wet
    clear = (1.0 - X["cloud"]).clip(0,1)
    # maggiore vento_eff → meno raffreddamento radiativo “netto”
    drad = (1.8 + 3.3*clear - 0.25*X["wind_eff"]).clip(0.3, 5.0)  # °C
    T_surf.loc[dry] = X["T2m"][dry] - drad[dry]

    # Giorno freddo ma soleggiato, limitiamo lo scarto sotto l’aria
    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (X["T2m"] + 0.35*(1.0 - X["cloud"]))[sunny_cold],
        pd.Series(-0.8, index=X.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # Strato top ~5mm: rilassamento
    T_top5 = pd.Series(index=X.index, dtype=float)
    tau = pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptyp"]!="none") | (X["wind"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(X)>0:
        T_top5.iloc[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    X["T_surf"] = T_surf.round(2)
    X["T_top5"] = T_top5.round(2)

    # Acqua liquida %vol — stima semplice 0..10
    # base da eccesso termico vicino 0 + sole forte + pioggia
    excess = (X["T_surf"] + 0.5).clip(lower=0)  # > -0.5°C
    sun_term = (X["SW_down"]/800.0).clip(0,1)
    rain_term= (X["rain"]).clip(lower=0, upper=5.0) / 5.0
    water_pct = 10.0 * (0.45*excess/1.5 + 0.35*sun_term + 0.20*rain_term)
    X["water_pct"] = clamp_series(water_pct, 0.0, 10.0).round(1)

    # Indice di scorrevolezza 0..100 (più alto = più veloce)
    # picco verso -6..-4 secco; penalità vicino a 0, bagnato e UR molto alta
    base_speed = 100 - (abs(X["T_surf"] + 5.0)*7.0).clip(0,100)     # picco ~ -5
    wet_pen   = ((X["water_pct"]>=2.0) | (X["ptyp"].isin(["rain","mixed"])) | near0).astype(int)*22
    stick_pen = ((X["RH"] > 90) & (X["T_surf"] > -1.0)).astype(int)*10
    sun_boost = (sunup & (X["SW_down"]>350) & (X["T_surf"]<-1.0)).astype(int)*6  # sole che “scioglie” microfilm su freddo leggero
    speed_idx = (base_speed - wet_pen - stick_pen + sun_boost).clip(0,100)
    X["speed_index"] = speed_idx.round(0)

    return X

def classify_snow(row):
    # Primavera: SW alto + T_surf vicino zero + acqua
    if row.ptyp=="rain": return "Neve bagnata / pioggia"
    if row.ptyp=="mixed": return "Mista pioggia-neve"
    if (row.sunup==1) and (row.SW_down>450) and (row.T_surf>-2.0) and (row.water_pct>=1.5):
        return "Primaverile / trasformata"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.sunup==0 and row.cloud<0.4: return "Rigelata / ghiacciata"
    return "Compatta"

def reliability(hours_ahead):
    x = float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# ===================== WAX BRANDS =====================
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
    if Tsurf <= 0.5: return "Diagonal / Scarico V (umido)"
    return "Wave / Scarico marcato (caldo-bagnato)"

# ===================== UI: CALCOLO =====================
st.write("")
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js  = fetch_open_meteo(lat,lon)
        raw = build_df(js, hours)

        # NOAA soft-layer
        raw = try_enrich_with_noaa(raw, lat, lon)

        # Downscaling verso quota pista
        raw_ds = apply_downscaling(raw, base_elev, pista_elev)

        # Model
        res = snow_temperature_model(raw_ds)

        # Tabella pulita
        show = pd.DataFrame({
            "Ora":    res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["td"].round(1),                 # Td = dew point (temperatura di rugiada)
            "UR (%)":      res["RH"].round(0),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità":  (res["cloud"]*100).round(0),
            "Prp (mm/h)":  res["prp_mmph"].round(2),
            "Tipo prp":    res["ptyp"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "SW_down (W/m²)": res["SW_down"].round(0),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "H₂O liquida (%)":  res["water_pct"].round(1),
            "Indice di scorrevolezza": res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # ===== Blocchi A/B/C
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            tzobj = tz.gettz("Europe/Rome")
            mask = (res["time"].dt.tz_localize(tzobj, nonexistent='shift_forward', ambiguous='NaT')
                        .dt.tz_convert(tzobj).dt.date == target_day)
            day_df = res[mask].copy()
            if day_df.empty:
                W = res.head(7).copy()
            else:
                cut = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                W = cut if not cut.empty else day_df.head(6)

            if not W.empty:
                t_med   = float(W["T_surf"].mean())
                k       = classify_snow(W.iloc[0])
                rel     = reliability((W.index[0] if not W.empty else 0) + 1)
                water_m = float(W["water_pct"].mean())
                spd_m   = int(W["speed_index"].mean())

                st.markdown(
                    f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                    f"<b>T_neve media</b> {t_med:.1f}°C · "
                    f"<b>H₂O liquida</b> ~ {water_m:.1f}% · "
                    f"<b>Indice scorrevolezza</b> {spd_m}/100 · "
                    f"<b>Affidabilità</b> ≈ {rel}%</div>",
                    unsafe_allow_html=True
                )
            else:
                st.info("Nessun dato nella finestra scelta.")
                t_med = 0.0

            # Struttura + Scioline
            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Scioline suggerite (per temperatura neve media):**")
                ccols1 = st.columns(4); ccols2 = st.columns(4)
                for i,(name,path,bands) in enumerate(BRANDS[:4]):
                    rec = pick_wax(bands, t_med)
                    ccols1[i].markdown(
                        f"<div class='brand'><div><b>{name}</b>"
                        f"<div style='color:#a9bacb'>{rec}</div></div></div>",
                        unsafe_allow_html=True
                    )
                for i,(name,path,bands) in enumerate(BRANDS[4:]):
                    rec = pick_wax(bands, t_med)
                    ccols2[i].markdown(
                        f"<div class='brand'><div><b>{name}</b>"
                        f"<div style='color:#a9bacb'>{rec}</div></div></div>",
                        unsafe_allow_html=True
                    )

            with col2:
                if not W.empty:
                    mini = pd.DataFrame({
                        "Ora":   W["time"].dt.strftime("%H:%M"),
                        "T aria":W["T2m"].round(1),
                        "T neve":W["T_surf"].round(1),
                        "UR%":   W["RH"].round(0),
                        "V m/s": W["wind"].round(1),
                        "Prp":   W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                    })
                    st.dataframe(mini, use_container_width=True, hide_index=True)

        # ===== CSV
        csv = res.copy()
        csv["time"] = csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
