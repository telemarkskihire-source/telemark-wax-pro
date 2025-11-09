# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark UI + algoritmi migliorati (Quick Wins) + blocchi + grafici

import os, math, base64, requests
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime, date, time, timedelta
from streamlit_searchbox import st_searchbox

# -------------------- THEME --------------------
PRIMARY = "#06b6d4"   # turchese
ACCENT  = "#f97316"   # arancio
OK      = "#10b981"
WARN    = "#f59e0b"
ERR     = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
h1,h2,h3,h4 {{ color:#fff }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding: .9rem .95rem; }}
.badge {{ display:inline-flex; gap:.5rem; align-items:center; background:#0b1220; border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{ border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0; padding:.75rem .9rem; border-radius:10px; font-size:.98rem; }}
.btn-primary button {{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important; }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e setup per blocchi A/B/C.")

# -------------------- UTIL --------------------
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

# -------------------- RICERCA CON PREFILTRO NAZIONE --------------------
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
    selected = st_searchbox(nominatim_search, key="place",
                            placeholder="Cerca… es. Champoluc, Plateau Rosa",
                            clear_on_submit=False, default=None)

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

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# -------------------- DATA: GIORNO + BLOCCHI --------------------
cdate = st.columns(1)[0]
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())

st.subheader("1) Finestre orarie A · B · C")
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
st.markdown("<span style='color:#9aa4af'>Suggerimento: &lt; 48h → stime più affidabili</span>", unsafe_allow_html=True)

# -------------------- OPEN-METEO --------------------
def fetch_open_meteo(lat, lon):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone="auto",
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7,
        ),
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])       # naive local time per Open-Meteo
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["RH"]   = (df["relative_humidity_2m"].astype(float)
                   if "relative_humidity_2m" in df else pd.Series(np.nan, index=df.index))
    # se manca RH calcoliamo da T/td più avanti
    out["td"]   = (df["dew_point_2m"].astype(float)
                   if "dew_point_2m" in df else out["T2m"] - 2.0)
    out["cloud"]= (df["cloudcover"].astype(float)/100.0).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df.get("rain",0.0) if isinstance(df.get("rain",0.0), pd.Series) else pd.Series(0.0, index=df.index)
    out["rain"] = out["rain"].astype(float)
    out["snowfall"] = df.get("snowfall",0.0) if isinstance(df.get("snowfall",0.0), pd.Series) else pd.Series(0.0, index=df.index)
    out["snowfall"] = out["snowfall"].astype(float)
    out["wcode"] = (df.get("weathercode",0) if isinstance(df.get("weathercode",0), pd.Series) else pd.Series(0, index=df.index)).astype(int)
    return out

# -------------------- QUICK WINS (INPUT) --------------------
def rh_from_T_Td(T, Td):
    """RH (%) da T e Td (Magnus)."""
    T = np.asarray(T, dtype=float); Td = np.asarray(Td, dtype=float)
    a, b = 17.625, 243.04
    es  = 6.1094*np.exp(a*T /(b+T))
    esd = 6.1094*np.exp(a*Td/(b+Td))
    RH = np.clip(100.0*esd/es, 1.0, 100.0)
    return RH

def wet_bulb_stull(T, RH):
    """Bulbo umido (°C) – Stull 2011, T in °C, RH in % (numpy)."""
    T = np.asarray(T, dtype=float)
    RH = np.clip(np.asarray(RH, dtype=float), 1.0, 100.0)
    Tw = T*np.arctan(0.151977*np.sqrt(RH+8.313659)) + \
         np.arctan(T+RH) - np.arctan(RH-1.676331) + \
         0.00391838*np.power(RH,1.5)*np.arctan(0.023101*RH) - 4.686035
    return Tw

def wind_effect(wind_ms):
    """0..1, log con saturazione ~8 m/s."""
    w = np.clip(np.asarray(wind_ms, dtype=float), 0.0, 8.0)
    return np.log1p(w)/np.log1p(8.0)

def solar_clear_ghi(lat_deg, times):
    """Stima clear-sky semplice: GHI_clear ≈ 990 * cos(zenith)+ (clip>=0)."""
    lat = np.deg2rad(lat_deg)
    t = pd.to_datetime(times)
    doy = t.dayofyear.values.astype(float)
    # declinazione (Cooper)
    delta = 23.45*np.pi/180.0 * np.sin(2*np.pi*(284 + doy)/365.0)
    # ora locale → angolo orario rispetto a mezzogiorno solare approx
    frac_hour = t.dt.hour.values + t.dt.minute.values/60.0
    h_ang = (frac_hour - 12.0) * (np.pi/12.0)
    cosz = np.sin(lat)*np.sin(delta) + np.cos(lat)*np.cos(delta)*np.cos(h_ang)
    cosz = np.clip(cosz, 0, 1)
    return 990.0*cosz  # W/m2

def sw_down(lat, times, cloud):
    """SW_down ≈ SW_clear * (1 - 0.75*cloud^3)."""
    clr = solar_clear_ghi(lat, times)
    c = np.clip(np.asarray(cloud, dtype=float), 0.0, 1.0)
    return clr * (1.0 - 0.75*np.power(c,3.0))

def dynamic_albedo(snowfall, T2m):
    """Albedo stimato 0.55–0.85 in base a età neve e T>0."""
    sf = np.asarray(snowfall, dtype=float)
    T = np.asarray(T2m, dtype=float)
    hrs = np.arange(len(sf))
    last_snow_idx = np.maximum.accumulate(np.where(sf>0.5, hrs, -10**6))
    hours_since = hrs - last_snow_idx
    albedo = np.where(hours_since <= 24, 0.85,
              np.where(hours_since <= 72, 0.75, 0.65))
    # neve “cotta” se T>0 nelle ultime 6h
    warm = pd.Series(T).rolling(6, min_periods=1).max().values > 0.0
    albedo = np.where(warm, np.maximum(0.55, albedo-0.1), albedo)
    return albedo

# -------------------- PRECIP TYPE --------------------
def prp_type_row(row):
    if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# -------------------- MODELLO NEVE (con Quick Wins) --------------------
def snow_temperature_model(df: pd.DataFrame, lat_deg: float, dt_hours=1.0):
    X = df.copy()
    # RH se mancante
    if X["RH"].isna().any():
        X["RH"] = rh_from_T_Td(X["T2m"].values, X["td"].values)

    # Wet-bulb (non usato direttamente come T_surf ma utile per umidità/penalità)
    X["Tw"] = wet_bulb_stull(X["T2m"].values, X["RH"].values)

    # tipologia prp
    X["ptyp"] = X.apply(prp_type_row, axis=1)

    # input “energetici”
    X["SW_down"] = sw_down(lat_deg, X["time"], X["cloud"])            # W/m2
    X["albedo"]  = dynamic_albedo(X["snowfall"].values, X["T2m"].values)
    X["wind_eff"]= wind_effect(X["wind"].values)                       # 0..1

    # inizializza
    n = len(X); Tsurf = np.zeros(n, dtype=float); Ttop5 = np.zeros(n, dtype=float)
    if n == 0:
        X["T_surf"]=np.nan; X["T_top5"]=np.nan; X["speed_index"]=0
        return X

    Tsurf[0] = min(X["T2m"].iloc[0], 0.0)
    Ttop5[0] = Tsurf[0]

    for i in range(1, n):
        Tair = float(X["T2m"].iloc[i])
        rh   = float(X["RH"].iloc[i])
        sun  = int(X["sunup"].iloc[i])==1
        cloud= float(X["cloud"].iloc[i])
        pt   = X["ptyp"].iloc[i]
        sw   = float(X["SW_down"].iloc[i]) * (1.0 - float(X["albedo"].iloc[i]))  # assorbita
        w    = float(X["wind_eff"].iloc[i])

        # base verso 0 in condizioni bagnate / prossimità 0°C
        wet = (pt in ["rain","mixed"]) or (pt=="snow" and Tair>-1.0) or (Tair>0.0) or (sun and cloud<0.35 and Tair>-2.0)
        if wet:
            T_eq = 0.0
        else:
            # equilibrio secco: aria - raffr. radiativo + riscaldamento SW
            drad = (1.8 + 3.3*(1.0-cloud) - 0.35*(w*8.0)).clip(0.5, 5.0)  # °C
            heat_sw = 0.002*sw                                           # °C per passo (tarabile)
            T_eq = Tair - drad + heat_sw

        # rilassamento esponenziale verso T_eq con tau variabile
        tau = 6.0
        if wet or w>=0.75: tau = 3.0
        if (not wet) and (not sun) and (w<0.25) and (cloud<0.3): tau = 8.0
        alpha = 1.0 - math.exp(-dt_hours / tau)

        Tsurf[i] = Tsurf[i-1] + alpha*(T_eq - Tsurf[i-1])
        # strato top ~5mm più lento
        alpha2 = 1.0 - math.exp(-dt_hours / (tau+1.5))
        Ttop5[i] = Ttop5[i-1] + alpha2*(Tsurf[i] - Ttop5[i-1])

    X["T_surf"] = np.round(Tsurf, 2)
    X["T_top5"] = np.round(Ttop5, 2)

    # Indice scorrevolezza 0..100
    near0 = (np.abs(X["T_surf"].values) < 0.6)
    base_speed = 100 - np.clip(np.abs(X["T_surf"].values + 6.0)*7.5, 0, 100)   # picco ~ -6°C
    wet_pen   = (X["ptyp"].isin(["rain","mixed"]).values | near0)*25
    sticky    = ((X["RH"].values>90) & (X["T_surf"].values>-1.0))*10
    sw_boost  = np.clip(X["SW_down"].values/800.0,0,1)*5   # un filo di boost col sole
    speed_idx = np.clip(base_speed - wet_pen - sticky + sw_boost, 0, 100)
    X["speed_index"] = np.round(speed_idx, 0)

    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.cloud<0.4 and row.sunup==0: return "Rigelata/ghiacciata"
    if row.sunup==1 and row.T_surf>-2 and row.cloud<0.3: return "Primaverile/trasformata"
    return "Compatta"

def reliability(hours_ahead):
    x = float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# -------------------- SCIOLINE & STRUTTURE --------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix",None,SWIX),("Toko",None,TOKO),("Vola",None,VOLA),("Rode",None,RODE),
          ("Holmenkol",None,HOLM),("Maplus",None,MAPL),("Start",None,START),("Skigo",None,SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (freddo/secco)"
    if Tsurf <= -3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf <= 0.5: return "Diagonal / Scarico a V (umido)"
    return "Wave / Scarico marcato (bagnato caldo)"

def edge_table_for(T):
    # angoli indicativi per disciplina
    rows=[]
    for d in ["SL","GS","SG","DH"]:
        if T <= -10:
            fam = "Linear Fine"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]
        elif T <= -3:
            fam = "Cross Hatch leggera"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]
        else:
            fam = "Diagonal / V"; base = 0.8 if T<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]
        rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
    return pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"])

# -------------------- CALCOLO --------------------
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon)
        raw = build_df(js, hours)
        res = snow_temperature_model(raw, lat_deg=lat, dt_hours=1.0)

        # ---- TABELLA COMPLETA ORDINATA ----
        show = pd.DataFrame({
            "Ora":    res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["td"].round(1),
            "UR (%)":      res["RH"].round(0),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità (%)":  (res["cloud"]*100).round(0),
            "Rad. SW ↓ (W/m²)": res["SW_down"].round(0),
            "Prp (mm/h)":  res["prp_mmph"].round(2),
            "Tipo prp":    res["ptyp"].map({"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "Indice scorrevolezza": res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- GRAFICI ----
        t = res["time"]
        fig1 = plt.figure(figsize=(8,3)); ax=plt.gca()
        ax.plot(t, res["T2m"], label="T aria")
        ax.plot(t, res["T_surf"], label="T neve surf")
        ax.plot(t, res["T_top5"], label="T top 5mm")
        ax.grid(True, alpha=.2); ax.set_ylabel("°C"); ax.set_title("Temperature")
        ax.legend()
        st.pyplot(fig1)

        fig2 = plt.figure(figsize=(8,3)); ax=plt.gca()
        ax.bar(t, res["prp_mmph"], width=0.03, align="center")
        ax.set_title("Precipitazione (mm/h)"); ax.grid(True, alpha=.2)
        st.pyplot(fig2)

        # ---- BLOCCHI A/B/C ----
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            day_mask = (res["time"].dt.date == target_day)
            day_df = res[day_mask].copy()
            if day_df.empty:
                W = res.head(6).copy()
            else:
                W = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                if W.empty: W = day_df.head(6)

            t_med = float(W["T_surf"].mean()) if not W.empty else 0.0
            k = classify_snow(W.iloc[0]) if not W.empty else "—"
            rel = reliability( (W.index[0] - res.index.min()) if not W.empty else 0 )

            st.markdown(
                f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                f"<b>T_neve med</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}% · "
                f"<b>Struttura:</b> {recommended_structure(t_med)}</div>",
                unsafe_allow_html=True
            )

            # Scioline per temperatura neve media
            st.markdown("**Scioline suggerite (T neve media):**")
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(name,_,bands) in enumerate(BRANDS[:4]):
                cols1[i].markdown(f"<div class='card'><b>{name}</b><br><span style='color:#a9bacb'>{pick_wax(bands, t_med)}</span></div>", unsafe_allow_html=True)
            for i,(name,_,bands) in enumerate(BRANDS[4:]):
                cols2[i].markdown(f"<div class='card'><b>{name}</b><br><span style='color:#a9bacb'>{pick_wax(bands, t_med)}</span></div>", unsafe_allow_html=True)

            # Mini tabella finestra
            if not W.empty:
                mini = pd.DataFrame({
                    "Ora": W["time"].dt.strftime("%H:%M"),
                    "T aria": W["T2m"].round(1),
                    "T neve": W["T_surf"].round(1),
                    "UR%":   W["RH"].round(0),
                    "V m/s": W["wind"].round(1),
                    "Prp":   W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                })
                st.dataframe(mini, use_container_width=True, hide_index=True)
            else:
                st.info("Nessun dato nella finestra scelta.")

            # Tabella tuning per discipline (angoli + struttura)
            st.markdown("**Tuning per discipline (indicativo):**")
            st.dataframe(edge_table_for(t_med), use_container_width=True, hide_index=True)

        # ---- Download CSV ----
        csv = res.copy(); csv["time"] = csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo",
                           data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv",
                           mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
