# telemark_pro_app.py
# -------------------
# Telemark · Pro Wax & Tune (tema scuro + algoritmo neve migliorato con Quick Wins NASA/NOAA style)

import os, math, base64, requests, pandas as pd
import streamlit as st
from datetime import datetime, date, time, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =============== Tema & stile (dark) ===============
PRIMARY = "#06b6d4"
ACCENT  = "#f97316"
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
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{
  border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0;
  padding:.75rem .9rem; border-radius:10px; font-size:.98rem;
}}
.brand {{
  display:flex; align-items:center; gap:.65rem; background:#0e141d;
  border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem;
}}
.brand img {{ height:22px }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline – blocchi A / B / C.")

# =============== Utils ===============
def flag(cc):
    try: 
        return chr(127397+ord(cc[0].upper()))+chr(127397+ord(cc[1].upper()))
    except: return "🏳️"

def concise_label(addr,fallback):
    name = (addr.get("hamlet") or addr.get("village") or addr.get("town") or 
            addr.get("city") or fallback)
    region = addr.get("state") or addr.get("region") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, region] if p])
    return f"{s} — {cc}"

# =============== Ricerca località con prefiltro paese ===============
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Svezia":"SE","Norvegia":"NO","Germania":"DE"
}
colA,colB = st.columns([1,3])
with colA:
    sel_country = st.selectbox("Nazione", list(COUNTRIES.keys()), index=0)
    iso2 = COUNTRIES[sel_country]

with colB:
    def nominatim(q):
        if not q or len(q)<2: return []
        try:
            r=requests.get("https://nominatim.openstreetmap.org/search",
                params={"q":q,"format":"json","limit":10,"addressdetails":1,"countrycodes":iso2.lower()},
                headers={"User-Agent":"telemark-pro"},timeout=8)
            r.raise_for_status()
            opts={}
            out=[]
            for it in r.json():
                lat,lon=float(it["lat"]),float(it["lon"])
                addr=it["address"]
                label=f"{flag(addr.get('country_code',''))}  {concise_label(addr,it['display_name'])}"
                key=f"{label}|||{lat:.6f},{lon:.6f}"
                opts[key]={"lat":lat,"lon":lon,"label":label}
                st.session_state["_opts"]=opts
                out.append(key)
            return out
        except: return []

    sel = st_searchbox(nominatim, key="search", placeholder="Cerca… es. Champoluc, Cervinia")

if sel and "_opts" in st.session_state:
    info = st.session_state["_opts"][sel]
    lat,lon = info["lat"],info["lon"]
    place_label = info["label"]
else:
    lat,lon = 45.83,7.73
    place_label = "🇮🇹 Champoluc — IT"

# Altitudine
def get_elev(lat,lon):
    try:
        r=requests.get("https://api.open-meteo.com/v1/elevation",params={"latitude":lat,"longitude":lon},timeout=8)
        return float(r.json()["elevation"][0])
    except: return None

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev else '—'} m</b></div>",unsafe_allow_html=True)

# =============== Giorno & blocchi ===============
target_day = st.date_input("Giorno", date.today())

st.subheader("Finestre orarie blocchi")
c1,c2,c3 = st.columns(3)
A_start,A_end = c1.time_input("A inizio",time(9,0)),c1.time_input("A fine",time(11,0))
B_start,B_end = c2.time_input("B inizio",time(11,0)),c2.time_input("B fine",time(13,0))
C_start,C_end = c3.time_input("C inizio",time(13,0)),c3.time_input("C fine",time(16,0))

hours = st.slider("Ore previsione",12,168,72,12)

# =============== Meteo ===============
def fetch_open_meteo(lat,lon):
    r = requests.get("https://api.open-meteo.com/v1/forecast",
        params=dict(latitude=lat,longitude=lon,timezone="Europe/Rome",
        hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
        forecast_days=7),timeout=30)
    r.raise_for_status()
    return r.json()

# =============== Quick Wins implementati ===============
def build_df(js,hours):
    h=js["hourly"]; df=pd.DataFrame(h)
    df["time"]=pd.to_datetime(df["time"])
    now0=pd.Timestamp.now().floor("H")
    df=df[df["time"]>=now0].head(hours).reset_index(drop=True)

    out=pd.DataFrame()
    out["time"]=df["time"]
    out["T2m"]=df["temperature_2m"].astype(float)

    if "relative_humidity_2m" in df:
        out["RH"]=df["relative_humidity_2m"].astype(float)
    else:
        Td=df["dew_point_2m"].astype(float)
        T=df["temperature_2m"].astype(float)
        out["RH"]=(100*(math.e**((17.625*Td)/(243.04+Td))/
                        math.e**((17.625*T)/(243.04+T)))).clip(5,100)

    out["td"]=df.get("dew_point_2m",out["T2m"]).astype(float)
    out["cloud"]=(df["cloudcover"]/100).clip(0,1)

    wind_ms=df["windspeed_10m"]/3.6
    out["wind"]=(1.6*pd.Series([math.log1p(max(w,0)) for w in wind_ms])).clip(0,8)

    out["sunup"]=df["is_day"].astype(int)
    out["prp_mmph"]=df["precipitation"].astype(float)
    out["rain"]=df.get("rain",0.0).astype(float)
    out["snowfall"]=df.get("snowfall",0.0).astype(float)
    out["wcode"]=df.get("weathercode",0).astype(int)

    SW_clear=820
    out["SW_down"]=SW_clear*(1-0.75*(out["cloud"]**3))
    return out

def prp_type_row(r):
    if r.prp_mmph<=0: return "none"
    if r.rain>0 and r.snowfall>0: return "mixed"
    if r.snowfall>0: return "snow"
    return "rain"

def snow_temperature_model(df):
    X=df.copy()
    X["ptyp"]=X.apply(prp_type_row,axis=1)

    Tw = (
        X["T2m"] * X["RH"].apply(lambda h: math.atan(0.151977*((h+8.313659)**0.5))) +
        X["RH"].apply(lambda h: math.atan(h))
        - math.atan(X["RH"]-1.676331)
        + 0.00391838*(X["RH"]**1.5)*X["RH"].apply(lambda h: math.atan(0.023101*h))
        - 4.686035
    )
    X["T_wetbulb"]=Tw

    albedo=(0.85-(X["T2m"]/40)).clip(0.55,0.85)
    rad = X["SW_down"]*(1-albedo)
    rad_eff=(rad/250).clip(0,4)

    wet=((X["ptyp"]!="none")|(X["T_wetbulb"]>-0.3)|(X["T2m"]>-0.3))
    T_surf=pd.Series(index=X.index,dtype=float)
    T_surf.loc[wet]=0.0

    dry=~wet
    clr=(1-X["cloud"]).clip(0,1)
    cool=(2+3.6*clr-0.33*X["wind"]).clip(0.5,5)
    T_surf.loc[dry]=X["T2m"][dry]-cool[dry]+(rad_eff[dry]*0.18)

    tau=pd.Series(6.0,index=X.index)
    tau.loc[wet| (X["wind"]>6)]=3
    alpha=1-math.e**(-1/tau)

    T_top5=pd.Series(index=X.index,dtype=float)
    if len(X)>0:
        T_top5.iloc[0]=min(X["T2m"].iloc[0],0)
        for i in range(1,len(X)):
            T_top5.iloc[i]=T_top5.iloc[i-1]+alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    X["T_surf"]=T_surf.round(2)
    X["T_top5"]=T_top5.round(2)

    base=100-(abs(X["T_surf"]+5.5)*6.8).clip(0,100)
    hum_pen=(X["RH"]>90).astype(int)*12
    near0=(X["T_surf"].between(-1.2,0.5)).astype(int)*20
    X["speed_index"]=(base-hum_pen-near0).clip(0,100).round(0)

    return X

# =============== Classificatore neve ===============
def classify_snow(r):
    if r.ptyp=="rain": return "Neve bagnata/pioggia"
    if r.ptyp=="mixed": return "Mista"
    if r.ptyp=="snow" and r.T_surf>-2: return "Neve nuova umida"
    if r.ptyp=="snow" and r.T_surf<=-2: return "Neve nuova fredda"
    if r.T_surf<=-8: return "Rigelata"
    if r.sunup==1 and r.T_surf>-2: return "Primaverile"
    return "Compatta"

def reliability(h): 
    if h<=24: return 85
    if h<=48: return 75
    if h<=72: return 65
    if h<=120: return 50
    return 40

# =============== Scioline ===============
SWIX=[("PS5",-18,-10),("PS6",-12,-6),("PS7",-8,-2),("PS8",-4,4),("PS10",0,10)]
TOKO=[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
BRANDS=[("Swix",SWIX),("Toko",TOKO)]

def pick(bands,t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0]

def struct(T):
    if T<=-10: return "Linear fine"
    if T<=-3: return "Cross Hatch"
    if T<=0.5: return "Diagonal"
    return "Wave marcata"

# =============== Calcolo ===============
if st.button("Calcola", type="primary", use_container_width=True):
    js=fetch_open_meteo(lat,lon)
    raw=build_df(js,hours)
    res=snow_temperature_model(raw)

    show=pd.DataFrame({
        "Ora":res["time"].dt.strftime("%Y-%m-%d %H:%M"),
        "T aria":res["T2m"].round(1),
        "UR%":res["RH"].round(0),
        "T neve surf":res["T_surf"],
        "T top5":res["T_top5"],
        "Vento m/s":res["wind"].round(1),
        "Nuvolosità %":(res["cloud"]*100).round(0),
        "Prp":res["ptyp"],
        "Indice scorrevolezza":res["speed_index"]
    })
    st.dataframe(show,use_container_width=True,hide_index=True)

    blocks={"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
    for L,(s,e) in blocks.items():
        st.markdown("---")
        st.subheader(f"Blocco {L}")
        mask=(res["time"].dt.date==target_day)
        day=res[mask]
        win=day[(day["time"].dt.time>=s)&(day["time"].dt.time<=e)]
        if win.empty: win=day.head(6)
        t=float(win["T_surf"].mean())
        cond=classify_snow(win.iloc[0])
        rel=reliability(hours)
        st.markdown(f"<div class='banner'><b>{cond}</b> · T neve {t:.1f}°C · Affidabilità {rel}%</div>",unsafe_allow_html=True)
        st.write(f"**Struttura consigliata:** {struct(t)}")

        col1,col2=st.columns(2)
        with col1:
            st.write("**Scioline:**")
            for name,bands in BRANDS:
                st.write(f"{name}: {pick(bands,t)}")

        with col2:
            mini=pd.DataFrame({
                "Ora":win["time"].dt.strftime("%H:%M"),
                "T aria":win["T2m"].round(1),
                "T neve":win["T_surf"].round(1),
                "UR%":win["RH"].round(0),
                "Vento":win["wind"].round(1),
                "Prp":win["ptyp"]
            })
            st.dataframe(mini,use_container_width=True,hide_index=True)
