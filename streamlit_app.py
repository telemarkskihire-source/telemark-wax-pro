# Telemark · Pro Wax & Tune (dark) — v2025-11-09
import streamlit as st
import pandas as pd
import requests, math, base64
from datetime import datetime, date, time, timedelta, timezone
from dateutil import tz
import matplotlib.pyplot as plt

# ------------------------ PAGE THEME (DARK) ------------------------
PRIMARY = "#10bfcf"; BG = "#0b1020"; CARD = "#0f172a"; BORDER = "rgba(255,255,255,.08)"
TEXT = "#eaf2ff"; MUTED = "#9db2d9"; GOOD="#22c55e"; WARN="#eab308"; BAD="#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:{BG}; --card:{CARD}; --text:{TEXT}; --muted:{MUTED}; --primary:{PRIMARY}; }}
[data-testid="stAppViewContainer"] > .main {{ background: radial-gradient(1200px 700px at 20% -10%, #111b36 0%, {BG} 45%); }}
.block-container {{ padding-top: 0.6rem; }}
h1,h2,h3,h4, p, span, label, div {{ color: var(--text); }}
hr {{ border:none; border-top:1px solid {BORDER}; margin: 8px 0 14px; }}
.card {{ background: var(--card); border: 1px solid {BORDER}; border-radius: 16px; padding: 12px 14px; }}
.kpi {{ display:flex; gap:8px; align-items:center; background: rgba(16,191,207,.06);
       border:1px dashed rgba(16,191,207,.45); padding:10px 12px; border-radius:12px; }}
.badge {{ display:inline-block; padding:4px 8px; border-radius:999px; font-size:.78rem; color:#021d26;
         background: linear-gradient(90deg, {PRIMARY}99, #4ade80aa); border:1px solid rgba(255,255,255,.2); }}
.small {{ color: var(--muted); font-size:.85rem; }}
.table thead th {{ background: #0a1328 !important; color: #dbeafe !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")

# ------------------------ HELPERS ------------------------
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village") \
           or addr.get("town") or addr.get("city") or fallback.split(",")[0]
    admin = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    short = ", ".join([p for p in [name, admin] if p])
    return f"{short} — {cc}" if cc else short

def search_places(q:str):
    if not q or len(q)<2: return []
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q":q,"format":"json","limit":8,"addressdetails":1},
                         headers={"User-Agent":"telemark-wax-app/1.0"}, timeout=8)
        r.raise_for_status()
        out=[]
        for it in r.json():
            addr=it.get("address",{}) or {}
            short = concise_label(addr, it.get("display_name",""))
            lab = f"{flag(addr.get('country_code',''))}  {short}"
            out.append({"label":lab, "lat":float(it["lat"]), "lon":float(it["lon"]), "addr":addr})
        return out
    except: return []

def get_elevation(lat:float, lon:float):
    try:
        rr = requests.get("https://api.open-meteo.com/v1/elevation",
                          params={"latitude":lat,"longitude":lon}, timeout=8)
        rr.raise_for_status()
        js=rr.json()
        if js and "elevation" in js and js["elevation"]: return float(js["elevation"][0])
    except: pass
    return None

def fetch_open_meteo(lat, lon, tzname):
    url="https://api.open-meteo.com/v1/forecast"
    params=dict(latitude=lat, longitude=lon, timezone=tzname,
        hourly="temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        forecast_days=7)
    r=requests.get(url, params=params, timeout=30); r.raise_for_status(); return r.json()

def rh_from_T_Td(T, Td):
    """Magnus formula → RH%."""
    try:
        a=17.625; b=243.04
        gamma=lambda x: (a*x)/(b+x)
        return (100*math.exp((gamma(Td)-gamma(T))*math.log(10)))  # stable
    except: return float("nan")

def build_df(js, start_dt_local:datetime, hours:int):
    h=js["hourly"]; df=pd.DataFrame(h)
    df["time"]=pd.to_datetime(df["time"])
    # Select from chosen local datetime forward
    df = df[df["time"] >= start_dt_local.floor("H")].head(hours).reset_index(drop=True)
    out=pd.DataFrame()
    out["time"]=df["time"]
    out["T2m"]=pd.to_numeric(df["temperature_2m"], errors="coerce")
    out["td"]=pd.to_numeric(df.get("dew_point_2m", float("nan")), errors="coerce")
    rh_col = df.get("relative_humidity_2m", None)
    if rh_col is not None:
        out["rh"]=pd.to_numeric(rh_col, errors="coerce")
    else:
        out["rh"]= [rh_from_T_Td(t, d) for t,d in zip(out["T2m"], out["td"])]
    out["cloud"]=pd.to_numeric(df["cloudcover"], errors="coerce")/100.0
    out["wind"]=pd.to_numeric(df["windspeed_10m"], errors="coerce")/3.6
    out["sunup"]=pd.to_numeric(df["is_day"], errors="coerce").fillna(0).astype(int)
    out["prp_mmph"]=pd.to_numeric(df["precipitation"], errors="coerce")
    out["rain"]=pd.to_numeric(df.get("rain",0.0), errors="coerce")
    out["snow"]=pd.to_numeric(df.get("snowfall",0.0), errors="coerce")
    out["wcode"]=pd.to_numeric(df.get("weathercode",0), errors="coerce").astype(int)
    # precip type
    pt=[]
    for r,s,p in zip(out["rain"], out["snow"], out["prp_mmph"]):
        if p<=0.0: pt.append("none")
        elif r>0 and s>0: pt.append("mixed")
        elif s>0: pt.append("snow")
        else: pt.append("rain")
    out["prp_type"]=pt
    return out

# ------------------------ SNOW THERMAL MODEL ------------------------
def compute_snow_temps(df:pd.DataFrame, dt_hours=1.0)->pd.DataFrame:
    """Heuristic energy-balance-like model. Outputs T_surf and T_top5."""
    res=df.copy()
    # wet logic using RH and Td proximity
    Tw = (res["T2m"] + res["td"]) / 2.0
    wet = (
        (res["rh"]>=88) & (res["T2m"]>-3) |
        (res["prp_type"].isin(["rain","mixed"])) |
        (res["snow"].gt(0) & (res["T2m"]>-1)) |
        (Tw>-0.5)
    )
    T_surf = pd.Series(index=res.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear=(1.0 - res["cloud"]).clip(0,1); windc=res["wind"].clip(upper=6.0)
    # Radiative/convective cooling strength
    drad = (1.3 + 3.1*clear - 0.28*windc).clip(0.3, 4.8)
    T_surf.loc[dry] = (res["T2m"] - drad)[dry]
    # Sunny cold compensation (shortwave warming)
    sunny_cold = (res["sunup"]==1) & dry & res["T2m"].between(-15,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.DataFrame({
        "sw": res["T2m"] + 0.5*(1.0 - res["cloud"]),
        "cap": pd.Series([-0.5]*len(res), index=res.index)
    }).min(axis=1)[sunny_cold]

    # Top 5 mm lag (exponential approach)
    T_top5 = pd.Series(index=res.index, dtype=float)
    tau = pd.Series(6.0, index=res.index)
    tau.loc[wet | res["snow"].gt(0) | (res["wind"]>=6)] = 3.0
    tau.loc[(res["sunup"]==0) & (res["wind"]<2) & (res["cloud"]<0.3)] = 8.0
    # compute alpha as numeric
    alpha = 1.0 - pd.np.exp(-dt_hours / tau.astype(float))
    if not res.empty:
        T_top5.iloc[0] = min(res["T2m"].iloc[0], 0.0)
        for i in range(1, len(res)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i] - T_top5.iloc[i-1])

    res["T_surf"]=T_surf
    res["T_top5"]=T_top5
    return res

# ------------------------ SNOW CONDITION & METRICS ------------------------
def snow_condition(row)->str:
    # simple rules with precedence
    if row["prp_type"] in ("rain","mixed"): return "neve bagnata / pioggia"
    if row["snow"]>0.0 and row["T_surf"]>-3: return "neve nuova bagnata"
    if row["snow"]>0.0 and row["T_surf"]<=-3: return "neve nuova asciutta"
    if row["T_surf"]>=-0.1: return "zuppa / primaverile"
    if row["T_surf"]<-0.1 and row["T_surf"]>-4 and row["rh"]>75: return "trasformata umida"
    if row["T_surf"]<=-8 and row["wind"]>6: return "vento / vetrata"
    if row["T_surf"]<=-8: return "molto fredda / abrasiva"
    return "fredda / compatta"

def glide_index(row)->int:
    # 0-100; best around -6..-1 for asciutta, near 0 for bagnata
    t=row["T_surf"]
    if t>=-0.2:
        score=85 - 25*min((t-0)**2,4)   # troppo caldo → meno scorrevole
    else:
        # optimum -6..-2
        opt=-4
        score=90 - 4*min((t-opt)**2, 100)
    # penalità vento forte e pioggia
    if row["prp_type"]=="rain": score-=20
    score -= 5*min(row["wind"]/5, 3)
    return int(max(0,min(100,score)))

def reliability(ts:pd.Timestamp, now_local:datetime, cloud:float)->int:
    h=(ts.to_pydatetime()-now_local).total_seconds()/3600.0
    base=0.35 + 0.5*math.exp(-max(0,h)/72.0)
    base *= (1.0 - 0.25*abs(cloud-0.5))  # alta in cieli molto coperti o molto sereni, meno a metà
    return int(max(20,min(95, round(base*100))))

# ------------------------ WAX BANDS (nomi, niente immagini) ------------------------
SWIX=[("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO=[("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA=[("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE=[("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
BRANDS=[("Swix",SWIX),("Toko",TOKO),("Vola",VOLA),("Rode",RODE)]

def pick(bands,t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ------------------------ UI — 1) Ricerca con ENTER + data ------------------------
with st.form("place_form", clear_on_submit=False):
    st.markdown("#### 1) Cerca località")
    q=st.text_input("Digita e premi Invio (es. Champoluc, Plateau Rosa, Sestriere)", value=st.session_state.get("q",""))
    start_day = st.date_input("Giorno previsione", value=st.session_state.get("day", date.today()))
    submitted = st.form_submit_button("Cerca")
if submitted:
    st.session_state["q"]=q; st.session_state["day"]=start_day
    st.session_state["choices"]=search_places(q)

choices=st.session_state.get("choices", [])
if choices:
    labels=[c["label"] for c in choices]
    idx = st.selectbox("Scegli risultato", list(range(len(labels))), format_func=lambda i: labels[i], index=0)
    sel=choices[idx]; lat,lon,label = sel["lat"], sel["lon"], sel["label"]
    st.session_state.update({"lat":lat,"lon":lon,"label":label})
else:
    lat=st.session_state.get("lat",45.831); lon=st.session_state.get("lon",7.730)
    label=st.session_state.get("label","🇮🇹 Champoluc — IT")

elev = get_elevation(lat,lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {label}{alt_txt}")

# ------------------------ 2) Finestre A/B/C ------------------------
st.markdown("#### 2) Finestre orarie A · B · C")
c1,c2,c3=st.columns(3)
with c1:
    A_start=st.time_input("Inizio A", time(9,0)); A_end=st.time_input("Fine A", time(11,0))
with c2:
    B_start=st.time_input("Inizio B", time(11,0)); B_end=st.time_input("Fine B", time(13,0))
with c3:
    C_start=st.time_input("Inizio C", time(13,0)); C_end=st.time_input("Fine C", time(16,0))
hours = st.slider("Ore previsione (orizzonte)", 12, 168, 72, 12)

# ------------------------ 3) Meteo + calcolo ------------------------
st.markdown("#### 3) Dati meteo & calcolo")
if st.button("Scarica/aggiorna previsioni", type="primary"):
    try:
        tzname="Europe/Rome"
        js=fetch_open_meteo(lat,lon,tzname)
        start_dt = datetime.combine(st.session_state.get("day", date.today()), time(0,0))
        start_dt = start_dt.replace(tzinfo=tz.gettz(tzname))
        src=build_df(js, start_dt, hours)
        res=compute_snow_temps(src, dt_hours=1.0)

        # derived metrics
        now_local=datetime.now(tz=tz.gettz(tzname))
        res["cond"]=res.apply(snow_condition, axis=1)
        res["glide"]=res.apply(glide_index, axis=1)
        res["reliab"]=[reliability(t, now_local, c) for t,c in zip(res["time"], res["cloud"])]

        st.success(f"Dati per **{label}** caricati.")
        # TABLE tidy
        show=res.copy()
        show["Ora"]=show["time"].dt.strftime("%d %b %H:%M")
        tidy=show[["Ora","T2m","rh","wind","cloud","prp_mmph","prp_type","T_surf","T_top5","cond","glide","reliab"]]
        tidy.columns=["Ora","T aria °C","UR %","Vento m/s","Nuvolosità","Prec mm/h","Tipo","T superficie °C","T top 5mm °C","Condizione neve","Indice di scorrevolezza","Affidabilità %"]
        st.dataframe(tidy, use_container_width=True, hide_index=True)

        # CHART
        t=show["time"]
        fig1=plt.figure(); plt.plot(t,show["T2m"],label="T aria"); plt.plot(t,show["T_surf"],label="T superficie"); plt.plot(t,show["T_top5"],label="T top 5mm")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2=plt.figure(); plt.bar(t,show["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # DOWNLOAD
        st.download_button("Scarica CSV", data=tidy.to_csv(index=False), file_name="telemark_forecast.csv", mime="text/csv")

        # WINDOWS A/B/C
        blocks={"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            # slice by chosen day + times
            def slice_window(df):
                dt_local = df["time"].dt.tz_convert(tz.gettz("Europe/Rome"))
                sel = (dt_local.dt.date==st.session_state.get("day", date.today())) & (dt_local.dt.time>=s) & (dt_local.dt.time<=e)
                dd = df[sel]
                return dd if not dd.empty else df.head(6)
            W=slice_window(show)
            t_med=float(W["T_surf"].mean()); cond=W["cond"].mode().iloc[0] if not W.empty else "—"
            gi=int(W["glide"].mean()) if not W.empty else 0
            rel=int(W["reliab"].mean()) if not W.empty else 0

            # banner riassunto
            st.markdown(
                f"<div class='card'><span class='badge'>Sintesi</span> "
                f"<div class='small'>T_surf medio: <b>{t_med:.1f}°C</b> · Condizione: <b>{cond}</b> · "
                f"Indice di scorrevolezza: <b>{gi}</b>/100 · Affidabilità: <b>{rel}%</b></div></div>",
                unsafe_allow_html=True
            )

            # Raccomandazioni sciolina (niente immagini)
            cols=st.columns(len(BRANDS))
            for i,(brand,bands) in enumerate(BRANDS):
                rec=pick(bands, t_med)
                cols[i].markdown(f"<div class='kpi'><div class='small'>{brand}</div>"
                                 f"<div style='font-weight:800'>{rec}</div></div>", unsafe_allow_html=True)

            # Struttura: solo nomi (niente immagini)
            def structure_name(ts):
                if ts<=-10: return "Linear Fine"
                if ts<=-3:  return "Cross Hatch (fine)"
                return "Diagonal / V (umido)"
            st.markdown(f"**Struttura consigliata (GS ref):** {structure_name(t_med)}")

    except Exception as e:
        st.error(f"Errore: {e}")
