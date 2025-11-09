# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# -------------------- UI (chiaro, che “stacca” sul bianco) --------------------
PRIMARY = "#0ea5b7"      # turchese Telemark
ACCENT  = "#111827"      # titoli scuri
MUTED   = "#6b7280"      # testo secondario

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
h1,h2,h3,h4 {{ color:{ACCENT}; }}
small, .muted {{ color:{MUTED}; }}
.brand {{ display:flex;align-items:center;gap:.75rem;background:#f8fafc;
          border:1px solid #e5e7eb;border-radius:12px;padding:.5rem .75rem; }}
.brand img {{ height:22px; }}
.badge {{ display:inline-block;background:{PRIMARY}1A;color:{ACCENT};border:1px solid {PRIMARY}66;
         padding:.25rem .5rem;border-radius:999px;font-size:.78rem }}
hr {{ border:none;border-top:1px solid #e5e7eb;margin:.75rem 0 }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Altitudine · Blocchi A/B/C · Marchi · Strutture · Angoli</span>", unsafe_allow_html=True)

# -------------------- Helpers --------------------
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label_from_address(addr:dict, fallback_name:str)->str:
    # prendo un nome corto + admin1 + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") or
            addr.get("town") or addr.get("city") or fallback_name)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts)
    if cc:
        short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    if not q or len(q)<2: 
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format":"json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent":"telemark-wax-pro/1.0"},
            timeout=8
        )
        r.raise_for_status()
        st.session_state._options = {}
        out = []
        for item in r.json():
            addr = item.get("address",{}) or {}
            label_short = concise_label_from_address(addr, item.get("display_name",""))
            cc = addr.get("country_code","")
            label = f"{flag(cc)}  {label_short}"
            lat = float(item.get("lat",0)); lon = float(item.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float)->float|None:
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and "elevation" in data and data["elevation"]:
            return float(data["elevation"][0])
    except:
        pass
    return None

def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly":"temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
            "forecast_days":7,
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and rain==0: return "snow"
        if rain>0 and snow==0: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"]>=now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["td"]  = df["dew_point_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).round(3)
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain","mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1
    tw = (df["T2m"] + df["td"]) / 2.0
    wet = (rain | (df["T2m"]>0) | (sunup & (df["cloud"]<0.3) & (df["T2m"]>=-3))
           | (snow & (df["T2m"]>=-1)) | (snow & tw.ge(-0.5).fillna(False)))
    T_surf = pd.Series(index=df.index, dtype=float); T_surf.loc[wet] = 0.0
    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0,1); windc = df["wind"].clip(upper=6.0)
    drad = (1.5 + 3.0*clear - 0.3*windc).clip(0.5, 4.5)
    T_surf.loc[dry] = df["T2m"][dry] - drad[dry]
    sunny_cold = sunup & dry & df["T2m"].between(-10,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (df["T2m"] + 0.5*(1.0 - df["cloud"]))[sunny_cold],
        pd.Series(-0.5, index=df.index)[sunny_cold]
    ], axis=1).min(axis=1)
    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[rain | snow | (df["wind"]>=6)] = 3.0
    tau.loc[(~sunup) & (df["wind"]<2) & (df["cloud"]<0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df)>0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)
        for i in range(1,len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])
    df["T_surf"] = T_surf; df["T_top5"] = T_top5
    return df

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# -------------------- WAX bands & brands --------------------
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [
    ("Swix","assets/brands/swix.png", SWIX),
    ("Toko","assets/brands/toko.png", TOKO),
    ("Vola","assets/brands/vola.png", VOLA),
    ("Rode","assets/brands/rode.png", RODE),
    ("Holmenkol","assets/brands/holmenkol.png", HOLM),
    ("Maplus","assets/brands/maplus.png", MAPL),
    ("Start","assets/brands/start.png", START),
    ("Skigo","assets/brands/skigo.png", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_badge(text:str, path:str)->str:
    if os.path.exists(path):
        b64 = base64.b64encode(open(path,"rb").read()).decode("utf-8")
        return f"<img src='data:image/png;base64,{b64}'/>"
    # fallback testuale
    return f"<div style='font-weight:700'>{text}</div>"

# -------------------- Strutture (foto reali se presenti) --------------------
STRUCT_IMG = {
    "linear":   "assets/structures/linear.png",
    "cross":    "assets/structures/cross.png",
    "diagonal": "assets/structures/diagonal.png",
    "wave":     "assets/structures/wave.png",
}
def show_structure(kind:str, title:str):
    path = STRUCT_IMG.get(kind,"")
    if path and os.path.exists(path):
        b64 = base64.b64encode(open(path,"rb").read()).decode("utf-8")
        st.markdown(f"<div style='text-align:center'><img src='data:image/png;base64,{b64}' style='max-width:360px;border:1px solid #e5e7eb;border-radius:12px' /><div class='muted' style='margin-top:.4rem'>{title}</div></div>", unsafe_allow_html=True)
    else:
        # fallback disegni stilizzati, se manca la foto
        fig = plt.figure(figsize=(3.6, 2.0), dpi=180); ax = plt.gca()
        ax.set_facecolor("#d6d6d6"); ax.set_xlim(0,100); ax.set_ylim(0,60); ax.axis("off")
        color="#2b2b2b"
        if kind=="linear":
            for x in range(8,98,5): ax.plot([x,x],[6,54],color=color,linewidth=2.6)
        elif kind=="cross":
            for x in range(-10,120,10): ax.plot([x,x+50],[6,54],color=color,linewidth=2.2,alpha=.95)
            for x in range(10,110,10):  ax.plot([x,x-50],[6,54],color=color,linewidth=2.2,alpha=.95)
        elif kind=="diagonal":
            for x in range(-20,120,8): ax.plot([x,x+50],[6,54],color=color,linewidth=3.0)
        else: # wave
            import numpy as np
            xs = np.linspace(5,95,9)
            for x in xs:
                yy = 30 + 20*np.sin(np.linspace(-math.pi, math.pi, 60))
                ax.plot(np.full_like(yy,x), yy, color=color, linewidth=2.4)
        st.pyplot(fig)
        st.caption(title)

def tune_for(t_surf, discipline):
    # fam (chiave struttura, descrizione), angoli SIDE/BASE
    if t_surf <= -10:
        fam = ("linear","Lineare fine (freddo/secco)")
        base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}.get(discipline,88.0)
    elif t_surf <= -3:
        fam = ("cross","Universale incrociata / leggera onda")
        base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}.get(discipline,88.0)
    else:
        fam = ("diagonal","Scarico diagonale/V (umido/caldo)")
        base = 0.8 if t_surf<=0.5 else 1.0
        side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}.get(discipline,88.0)
    return fam, side, base

# ==================== 1) RICERCA LOCALITÀ ====================
st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Scrivi… es. Champoluc, Plateau Rosa, Cervinia",
    clear_on_submit=False,
    default=None
)

lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

# Altitudine (mostrata subito, così capisci se è “quella giusta”)
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {place_label}{alt_txt}")

# ==================== 2) Finestre A/B/C ====================
st.subheader("2) Finestre orarie A · B · C (oggi)")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0),  key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

# Orizzonte previsioni (riaggiungo così non compare più “hours not defined”)
hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ==================== 3) Meteo + raccomandazioni ====================
st.subheader("3) Scarica dati meteo & calcola")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    try:
        js = fetch_open_meteo(lat, lon, "Europe/Rome")
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{place_label}** caricati.")
        st.dataframe(res, use_container_width=True)

        # grafici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T_surf"); plt.plot(t,res["T_top5"],label="T_top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = window_slice(res, "Europe/Rome", s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # Marchi (logo reale se presente)
            cols1 = st.columns(4); cols2 = st.columns(4)
            for i,(name,path,bands) in enumerate(BRANDS[:4]):
                rec = pick(bands, t_med)
                cols1[i].markdown(
                    f"<div class='brand'>{logo_badge(name,path)}<div><div class='muted' style='font-size:.8rem'>{name}</div><div style='font-weight:800'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )
            for i,(name,path,bands) in enumerate(BRANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'>{logo_badge(name,path)}<div><div class='muted' style='font-size:.8rem'>{name}</div><div style='font-weight:800'>{rec}</div></div></div>",
                    unsafe_allow_html=True
                )

            # Struttura + angoli per le 4 specialità (niente toggle: tabella diretta)
            fam_gs, side_gs, base_gs = tune_for(t_med, "GS")
            st.markdown("**Struttura consigliata (GS di riferimento):**")
            show_structure(fam_gs[0], fam_gs[1])

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam[1], f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
         
