# telemark_pro_app.py
# Telemark · Pro Wax & Tune – dark, country-prefilter, improved inputs (RH, wet-bulb, SW, albedo),
# robust snow-surface model, graphs, brand wax, tuning by discipline.

import os, base64, requests, numpy as np, pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime, date, time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ===================== THEME / STYLE =====================
PRIMARY = "#06b6d4"   # turquoise
ACCENT  = "#f97316"   # orange
OK      = "#10b981"
WARN    = "#f59e0b"
ERR     = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:1rem }}
.badge {{
  display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045;
  color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th,.tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{ border-left:6px solid {ACCENT}; background:#1a2230; color:#e2e8f0; padding:.75rem .9rem; border-radius:10px }}
.btn-prim button {{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important; }}
.kpi .v {{ font-weight:800 }} .kpi.ok .v {{ color:{OK} }} .kpi.warn .v {{ color:{WARN} }} .kpi.err .v {{ color:{ERR} }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e setup – blocchi A/B/C.")

# ===================== HELPERS =====================
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

def get_elev(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status(); js = r.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except:
        return None

# ===================== COUNTRY PREFILTER + SEARCH =====================
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
cA, cB = st.columns([1,3])
with cA:
    sel_country = st.selectbox("Nazione (prefiltro)", list(COUNTRIES.keys()), index=0)
    ISO2 = COUNTRIES[sel_country]
with cB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search",
                             params={"q":q,"format":"json","limit":12,"addressdetails":1,
                                     "countrycodes":ISO2.lower()},
                             headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=10)
            r.raise_for_status()
            st.session_state._opts = {}
            out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab  = concise_label(addr, it.get("display_name",""))
                cc   = addr.get("country_code","")
                lab2 = f"{flag(cc)}  {lab}"
                lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
                key = f"{lab2}|||{lat:.6f},{lon:.6f}"
                st.session_state._opts[key] = {"lat":lat,"lon":lon,"label":lab2,"addr":addr}
                out.append(key)
            return out
        except:
            return []
    selected = st_searchbox(nominatim_search, key="place", placeholder="Cerca… es. Champoluc, Plateau Rosa",
                            clear_on_submit=False, default=None)

# Defaults
lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_opts" in st.session_state:
    info = st.session_state._opts.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev else '—'} m</b></div>", unsafe_allow_html=True)

# ===================== DAY & WINDOWS =====================
cdate, ctz = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno", value=date.today())
with ctz:
    tzname = "Europe/Rome"
    st.text_input("Fuso orario", tzname, disabled=True)

st.subheader("1) Finestre A · B · C")
def tt(h,m): return time(h,m)
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   tt(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", tt(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   tt(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", tt(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   tt(16,0), key="C_e")

st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)

# ===================== OPEN-METEO =====================
def fetch_open_meteo(lat,lon,tzname):
    r = requests.get("https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone=tzname,
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7
        ),
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def build_df(js, hours):
    H = js["hourly"]; df = pd.DataFrame(H)
    # open-meteo times sono localizzati alla timezone richiesta; trattiamoli come naive locali
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    if "relative_humidity_2m" in df:
        out["RH"] = df["relative_humidity_2m"].astype(float)
    else:
        out["RH"] = np.nan
    out["td"]   = df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100.0).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)   # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"] = df.get("weathercode",0).astype(int)
    return out

def prp_type_row(row):
    if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes={71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# ===================== QUICK WINS INPUTS =====================
def calc_RH_from_T_Td(T, Td):
    # Magnus-Tetens (Tetens) with numpy – returns %
    T = np.asarray(T, float); Td = np.asarray(Td, float)
    es = 6.112 * np.exp((17.67 * T) / (T + 243.5))
    e  = 6.112 * np.exp((17.67 * Td) / (Td + 243.5))
    RH = 100.0 * (e / es)
    return np.clip(RH, 1.0, 100.0)

def wet_bulb_stull(T, RH):
    # Stull (2011) approximation, degC – vectorized
    T  = np.asarray(T, float)
    RH = np.clip(np.asarray(RH, float), 1.0, 100.0)
    # formula uses radians with atan
    Tw = (T*np.arctan(0.151977*np.sqrt(RH + 8.313659))
          + np.arctan(T + RH)
          - np.arctan(RH - 1.676331)
          + 0.00391838*(RH**1.5)*np.arctan(0.023101*RH)
          - 4.686035)
    return Tw

def effective_wind(w_ms):
    # diminishing returns: log1p, cap 0..8 m/s
    w = np.clip(np.asarray(w_ms, float), 0.0, 8.0)
    return np.log1p(w) / np.log1p(8.0)  # 0..1

def clear_sky_SW(lat, doy, hour_local):
    # very small clear-sky proxy (~1000 W/m2 midday) with cosine of solar hour angle
    # we keep it simple & robust: day-length approx with latitude
    latr = np.radians(lat)
    # declination (approx)
    decl = 23.44*np.pi/180*np.sin(2*np.pi*(284 + doy)/365.0)
    # hour angle from local solar noon (assume noon at 13 winter -> keep symmetric)
    h = (hour_local-12.0) * np.pi/12.0
    mu = np.sin(latr)*np.sin(decl) + np.cos(latr)*np.cos(decl)*np.cos(h)
    mu = np.clip(mu, 0.0, 1.0)
    SW_clear = 950.0 * mu   # W/m2
    return SW_clear

def downwelling_SW(lat, times, cloud, sunup):
    # Ineichen-like very light reduction: SW_down ≈ SW_clear * (1 - 0.75*cloud^3)
    t = pd.to_datetime(times)
    doy  = t.dayofyear.values
    hour = t.dt.hour.values.astype(float)
    SWc = clear_sky_SW(lat, doy, hour)
    cloud = np.clip(np.asarray(cloud, float), 0.0, 1.0)
    SW = SWc * (1.0 - 0.75*(cloud**3))
    SW *= (np.asarray(sunup, int) > 0)  # zero at night
    return SW  # W/m2

def snow_age_hours(snowfall, times):
    # hours since last snowfall (>0) – robust & vectorized with a small loop (fast enough for <=168 rows)
    ts = pd.to_datetime(times).values
    snow = np.asarray(snowfall, float) > 0.0
    age = np.zeros_like(snow, dtype=float)
    last = None
    for i, (t, s) in enumerate(zip(ts, snow)):
        if s: last = t
        age[i] = 0.0 if last is None else (ts[i] - last)/np.timedelta64(1, 'h')
    return age

def dynamic_albedo(age_h, T2m):
    # 0.85 (fresh) → 0.55 (old/wet). Faster decay when T>0.
    age = np.asarray(age_h, float)
    warm = (np.asarray(T2m, float) > 0.0).astype(float)
    # logistic decay from 0 to 1 around 36 h; speed up if warm
    decay = 1.0 / (1.0 + np.exp(-(age-36.0)/(8.0 - 3.0*warm)))
    alb = 0.85 - 0.30*decay - 0.05*warm
    return np.clip(alb, 0.55, 0.85)

# ===================== SNOW TEMPERATURE & SPEED INDEX =====================
def snow_temperature_model(df, lat):
    X = df.copy()
    # Fill RH if missing via T & Td
    if X["RH"].isna().any():
        X["RH"] = calc_RH_from_T_Td(X["T2m"], X["td"])
    else:
        X["RH"] = np.clip(X["RH"].astype(float), 1.0, 100.0)
    # Wet-bulb
    X["Tw"] = wet_bulb_stull(X["T2m"], X["RH"])
    # Precip type
    X["ptyp"] = X.apply(prp_type_row, axis=1)
    # Effective wind 0..1
    X["w_eff"] = effective_wind(X["wind"])
    # Downwelling shortwave (W/m2) reduced by cloud
    X["SW_down"] = downwelling_SW(lat, X["time"], X["cloud"], X["sunup"])
    # Snow age (h) & albedo
    X["age_h"] = snow_age_hours(X["snowfall"], X["time"])
    X["albedo"] = dynamic_albedo(X["age_h"], X["T2m"])

    # ---- Surface temperature
    # Start baseline as air temperature
    Tair = X["T2m"].values
    # Radiative cooling (night/clear): stronger when clear & calm
    clear = (1.0 - X["cloud"].values)
    night = (X["sunup"].values==0).astype(float)
    cool = (1.2 + 2.3*clear)*night*(1.0 - X["w_eff"].values)  # °C to subtract
    # Solar warming (day): proportional to absorbed SW (1-albedo), scaled ~ 4°C max
    absorbed = (X["SW_down"].values * (1.0 - X["albedo"].values)) / 900.0  # ~0..1.2
    warm = np.clip(absorbed, 0, 1.2) * 3.5  # °C to add
    # Wet conditions → clamp to 0°C
    wet_cond = (
        (X["ptyp"].isin(["rain","mixed"]).values) |
        ((X["ptyp"]=="snow").values & (Tair>-1.0)) |
        (Tair>0.0) |
        ((X["sunup"].values==1) & (X["cloud"].values<0.35) & (Tair>-2.0))
    )
    T_surf = Tair - cool + warm
    T_surf = np.where(wet_cond, 0.0, T_surf)
    # Gentle floor so it doesn't go crazy below air in the day
    T_surf = np.minimum(T_surf, Tair + 0.5)

    # ---- Top ~5 mm (relaxation on surface)
    tau_h = np.full(len(X), 6.0)
    tau_h[(X["ptyp"]!="none")] = 3.0
    tau_h[(X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3)] = 8.0
    alpha = 1.0 - np.exp(-1.0/np.asarray(tau_h,float))
    T_top5 = np.zeros(len(X), float)
    if len(X)>0:
        T_top5[0] = min(Tair[0], 0.0)
        for i in range(1,len(X)):
            T_top5[i] = T_top5[i-1] + alpha[i]*(T_surf[i] - T_top5[i-1])

    X["T_surf"] = np.round(T_surf, 2)
    X["T_top5"] = np.round(T_top5, 2)

    # ---- Speed (0..100): combine proximity to -0.5..0, wetness, RH, solar & grain age
    near0 = np.exp(-((X["T_surf"]+0.5)**2) / (2*1.8**2))  # bell around -0.5
    wet_pen = np.where((X["ptyp"].isin(["rain","mixed"])) | (X["T_surf"]>-0.3), 25, 0)
    rh_pen  = np.where((X["RH"]>90) & (X["T_surf"]>-2.0), 10, 0)
    age_bonus = np.clip(X["age_h"]/48.0, 0, 1)*8.0  # transformed snow glides more (up to a point)
    sol_bonus = np.clip(X["SW_down"]/600.0, 0, 1)*6.0
    base = (near0*70.0) + age_bonus + sol_bonus
    speed = np.clip(base - wet_pen - rh_pen, 0, 100)
    X["speed_index"] = np.round(speed, 0).astype(int)
    return X

def classify_snow_row(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista pioggia/neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.sunup==0 and row.cloud<0.4: return "Rigelata/ghiacciata"
    if row.sunup==1 and row.T_surf>-2 and row.cloud<0.3: return "Primaverile/trasformata"
    return "Compatta"

def reliability_from_h(h):
    x=float(h)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# ===================== WAX BRANDS & TUNING =====================
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
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure_name(T):
    if T<=-10: return "Linear Fine (S1) – freddo secco"
    if T<=-3:  return "Cross Hatch (S1) – universale freddo"
    if T<=0.5: return "Thumb Print / Diagonal (S2) – freddo umido"
    return "Wave / Scarico marcato (S2) – caldo bagnato"

def angles_for_discipline(T, disc):
    # base angles tuned by temperature
    base = 0.5 if T<=-8 else (0.7 if T<=-3 else (0.8 if T<=0.5 else 1.0))
    side_map = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}
    return side_map.get(disc,88.0), base

# ===================== UI – ACTION =====================
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon,tzname)
        raw = build_df(js, hours)
        res = snow_temperature_model(raw, lat)

        # ---------- Table (clean) ----------
        table = pd.DataFrame({
            "Ora": res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria °C": res["T2m"].round(1),
            "Td °C": res["td"].round(1),
            "UR %": res["RH"].round(0),
            "Tw °C": res["Tw"].round(1),
            "Vento m/s": res["wind"].round(1),
            "Nuvolosità %": (res["cloud"]*100).round(0),
            "Prp mm/h": res["prp_mmph"].round(2),
            "Tipo": res["ptyp"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf °C": res["T_surf"].round(1),
            "T top5mm °C": res["T_top5"].round(1),
            "Scorrevolezza": res["speed_index"].astype(int)
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # ---------- Graphs ----------
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(figsize=(8,3))
        plt.plot(t, res["T2m"], label="T aria")
        plt.plot(t, res["T_surf"], label="T neve (surf)")
        plt.plot(t, res["T_top5"], label="T neve (top5)")
        plt.title("Temperature")
        plt.ylabel("°C"); plt.xticks(rotation=15); plt.legend()
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(8,2.6))
        plt.bar(t, res["prp_mmph"])
        plt.title("Precipitazione (mm/h)"); plt.xticks(rotation=15)
        st.pyplot(fig2)

        # ---------- Blocks A/B/C ----------
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        tzobj = tz.gettz(tzname)

        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            # Filter the selected local day
            day_mask = res["time"].dt.date == target_day
            day_df = res[day_mask].copy()
            if day_df.empty:
                W = res.head(6).copy()
            else:
                cut = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                W = cut if not cut.empty else day_df.head(6)

            if W.empty:
                st.info("Nessun dato disponibile nella finestra selezionata.")
                continue

            t_med = float(W["T_surf"].mean())
            kstate = classify_snow_row(W.iloc[0])
            # reliability proxy: closer in time → higher
            # (index distance from start, translate to ~hours ahead)
            idx0 = W.index.min() - res.index.min()
            rel = reliability_from_h(idx0)

            st.markdown(
                f"<div class='banner'><b>Condizioni:</b> {kstate} · "
                f"<b>T neve media</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}%</div>",
                unsafe_allow_html=True
            )

            # Structure name
            st.markdown(f"**Struttura consigliata:** {recommended_structure_name(t_med)}")

            cW1, cW2 = st.columns([1,1])

            # ---- Brand wax suggestions
            with cW1:
                st.markdown("**Scioline (per T neve media):**")
                cols1 = st.columns(4); cols2 = st.columns(4)
                for i,(name,bands) in enumerate(BRANDS[:4]):
                    rec = pick_wax(bands, t_med)
                    cols1[i].markdown(f"<div class='card' style='padding:.6rem'><b>{name}</b><br><span style='color:#a9bacb'>{rec}</span></div>", unsafe_allow_html=True)
                for i,(name,bands) in enumerate(BRANDS[4:]):
                    rec = pick_wax(bands, t_med)
                    cols2[i].markdown(f"<div class='card' style='padding:.6rem'><b>{name}</b><br><span style='color:#a9bacb'>{rec}</span></div>", unsafe_allow_html=True)

            # ---- Mini-table window
            with cW2:
                mini = pd.DataFrame({
                    "Ora": W["time"].dt.strftime("%H:%M"),
                    "T aria": W["T2m"].round(1),
                    "T neve": W["T_surf"].round(1),
                    "UR%":   W["RH"].round(0),
                    "V m/s": W["wind"].round(1),
                    "Prp":   W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                })
                st.dataframe(mini, use_container_width=True, hide_index=True)

            # ---- Tuning by discipline (table SL/GS/SG/DH)
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base = angles_for_discipline(t_med, d)
                rows.append([d, recommended_structure_name(t_med), f"{side:.1f}°", f"{base:.1f}°"])
            st.markdown("**Tuning discipline:**")
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","SIDE","BASE"]))

        # ---------- Download ----------
        csv = res.copy(); csv["time"]=csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="telemark_forecast_snow.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
