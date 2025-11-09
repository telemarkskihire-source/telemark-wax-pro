# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- TEMA SCURO (Opzione B) --------------------
BG = "#111111"
CARD = "#1a1a1a"
TEXT = "#f5f5f5"
ACCENT = "#0099cc"
MUTED = "#aaaaaa"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{
  background: {BG};
}}
* {{ color: {TEXT} }}
h1,h2,h3,h4,h5,h6 {{ color: {TEXT}; font-weight:600 }}
hr {{ border-top: 1px solid #333 }}
.card {{
  background:{CARD};
  border:1px solid #333;
  border-radius:14px;
  padding:1rem 1.2rem;
  box-shadow:0 0 25px rgba(0,0,0,.25);
}}
.badge {{
  display:inline-block;
  padding:.3rem .7rem;
  border-radius:10px;
  background:{ACCENT}33;
  border:1px solid {ACCENT}77;
  font-size:.78rem;
}}
.brand {{
  display:flex;align-items:center;gap:.75rem;
  background:#00000055;
  border:1px solid #444;
  border-radius:8px;
  padding:.45rem .75rem;
}}
.brand img {{ height:20px }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Altitudine · Blocchi A/B/C · Marchi · Strutture · Angoli · Stile tuning</span>", unsafe_allow_html=True)


# -------------------- FUNZIONI BASE --------------------
def flag(cc):
    try:
        return chr(127397+ord(cc.upper()[0]))+chr(127397+ord(cc.upper()[1]))
    except:
        return "🏳️"

def concise(addr, full):
    n = addr.get("village") or addr.get("town") or addr.get("city") or full
    admin = addr.get("state") or addr.get("region") or ""
    cc = (addr.get("country_code") or "").upper()
    t = ", ".join([p for p in [n,admin] if p])
    if cc: t += f" — {cc}"
    return t

def search(q):
    if not q or len(q)<2: return []
    r = requests.get("https://nominatim.openstreetmap.org/search",
        params={"q":q,"format":"json","limit":10,"addressdetails":1},
        headers={"User-Agent":"telemark-pro/1.0"},timeout=8)
    st.session_state._opts={}
    out=[]
    for it in r.json():
        addr=it.get("address",{}) or {}
        label=f"{flag(addr.get('country_code',''))}  {concise(addr,it.get('display_name',''))}"
        lat=float(it["lat"]); lon=float(it["lon"])
        key=f"{label}|||{lat:.6f},{lon:.6f}"
        st.session_state._opts[key]={"lat":lat,"lon":lon,"label":label}
        out.append(key)
    return out

def elevation(lat,lon):
    try:
        r=requests.get("https://api.open-meteo.com/v1/elevation",
            params={"latitude":lat,"longitude":lon},timeout=8).json()
        return int(r["elevation"][0])
    except:
        return None

def fetch(lat,lon):
    r=requests.get("https://api.open-meteo.com/v1/forecast",
        params={"latitude":lat,"longitude":lon,"timezone":"Europe/Rome",
        "hourly":"temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days":7},timeout=20)
    return r.json()

def prp(df):
    snow={71,73,75,77,85,86}
    rain={51,53,55,61,63,65,80,81,82}
    def f(r):
        if r.precipitation<=0: return "none"
        if r.snowfall>0 and r.rain>0: return "mixed"
        if r.snowfall>0: return "snow"
        if r.rain>0: return "rain"
        if r.weathercode in snow: return "snow"
        if r.weathercode in rain: return "rain"
        return "mixed"
    return df.apply(f,axis=1)

def build(js,h):
    df=pd.DataFrame(js["hourly"])
    df["time"]=pd.to_datetime(df["time"])
    df=df[df["time"]>=pd.Timestamp.now().floor("H")].head(h).reset_index(drop=True)
    out=pd.DataFrame()
    out["time"]=df["time"]; out["T2m"]=df["temperature_2m"].astype(float)
    out["td"]=df["dew_point_2m"].astype(float)
    out["cloud"]=(df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]=(df["windspeed_10m"].astype(float)/3.6).round(3)
    out["sunup"]=df["is_day"].astype(int)
    out["prp_mmph"]=df["precipitation"].astype(float)
    extra=df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"]=prp(extra)
    return out

def snowT(df,dt=1):
    df=df.copy()
    df["time"]=pd.to_datetime(df["time"])
    rain=df["prp_type"].isin(["rain","mixed"])
    snow=df["prp_type"].eq("snow")
    sun=df["sunup"].eq(1)
    tw=(df["T2m"]+df["td"])/2
    wet=(rain | (df["T2m"]>0) | (sun&(df["cloud"]<0.3)&(df["T2m"]>=-3))
         | (snow&(df["T2m"]>=-1)) | (snow&tw.ge(-0.5)))
    T_surf=pd.Series(index=df.index,dtype=float); T_surf[wet]=0
    dry=~wet
    rad=(1.5+3*(1-df["cloud"])-0.3*df["wind"].clip(upper=6)).clip(0.5,4.5)
    T_surf[dry]=df["T2m"][dry]-rad[dry]
    T_top=pd.Series(index=df.index,dtype=float)
    tau=pd.Series(6,index=df.index); tau[rain|snow|df["wind"].ge(6)]=3
    a=1-(math.e**(-dt/tau))
    if len(df)>0:
        T_top.iloc[0]=min(df["T2m"].iloc[0],0)
        for i in range(1,len(df)):
            T_top.iloc[i]=T_top.iloc[i-1]+a.iloc[i]*(T_surf.iloc[i]-T_top.iloc[i-1])
    df["T_surf"]=T_surf; df["T_top5"]=T_top
    return df

def slice(res,s,e):
    t=pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz("Europe/Rome"))
    D=res.copy(); D["dt"]=t
    today=pd.Timestamp.now(tz=tz.gettz("Europe/Rome")).date()
    W=D[(D["dt"].dt.date==today)&(D["dt"].dt.time>=s)&(D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(6)

# -------------------- SCIOLINE + STRUTTURE --------------------
BRANDS=[
("Swix","assets/brands/swix.png",[("PS5",-18,-10),("PS6",-12,-6),("PS7",-8,-2),("PS8",-4,4),("PS10",0,10)]),
("Toko","assets/brands/toko.png",[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]),
("Vola","assets/brands/vola.png",[("MX Blue",-25,-10),("MX Violet",-12,-4),("MX Red",-5,0),("MX Yellow",-2,6)]),
("Rode","assets/brands/rode.png",[("R20",-18,-8),("R30",-10,-3),("R40",-5,0),("R50",-1,10)]),
("Holmenkol","assets/brands/holmenkol.png",[("Ultra",-20,-8),("Beta",-14,-4),("Alpha",-4,5)]),
("Maplus","assets/brands/maplus.png",[("Cold",-12,-6),("Med",-7,-2),("Soft",-5,0)]),
("Start","assets/brands/start.png",[("Blue",-12,-6),("Purple",-8,-2),("Red",-3,7)]),
("Skigo","assets/brands/skigo.png",[("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)])
]

STRUCTURE_NAMES = {
"cold": "Lineare fine (freddo/secco)",
"mid": "Onda universale (all-round)",
"wet": "Scarico diagonale/V (umido)",
"thumb": "Thumb-print (grana media)"
}

def choose_structure(T):
    if T<=-10: return "cold"
    if T<=-3: return "mid"
    if T<=1:  return "thumb"
    return "wet"

def angles(T,disc):
    if T<=-10: base=0.5; sides={"SL":88.5,"GS":88,"SG":87.5,"DH":87.5}
    elif T<=-3: base=0.7; sides={"SL":88,"GS":88,"SG":87.5,"DH":87}
    else: base=1.0; sides={"SL":88,"GS":87.5,"SG":87,"DH":87}
    return sides.get(disc,88),base


# -------------------- UI FLUSSO --------------------
st.subheader("1) Cerca località")

sel=st_searchbox(search,key="loc",placeholder="Scrivi es. Champoluc, Plateau Rosa, Sestriere...")
lat=st.session_state.get("lat",45.83); lon=st.session_state.get("lon",7.73)
label=st.session_state.get("label","Champoluc — IT")

if sel and "_opts" in st.session_state:
    x=st.session_state._opts[sel]
    lat,lon,label=x["lat"],x["lon"],x["label"]
    st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["label"]=label

e=elevation(lat,lon)
st.markdown(f"**Località:** {label} · Altitudine **{e if e else '?'} m**")

st.subheader("2) Finestre A · B · C")
c1,c2,c3=st.columns(3)
with c1:
    A_s=st.time_input("Inizio A",time(9,0))
    A_e=st.time_input("Fine A",time(11,0))
with c2:
    B_s=st.time_input("Inizio B",time(11,0))
    B_e=st.time_input("Fine B",time(13,0))
with c3:
    C_s=st.time_input("Inizio C",time(13,0))
    C_e=st.time_input("Fine C",time(16,0))

hours=st.slider("Ore previsione",12,168,72,12)

st.subheader("3) Calcola tuning")
if st.button("Calcola"):
    js=fetch(lat,lon)
    d=build(js,hours)
    r=snowT(d)

    st.success("Dati caricati.")
    st.dataframe(r,use_container_width=True)

    blocks={"A":(A_s,A_e),"B":(B_s,B_e),"C":(C_s,C_e)}

    for L,(s,e) in blocks.items():
        W=slice(r,s,e)
        T=float(W["T_surf"].mean())
        st.markdown(f"---\n### Blocco {L} — T_surf **{T:.1f}°C**")

        cols=st.columns(4)
        for i,(name,path,bands) in enumerate(BRANDS[:4]):
            rec=[x[0] for x in bands if x[1]<=T<=x[2]]
            rec=rec[0] if rec else bands[-1][0]
            try:
                b64=base64.b64encode(open(path,"rb").read()).decode()
                img=f"<img src='data:image/png;base64,{b64}'/>"
            except:
                img=f"<div style='font-weight:700'>{name}</div>"
            cols[i].markdown(f"<div class='brand'>{img}<div>{rec}</div></div>",unsafe_allow_html=True)

        cols=st.columns(4)
        for i,(name,path,bands) in enumerate(BRANDS[4:]):
            rec=[x[0] for x in bands if x[1]<=T<=x[2]]
            rec=rec[0] if rec else bands[-1][0]
            try:
                b64=base64.b64encode(open(path,"rb").read()).decode()
                img=f"<img src='data:image/png;base64,{b64}'/>"
            except:
                img=f"<div style='font-weight:700'>{name}</div>"
            cols[i].markdown(f"<div class='brand'>{img}<div>{rec}</div></div>",unsafe_allow_html=True)

        st.markdown("**Stile preferito:**")
        style = st.selectbox(f"Stile tuning · Blocco {L}",["Velocità ⚡","Stabilità 🎯","Universale 🌍"],key=L)

        if style=="Velocità ⚡":
            struct=choose_structure(T)
        elif style=="Stabilità 🎯":
            struct="cold"
        else:
            struct="mid"

        st.markdown(f"**Struttura consigliata:** {STRUCTURE_NAMES[struct]}")

        rows=[]
        for d in ["SL","GS","SG","DH"]:
            side,base=angles(T,d)
            rows.append([d,STRUCTURE_NAMES[struct],f"{side:.1f}°",f"{base:.1f}°"])
        st.table(pd.DataFrame(rows,columns=["Disciplina","Struttura","Lamina SIDE","Lamina BASE"]))
