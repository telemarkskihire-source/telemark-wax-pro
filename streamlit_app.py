# telemark_pro_app.py
# Telemark · Pro Wax & Tune – tema scuro + quick-wins input + fix Series .dt + NOAA soft

import os, math, base64, requests
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, date, time
from dateutil import tz
from streamlit_searchbox import st_searchbox
import matplotlib.pyplot as plt

# ---------------- UI (dark) ----------------
PRIMARY = "#06b6d4"; ACCENT="#f97316"; OK="#10b981"; WARN="#f59e0b"; ERR="#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root{{--bg:#0b0f13;--panel:#121821;--line:#1f2937;--fg:#e5e7eb;--muted:#9aa4af}}
html, body, .stApp{{background:var(--bg);color:var(--fg)}}
[data-testid="stHeader"]{{background:transparent}}
h1,h2,h3,h4{{color:#fff}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1rem}}
.badge{{display:inline-flex;gap:.5rem;background:#0b1220;border:1px solid #203045;color:#cce7f2;
border-radius:12px;padding:.35rem .6rem;font-size:.85rem}}
.banner{{border-left:6px solid {ACCENT};background:#1a2230;color:#e2e8f0;padding:.75rem .9rem;border-radius:10px}}
.btn-primary button{{background:{ACCENT}!important;color:#111!important;font-weight:800!important}}
a{{color:{PRIMARY}!important}}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline – blocchi A/B/C.")

# ---------------- Helpers ----------------
def flag(cc:str)->str:
    try: c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name=(addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
          or addr.get("town") or addr.get("city") or fallback)
    admin1=addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc=(addr.get("country_code") or "").upper()
    s=", ".join([p for p in [name,admin1] if p]);  return f"{s} — {cc}" if cc else s

# ---------------- Ricerca con prefiltro nazione ----------------
COUNTRIES={"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
c_na, c_sb = st.columns([1,3])
with c_na:
    sel_country = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
    iso2 = COUNTRIES[sel_country]
with c_sb:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r=requests.get("https://nominatim.openstreetmap.org/search",
                params={"q":q,"format":"json","limit":12,"addressdetails":1,"countrycodes":iso2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"},timeout=8)
            r.raise_for_status(); st.session_state._options={}; out=[]
            for it in r.json():
                addr=it.get("address",{}) or {}
                lab=f"{flag(addr.get('country_code',''))}  {concise_label(addr, it.get('display_name',''))}"
                lat=float(it.get("lat",0)); lon=float(it.get("lon",0))
                key=f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key]={"lat":lat,"lon":lon,"label":lab,"addr":addr}; out.append(key)
            return out
        except: return []
    selected = st_searchbox(nominatim_search, key="place",
                            placeholder="Cerca… es. Champoluc, Plateau Rosa", clear_on_submit=False)

def get_elev(lat,lon):
    try:
        rr=requests.get("https://api.open-meteo.com/v1/elevation",
                        params={"latitude":lat,"longitude":lon},timeout=8)
        rr.raise_for_status(); js=rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat=st.session_state.get("lat",45.831); lon=st.session_state.get("lon",7.730)
place_label=st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info=st.session_state._options.get(selected)
    if info:
        lat,lon,place_label=info["lat"],info["lon"],info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label
elev=get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# ---------------- Giorno e blocchi (niente fuso orario toggle) ----------------
cdate,_ = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())

st.subheader("1) Finestre orarie A · B · C")
c1,c2,c3=st.columns(3)
with c1:
    A_s=st.time_input("Inizio A", time(9,0)); A_e=st.time_input("Fine A", time(11,0))
with c2:
    B_s=st.time_input("Inizio B", time(11,0)); B_e=st.time_input("Fine B", time(13,0))
with c3:
    C_s=st.time_input("Inizio C", time(13,0)); C_e=st.time_input("Fine C", time(16,0))

st.subheader("2) Orizzonte previsionale")
hours=st.slider("Ore previsione (da ora)",12,168,72,12)
st.caption("Suggerimento: < 48h → stime più affidabili")

# ---------------- Open-Meteo ----------------
def fetch_open_meteo(lat, lon):
    r=requests.get("https://api.open-meteo.com/v1/forecast", params=dict(
        latitude=lat, longitude=lon, timezone="auto",
        hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
        forecast_days=7
    ), timeout=30)
    r.raise_for_status();  return r.json()

def build_df(js, hours):
    h=js["hourly"]; df=pd.DataFrame(h); df["time"]=pd.to_datetime(df["time"])
    tzname=js.get("timezone","UTC"); now0=pd.Timestamp.now(tz=tz.gettz(tzname)).floor("H").tz_localize(None)
    df=df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)
    out=pd.DataFrame()
    out["time"]=df["time"]
    out["T2m"]=df["temperature_2m"].astype(float)
    out["RH"]=df.get("relative_humidity_2m", pd.Series(np.nan, index=df.index)).astype(float)
    out["td"]=df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]=(df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]=(df["windspeed_10m"].astype(float)/3.6) # m/s
    out["sunup"]=df["is_day"].astype(int)
    out["prp_mmph"]=df["precipitation"].astype(float)
    out["rain"]=df.get("rain",0.0).astype(float)
    out["snowfall"]=df.get("snowfall",0.0).astype(float)
    out["wcode"]=df.get("weathercode",0).astype(int)
    return out

def prp_type_row(row):
    if pd.isna(row.prp_mmph) or row.prp_mmph<=0: return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes={71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# ---------------- QUICK-WINS INPUT ----------------
def ensure_inputs(X: pd.DataFrame)->pd.DataFrame:
    """RH da T/td se manca; wet-bulb (Stull); vento effettivo; radiazione stimata; albedo dinamico."""
    X=X.copy()

    # RH da T/td quando RH è NaN
    need_rh = X["RH"].isna()
    if need_rh.any():
        # Magnus-Tetens per saturation vapour pressure
        def _svp(T): return 6.112*np.exp((17.62*T)/(243.12+T))
        es=_svp(X["T2m"]); e=_svp(X["td"])
        RH_calc=(100*(e/es)).clip(1,100)
        X.loc[need_rh,"RH"]=RH_calc[need_rh]

    # Wet-bulb (Stull 2011) – vettoriale
    T=X["T2m"]; RH=X["RH"].clip(1,100)
    Tw = T*np.arctan(0.151977*np.sqrt(RH+8.313659)) \
         + np.arctan(T+RH) - np.arctan(RH-1.676331) \
         + 0.00391838*np.power(RH,1.5)*np.arctan(0.023101*RH) - 4.686035
    X["Tw"]=Tw

    # Vento effettivo
    X["wind_eff"]=np.clip(X["wind"],0,8)
    X["wind_conv"]=np.log1p(X["wind_eff"])/np.log1p(8)  # 0..1

    # Radiazione stimata (clear-sky semplice + nuvolosità)
    doy = X["time"].dt.dayofyear
    decl = 23.45*np.pi/180*np.sin(2*np.pi*(284+doy)/365)               # rad
    # irradianza extra-atmosferica normalizzata ~ 1367 W/m2 * qualcosa; usiamo forma semplice:
    SW_clear = 1.0*np.cos(decl.clip(-np.pi/3,np.pi/3).abs()) + 0.7     # scala 0.7..1.7
    SW_down = SW_clear * (1 - 0.75*(X["cloud"]**3))
    X["SW_down"]=SW_down.clip(0,2.0)  # scala adimensionale 0..2

    # Albedo dinamico (età neve)
    # età = ore dal’ultima nevicata > 0.5 mm/h
    last_snow_idx = (~(X["snowfall"]>0.5)).cumsum()
    first_seen = X.groupby(last_snow_idx).cumcount()  # contatore ore dall’ultima nevicata
    age_h = first_seen.where(X["snowfall"]<=0.5, 0).astype(float)
    albedo = 0.85 - (0.30*(age_h/72.0)).clip(0,1)     # 0.85 → 0.55 in ~3 giorni
    # scalda più velocemente se T>0
    albedo = np.where(X["T2m"]>0, albedo-0.05, albedo)
    X["albedo"]=pd.Series(albedo, index=X.index).clip(0.45,0.85)

    return X

# ---------------- Modello neve ----------------
def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    X=ensure_inputs(df)
    X["ptyp"]=X.apply(prp_type_row, axis=1)

    sunup = X["sunup"]==1
    near0 = X["T2m"].between(-1.2, 1.2)

    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ((X["ptyp"]=="snow") & X["T2m"].ge(-1.0)) |
        (sunup & (X["cloud"]<0.35) & X["T2m"].ge(-2.0)) |
        (X["T2m"]>0.0)
    )

    T_surf=pd.Series(index=X.index, dtype=float); T_surf.loc[wet]=0.0

    dry = ~wet
    clear=(1.0 - X["cloud"]).clip(0,1)
    # raffreddamento radiativo notturno con vento/log e radiazione
    drad = (1.2 + 2.8*clear - 0.6*X["wind_conv"] - 0.8*X["SW_down"]*(sunup.astype(float))).clip(0.3,5.0)
    T_surf.loc[dry] = X["T2m"][dry] - drad[dry]

    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (X["T2m"] + 0.4*(1.0 - X["cloud"]))[sunny_cold],
        pd.Series(-0.8, index=X.index)[sunny_cold]
    ], axis=1).min(axis=1)

    # top ~5mm
    T_top5=pd.Series(index=X.index, dtype=float)
    tau=pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptyp"]!="none") | (X["wind"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - (np.exp(-dt_hours / tau))
    if len(X)>0:
        T_top5.iloc[0]=float(min(X["T2m"].iloc[0],0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i]=T_top5.iloc[i-1] + alpha.iloc[i]*(T_surf.iloc[i]-T_top5.iloc[i-1])

    X["T_surf"]=T_surf.round(2); X["T_top5"]=T_top5.round(2)

    # indice scorrevolezza 0..100
    base = 100 - (abs(X["T_surf"] + 6.0)*7.5).clip(0,100)
    wet_pen = (X["ptyp"].isin(["rain","mixed"]) | near0).astype(int)*25
    stick_pen = ((X["RH"].fillna(75)>90) & (X["T_surf"]>-1.0)).astype(int)*10
    speed_idx = (base - wet_pen - stick_pen).clip(0,100)
    X["speed_index"]=speed_idx.round(0)

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
    x=float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# ---------------- Scioline & strutture ----------------
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

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Tsurf):
    if Tsurf<=-10: return "Linear Fine (freddo/secco)"
    if Tsurf<=-3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf<=0.5: return "Diagonal/V (umido)"
    return "Wave marcata (bagnato caldo)"

# ---------------- NOAA soft enrichment ----------------
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)
def try_enrich_with_noaa(df, lat, lon, when_day: date):
    if not NOAA_TOKEN: return df
    # Per robustezza: piccola correzione climatologica senza dipendenze esterne
    try:
        corr=(70 - df["RH"].fillna(70))*0.03
        df["RH"]=(df["RH"].fillna(70)+corr).clip(5,100)
        return df
    except: return df

# ---------------- Calcolo ----------------
st.subheader("3) Meteo & calcolo")
btn=st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js=fetch_open_meteo(lat,lon)
        raw=build_df(js,hours)
        raw=try_enrich_with_noaa(raw, lat, lon, target_day)
        res=snow_temperature_model(raw)

        # tabella completa
        show=pd.DataFrame({
            "Ora":res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)":res["T2m"].round(1),
            "Td (°C)":res["td"].round(1),
            "UR (%)":res["RH"].round(0),
            "Tw (°C)":res["Tw"].round(1),
            "Vento (m/s)":res["wind"].round(1),
            "Nuvolosità (%)":(res["cloud"]*100).round(0),
            "Rad (rel)":res["SW_down"].round(2),
            "Prp (mm/h)":res["prp_mmph"].round(2),
            "Tipo prp":res.apply(lambda r:{"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}[prp_type_row(r)],axis=1),
            "T neve surf (°C)":res["T_surf"].round(1),
            "T top5mm (°C)":res["T_top5"].round(1),
            "Indice scorrevolezza":res["speed_index"].astype(int),
        })
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Grafici rapidi
        fig, ax = plt.subplots(figsize=(8,3), dpi=140)
        ax.plot(res["time"], res["T2m"], label="T aria")
        ax.plot(res["time"], res["T_surf"], label="T neve surf")
        ax.plot(res["time"], res["T_top5"], label="T top5mm")
        ax.legend(); ax.grid(True, alpha=.2); ax.set_title("Temperature")
        st.pyplot(fig)

        # Blocchi
        blocks={"A":(A_s,A_e),"B":(B_s,B_e),"C":(C_s,C_e)}
        tzobj=tz.gettz(js.get("timezone","UTC"))
        res_local=res.copy()
        res_local["dt"]=res_local["time"].dt.tz_localize(tzobj, nonexistent="shift_forward", ambiguous="NaT")
        res_local["date"]=res_local["dt"].dt.date
        res_local["t_only"]=res_local["dt"].dt.time

        for L,(s,e) in blocks.items():
            st.markdown("---"); st.markdown(f"### Blocco {L}")
            daymask=res_local["date"]==target_day
            day_df=res_local[daymask]
            if day_df.empty: W=res_local.head(6)
            else:
                W=day_df[(day_df["t_only"]>=s) & (day_df["t_only"]<=e)]
                if W.empty: W=day_df.head(6)

            if W.empty:
                st.info("Nessun dato nella finestra scelta.")
                continue

            t_med=float(W["T_surf"].mean())
            k=classify_snow(W.iloc[0])
            rel=reliability((W.index[0]+1))
            st.markdown(f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}%</div>",
                        unsafe_allow_html=True)

            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            # Tabella discipline (SL/GS/SG/DH)
            rows=[]
            for d in ["SL","GS","SG","DH"]:
                # lamina/angoli semplificati in funzione T
                if t_med<=-10: side={"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[d]; base=0.5; struct="Linear Fine"
                elif t_med<=-3: side={"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[d]; base=0.7; struct="Cross Hatch"
                elif t_med<=0.5: side={"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]; base=0.8; struct="Diagonal/V"
                else: side={"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[d]; base=1.0; struct="Wave"
                rows.append([d, struct, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE","Lamina BASE"]))

            # Scioline
            st.markdown("**Scioline suggerite (per temperatura neve media):**")
            cols1=st.columns(4); cols2=st.columns(4)
            for i,(name,_,bands) in enumerate(BRANDS[:4]):
                cols1[i].markdown(f"<div class='card'><b>{name}</b><br>{pick_wax(bands,t_med)}</div>", unsafe_allow_html=True)
            for i,(name,_,bands) in enumerate(BRANDS[4:]):
                cols2[i].markdown(f"<div class='card'><b>{name}</b><br>{pick_wax(bands,t_med)}</div>", unsafe_allow_html=True)

            mini=pd.DataFrame({
                "Ora":W["dt"].dt.strftime("%H:%M"),
                "T aria":W["T2m"].round(1),
                "T neve":W["T_surf"].round(1),
                "UR%":W["RH"].round(0),
                "V m/s":W["wind"].round(1),
                "Prp":W.apply(prp_type_row, axis=1).map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
            })
            st.dataframe(mini, use_container_width=True, hide_index=True)

        csv=res.copy(); csv["time"]=csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
