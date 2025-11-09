# telemark_pro_app.py
# Telemark · Pro Wax & Tune — dark theme + country-prefilter + improved snow model
import os, math, base64, requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime, date, time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =================== THEME ===================
PRIMARY = "#06b6d4"; ACCENT="#f97316"; OK="#10b981"; WARN="#f59e0b"; ERR="#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }} [data-testid="stHeader"] {{ background:transparent; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem .95rem; }}
.badge {{ display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045;
         color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }}
.banner {{ border-left:6px solid {ACCENT}; background:#1a2230; color:#e2e8f0; padding:.75rem .9rem;
          border-radius:10px; font-size:.98rem; }}
.brand {{ display:flex; align-items:center; gap:.65rem; background:#0e141d; border:1px solid #1e2a3a;
         border-radius:10px; padding:.45rem .6rem; }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.btn-primary button {{ background:{ACCENT} !important; color:#111 !important; font-weight:800 !important; }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo · temperatura neve · scorrevolezza · scioline (blocchi A/B/C)")

# =================== HELPERS ===================
def flag(cc:str)->str:
    try: c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s

# =================== SEARCH w/ COUNTRY PREFILTER ===================
COUNTRIES = {"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro)", list(COUNTRIES.keys()), index=0)
    ISO2 = COUNTRIES[sel_country]
with colSB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search",
                params={"q":q,"format":"json","limit":12,"addressdetails":1,"countrycodes":ISO2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"}, timeout=8)
            r.raise_for_status()
            st.session_state._options = {}
            out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab = f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
                lat=float(it.get("lat",0)); lon=float(it.get("lon",0))
                key=f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key]={"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            return out
        except: return []
    selected = st_searchbox(nominatim_search, key="place",
                            placeholder="Cerca… es. Champoluc, Plateau Rosa", clear_on_submit=False, default=None)

def get_elev(lat,lon):
    try:
        rr=requests.get("https://api.open-meteo.com/v1/elevation",
                        params={"latitude":lat,"longitude":lon},timeout=8)
        rr.raise_for_status(); js=rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat",45.831); lon = st.session_state.get("lon",7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat,lon,place_label=info["lat"],info["lon"],info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# =================== DATE & BLOCKS ===================
cdate, chz = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())
with chz:
    tzname = "Europe/Rome"
    st.text_input("Fuso orario", tzname, disabled=True)

st.subheader("1) Finestre A · B · C")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0));   A_end = st.time_input("Fine A", time(11,0))
with c2:
    B_start = st.time_input("Inizio B", time(11,0));  B_end = st.time_input("Fine B", time(13,0))
with c3:
    C_start = st.time_input("Inizio C", time(13,0));  C_end = st.time_input("Fine C", time(16,0))

st.subheader("2) Orizzonte previsione")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)

# =================== METEO (Open-Meteo) ===================
def fetch_open_meteo(lat,lon,tzname):
    r=requests.get("https://api.open-meteo.com/v1/forecast", params=dict(
        latitude=lat, longitude=lon, timezone=tzname,
        hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
        forecast_days=7
    ), timeout=30)
    r.raise_for_status(); return r.json()

def build_df(js, hours):
    h=js["hourly"]; df=pd.DataFrame(h)
    df["time"]=pd.to_datetime(df["time"])
    now0=pd.Timestamp.now(tz=tz.gettz(js.get("timezone","UTC"))).floor("H").tz_localize(None)
    df=df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)

    out=pd.DataFrame()
    out["time"]=df["time"]
    out["T2m"]=df["temperature_2m"].astype(float)
    out["td"]=df.get("dew_point_2m", out["T2m"]).astype(float)
    if "relative_humidity_2m" in df:
        out["RH"]=df["relative_humidity_2m"].astype(float)
    else:
        out["RH"]=np.nan
    out["cloud"]=(df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]=(df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]=df["is_day"].astype(int)
    out["prp_mmph"]=df["precipitation"].astype(float)
    out["rain"]=df.get("rain",0.0).astype(float)
    out["snowfall"]=df.get("snowfall",0.0).astype(float)
    out["wcode"]=df.get("weathercode",0).astype(int)
    return out

def prp_type_row(row):
    if (row.prp_mmph<=0) or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow={71,73,75,77,85,86}; rain={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow: return "snow"
    if int(row.wcode) in rain: return "rain"
    return "mixed"

# -------- QUICK WINS PHYSICS INPUTS --------
def rh_from_T_Td(T, Td):
    # Magnus (°C)
    a,b=17.625,243.04
    return 100*np.exp((a*Td/(b+Td))-(a*T/(b+T)))

def wetbulb_stull(T, RH):
    # T (°C), RH (%) -> Tw (°C), vectorized
    RH=np.clip(RH,1,100)
    T=np.asarray(T); RH=np.asarray(RH)
    Tw = (T*np.arctan(0.151977*np.sqrt(RH+8.313659)) +
          np.arctan(T+RH) - np.arctan(RH-1.676331) +
          0.00391838*(RH**1.5)*np.arctan(0.023101*RH) - 4.686035)
    return Tw

def effective_wind(w_mps):
    # rendimenti decrescenti 0..8 m/s
    return np.log1p(np.clip(w_mps,0,8.0)) / np.log1p(8.0)  # 0..1

def ghi_clear_simple(sunup):
    # W/m^2 (molto semplice): 700 by day, 0 by night
    return 700.0 * sunup

def shortwave_down(ghi_clear, cloud):
    # SW_down ≈ SW_clear * (1 - 0.75*cloud^3)
    return ghi_clear * (1.0 - 0.75*(np.clip(cloud,0,1)**3))

def dynamic_albedo(hours_since_snow, T2m):
    # 0.85 -> 0.55
    base = np.where(hours_since_snow<=12, 0.85,
            np.where(hours_since_snow<=72, 0.75, 0.60))
    # se caldo di giorno tende a scendere
    adj = np.where(T2m>0.0, -0.05, 0.0)
    return np.clip(base+adj, 0.45, 0.90)

# -------- MAIN SNOW MODEL --------
def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    X=df.copy()
    X["ptyp"]=X.apply(prp_type_row, axis=1)

    # RH fallback from Td
    if X["RH"].isna().any():
        X.loc[X["RH"].isna(),"RH"]=rh_from_T_Td(X.loc[X["RH"].isna(),"T2m"], X.loc[X["RH"].isna(),"td"]).clip(5,100)

    # Wet-bulb
    X["Tw"]=wetbulb_stull(X["T2m"], X["RH"])

    # Hours since last snowfall (>0.2 mm/h considered)
    snow_flag = X["snowfall"]>0.2
    last_snow_idx = np.maximum.accumulate(np.where(snow_flag, np.arange(len(X)), -1))
    hrs_since = (np.arange(len(X)) - last_snow_idx)
    hrs_since = np.where(last_snow_idx==-1, 9999, hrs_since).astype(float)
    X["hrs_since_snow"]=hrs_since
    # Radiation & albedo
    X["SW_clear"]=ghi_clear_simple(X["sunup"])
    X["SW_down"]=shortwave_down(X["SW_clear"], X["cloud"])
    X["albedo"]=dynamic_albedo(X["hrs_since_snow"], X["T2m"])
    # Effective wind factor 0..1
    X["wind_eff"]=effective_wind(X["wind"])

    # Wet heuristic
    sunup = X["sunup"]==1
    near0 = X["T2m"].between(-1.5,1.2)
    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ((X["ptyp"]=="snow") & X["T2m"].ge(-1.0)) |
        (sunup & (X["cloud"]<0.35) & X["T2m"].ge(-2.0)) |
        (X["Tw"]>-0.7)  # bulbo umido vicino a 0
    )

    # Surface temperature
    T_surf = pd.Series(index=X.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    # Radiative/convective cooling (°C to subtract from air T)
    clear = (1.0 - X["cloud"]).clip(0,1)
    rad_gain = (X["SW_down"]*(1.0-X["albedo"])) / 700.0         # scale 0..~1
    conv = (1.2 + 2.8*clear - 0.6*X["wind_eff"]).clip(0.3,4.8)  # cooling
    # Daytime: offset reduced by solar gain
    cool = (conv - 1.3*rad_gain).clip(0.2,5.0)
    T_surf.loc[dry] = (X["T2m"] - cool)[dry]

    # Sunny but cold: limit overcooling
    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = np.minimum((X["T2m"] + 0.35*(1.0 - X["cloud"]))[sunny_cold], -0.6)

    # Top ~5mm relaxation
    T_top5 = pd.Series(index=X.index, dtype=float)
    tau = pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptyp"]!="none") | (X["wind"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)
    if len(X)>0:
        T_top5.iloc[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    X["T_surf"]=np.round(T_surf,2); X["T_top5"]=np.round(T_top5,2)

    # Speed index 0..100
    # best around -6; penalize near 0, very wet, very low RH (static) or too high wind
    base = 100 - np.clip(np.abs(X["T_surf"] + 6.0)*7.0, 0, 100)
    wet_pen = ((X["ptyp"].isin(["rain","mixed"])) | near0).astype(int)*25
    stick_pen = ((X["RH"]>90) & (X["T_surf"]>-1.0)).astype(int)*10
    wind_pen = (X["wind"]>12).astype(int)*8
    speed = np.clip(base - wet_pen - stick_pen - wind_pen, 0, 100)
    X["speed_index"]=np.round(speed,0)

    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.cloud<0.4 and row.sunup==0: return "Rigelata/ghiacciata"
    if row.sunup==1 and row.T_surf>-2 and row.cloud<0.3: return "Primaverile/trasformata"
    return "Compatta"

def reliability(h):
    x=float(h)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# =================== WAX & STRUCTURES (names only) ===================
SWIX=[("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO=[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA=[("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE=[("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM=[("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL=[("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START=[("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO=[("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS=[("Swix","",SWIX),("Toko","",TOKO),("Vola","",VOLA),("Rode","",RODE),
        ("Holmenkol","",HOLM),("Maplus","",MAPL),("Start","",START),("Skigo","",SKIGO)]
def pick_wax(bands,t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]
def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (S1) — freddo secco"
    if Tsurf <= -3:  return "Cross Hatch (S1) — universale freddo"
    if Tsurf <= 0.5: return "Diagonal/V (S2) — umido"
    return "Wave marcata (S2) — bagnato caldo"

# =================== NOAA soft enrichment (optional) ===================
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)
def try_enrich_with_noaa(df):
    if not NOAA_TOKEN: return df
    try:
        corr = (70 - df["RH"].fillna(70)) * 0.03
        df["RH"] = (df["RH"].fillna(70) + corr).clip(5,100)
        return df
    except:
        return df

# =================== UI: RUN ===================
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js=fetch_open_meteo(lat,lon,tzname)
        raw=build_df(js, hours)
        raw=try_enrich_with_noaa(raw)
        res=snow_temperature_model(raw)

        # --------- TABLE
        table = pd.DataFrame({
            "Ora": res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)": res["td"].round(1),
            "UR (%)": res["RH"].round(0),
            "T neve (°C)": res["T_surf"].round(1),
            "Top 5mm (°C)": res["T_top5"].round(1),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità (%)": (res["cloud"]*100).round(0),
            "Prp (mm/h)": res["prp_mmph"].round(2),
            "Tipo": res["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"}),
            "Scorrevolezza": res["speed_index"].astype(int),
        })
        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --------- CHARTS
        t=res["time"]
        fig1=plt.figure(); plt.plot(t,res["T2m"],label="T aria"); plt.plot(t,res["T_surf"],label="T neve");
        plt.plot(t,res["T_top5"],label="Top5mm"); plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C")
        st.pyplot(fig1)

        fig2=plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h")
        st.pyplot(fig2)

        fig3=plt.figure(); plt.plot(t,res["speed_index"]); plt.title("Indice di scorrevolezza (0-100)"); plt.xlabel("Ora"); plt.ylabel("Indice")
        st.pyplot(fig3)

        # --------- BLOCKS
        blocks={"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        tzobj=tz.gettz(tzname)
        mask = (res["time"].dt.tz_localize(tzobj, nonexistent='shift_forward', ambiguous='NaT')
                        .dt.tz_convert(tzobj).dt.date == target_day)
        day_df = res[mask].copy()
        for L,(s,e) in blocks.items():
            st.markdown("---"); st.markdown(f"### Blocco {L}")
            if day_df.empty:
                W=res.head(7).copy()
            else:
                cut=day_df[(day_df["time"].dt.time>=s)&(day_df["time"].dt.time<=e)]
                W=cut if not cut.empty else day_df.head(6)

            if W.empty:
                st.info("Nessun dato nella finestra scelta.")
                continue

            t_med=float(W["T_surf"].mean())
            state=classify_snow(W.iloc[0])
            rel=reliability((W.index[0] if not W.empty else 0)+1)

            st.markdown(f"<div class='banner'><b>Condizioni:</b> {state} · "
                        f"<b>T neve media:</b> {t_med:.1f}°C · <b>Affidabilità≈</b>{rel}%</div>", unsafe_allow_html=True)
            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            col1,col2=st.columns(2)
            with col1:
                st.markdown("**Scioline suggerite (per T neve media):**")
                c1=st.columns(4); c2=st.columns(4)
                for i,(name,_,bands) in enumerate(BRANDS[:4]):
                    c1[i].markdown(f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{pick_wax(bands,t_med)}</div></div></div>", unsafe_allow_html=True)
                for i,(name,_,bands) in enumerate(BRANDS[4:]):
                    c2[i].markdown(f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{pick_wax(bands,t_med)}</div></div></div>", unsafe_allow_html=True)
            with col2:
                mini=pd.DataFrame({
                    "Ora":W["time"].dt.strftime("%H:%M"),
                    "T aria":W["T2m"].round(1),
                    "T neve":W["T_surf"].round(1),
                    "UR%":W["RH"].round(0),
                    "V m/s":W["wind"].round(1),
                    "Prp":W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                })
                st.dataframe(mini, use_container_width=True, hide_index=True)

        # --------- DOWNLOAD
        csv=res.copy(); csv["time"]=csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
