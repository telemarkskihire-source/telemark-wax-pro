# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math, os
import matplotlib.pyplot as plt
from datetime import time, date, datetime, timedelta
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ========================= THEME =========================
PRIMARY = "#06b6d4"    # turchese vivo
ACCENT  = "#eab308"    # giallo caldo per KPI
TEXT    = "#e5e7eb"    # testo chiaro
BG      = "#0b1220"    # sfondo scuro
CARD    = "#0f172a"    # card scuro

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] > .main {{
  background: radial-gradient(1200px 600px at 20% -10%, #0b1a33 0%, {BG} 40%, #0a0f1a 100%);
}}
.block-container {{ padding-top: .8rem; }}
* {{ color:{TEXT}; }}
h1,h2,h3,h4,h5 {{ color:#f8fafc; letter-spacing:.2px }}
.small {{ color:#9ca3af; font-size:.85rem }}
.card {{ background:{CARD}; border:1px solid rgba(255,255,255,.08); border-radius:18px; padding:16px; box-shadow:0 12px 36px rgba(0,0,0,.32) }}
.badge {{ display:inline-flex; gap:.5rem; align-items:center; padding:.25rem .6rem;
         border-radius:999px; border:1px solid {PRIMARY}44; color:#cffafe; background:{PRIMARY}1a; font-size:.8rem; }}
.kpi {{ display:flex; gap:.6rem; align-items:center; background:#0b2236; border:1px solid #16435b; padding:.55rem .75rem; border-radius:12px; }}
.kpi .lab {{ color:#93c5fd; font-size:.8rem }}
.kpi .val {{ font-weight:800; color:#fef08a }}
hr {{ border:none; border-top:1px solid rgba(255,255,255,.1); margin:.6rem 0 }}
.brand {{ display:flex; align-items:center; gap:.6rem; padding:.6rem .7rem; border-radius:12px;
          background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08) }}
.brand img {{ height:22px }}
.banner {{
  background: linear-gradient(90deg, #0a2a3a, #0f2131);
  border: 1px solid #12374f; border-radius: 14px; padding: 10px 14px; margin-top: .4rem;
}}
.banner b {{ color:#fef9c3 }}
.table thead th {{ background:#0b1c2a !important }}
</style>
""", unsafe_allow_html=True)

st.markdown("## Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca smart · Finestre A/B/C con scelta data · Algoritmo neve · Scioline · Indice di scorrevolezza</span>", unsafe_allow_html=True)

# ========================= HELPERS =========================
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

COUNTRIES = {
    "Tutte (consigliato)": "",
    "Italia 🇮🇹": "it",
    "Svizzera 🇨🇭": "ch",
    "Francia 🇫🇷": "fr",
    "Austria 🇦🇹": "at",
    "Germania 🇩🇪": "de",
    "Norvegia 🇳🇴": "no",
    "Svezia 🇸🇪": "se",
    "Finlandia 🇫🇮": "fi",
}

def concise_label(addr:dict, display_name:str)->str:
    # Nome breve + admin1 + country code
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or display_name.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    short = ", ".join([p for p in [name, admin1] if p])
    if cc: short = f"{short} — {cc}"
    return short

def nominatim_search(q:str):
    # richiama ad ogni tasto (no Enter) — filtra per nazione se selezionata
    country = st.session_state.get("_country_filter","")
    if not q or len(q) < 2:
        return []
    try:
        params = {"q": q, "format":"json", "limit": 12, "addressdetails": 1}
        if country:
            params["countrycodes"] = country
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params=params,
                         headers={"User-Agent":"telemark-wax-pro/1.2"},
                         timeout=8)
        r.raise_for_status()
        st.session_state._geo_opts = {}
        out = []
        for it in r.json():
            addr = it.get("address",{}) or {}
            label_short = concise_label(addr, it.get("display_name",""))
            cc = (addr.get("country_code") or "").upper()
            label = f"{flag(cc)}  {label_short}"
            lat = float(it.get("lat",0)); lon = float(it.get("lon",0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_opts[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
            out.append(key)
        return out
    except:
        return []

def get_elevation(lat:float, lon:float):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if js and "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except:
        pass
    return None

# ========================= DATA =========================
def fetch_open_meteo(lat, lon, tzname="Europe/Rome"):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "hourly": ",".join([
                "temperature_2m","dew_point_2m","relative_humidity_2m",
                "precipitation","rain","snowfall","cloudcover",
                "windspeed_10m","is_day","weathercode",
            ]),
            "forecast_days": 7,
        }, timeout=30
    )
    r.raise_for_status()
    return r.json()

def _prp_type(row):
    # classifica precipitazione
    prp = row.get("precipitation", 0.0)
    rain = row.get("rain", 0.0)
    snow = row.get("snowfall", 0.0)
    if prp and prp > 0:
        if rain > 0 and snow > 0: return "mixed"
        if snow > 0 and rain == 0: return "snow"
        if rain > 0 and snow == 0: return "rain"
        return "mixed"
    return "none"

def build_df(js, hours, tzname):
    h = js["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now_tz = pd.Timestamp.now(tz=tz.gettz(tzname)).floor("H").tz_convert(None)
    df = df[df["time"] >= now_tz].head(hours).reset_index(drop=True)

    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["Td"]   = df["dew_point_2m"].astype(float)
    out["RH"]   = df["relative_humidity_2m"].astype(float).clip(0,100)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).clip(lower=0)   # m/s
    out["is_day"] = df["is_day"].astype(int)
    out["precip"]  = df["precipitation"].astype(float)
    out["rain"]    = df["rain"].astype(float)
    out["snowfall"]= df["snowfall"].astype(float)

    # precip type
    out["prp_type"] = out[["precip","rain","snowfall"]].apply(
        lambda r: _prp_type({"precipitation":r["precip"],"rain":r["rain"],"snowfall":r["snowfall"]}), axis=1
    )

    # wet-bulb (Stull 2011 approx)
    # Tw ≈ T*atan(0.151977*(RH+8.313659)^{1/2}) + atan(T+RH) - atan(RH-1.676331) + 0.00391838 RH^{3/2} atan(0.023101*RH) - 4.686035
    import numpy as np
    T = out["T2m"].values
    RH = out["RH"].values
    Tw = (T*np.arctan(0.151977*np.sqrt(RH+8.313659)) +
          np.arctan(T+RH) - np.arctan(RH-1.676331) +
          0.00391838*(RH**1.5)*np.arctan(0.023101*RH) - 4.686035)
    out["Tw"] = Tw

    return out

# ========================= SURFACE MODEL =========================
def compute_surface(df: pd.DataFrame):
    """
    Modello euristico migliorato della T_surf e T_top5:
    - eff. radiativo/vento di raffreddamento
    - influenza wet-bulb e tipo precipitazione
    - evita clamp a 0 costante: permette T_surf < 0 anche con neve asciutta,
      e leggermente > Tw con umido/bagnato.
    """
    out = df.copy()
    sunup = out["is_day"] == 1

    # raffreddamento radiativo (più cielo sereno + poco vento)
    clear = (1.0 - out["cloud"]).clip(0,1)
    windc = out["wind"].clip(upper=8.0)
    rad_cool = (1.2 + 2.8*clear - 0.25*windc).clip(0.2, 3.8)

    # base candidate (asciutto)
    T_surf_dry = out["T2m"] - rad_cool

    # bagnato/umido: avvicina a Tw, ma non “incolla” a 0
    wet_cond = (
        (out["prp_type"].isin(["rain","mixed"])) |
        ((out["prp_type"]=="snow") & (out["T2m"]>-2) & (out["Tw"]>-3)) |
        (out["T2m"]>=0.5)
    )
    T_wet_target = out["Tw"].clip(upper=0.0)  # se Tw > 0, usa 0 (superficie tende a 0)
    T_surf = T_surf_dry.copy()
    T_surf[wet_cond] = 0.6*T_wet_target[wet_cond] + 0.4*T_surf_dry[wet_cond]

    # strato top 5mm (inerzia termica con tau variabile)
    T_top5 = pd.Series(index=out.index, dtype=float)
    tau = pd.Series(6.0, index=out.index)  # ore
    tau.loc[out["precip"]>0] = 3.0
    tau.loc[(~sunup) & (clear>0.6) & (out["wind"]<2.0)] = 8.0

    alpha = 1.0 - (math.e ** (-1.0 / tau))  # timestep = 1h
    if len(out)>0:
        T_top5.iloc[0] = min(out["T2m"].iloc[0], 0.0)
        for i in range(1, len(out)):
            prev = T_top5.iloc[i-1]
            T_top5.iloc[i] = prev + alpha.iloc[i] * (T_surf.iloc[i] - prev)

    out["T_surf"] = T_surf
    out["T_top5"] = T_top5

    return out

# ========================= CLASSIFICAZIONE NEVE =========================
def classify_snow(row):
    t = row["T_surf"]
    prp = row["prp_type"]
    rh = row["RH"]
    snow = row["snowfall"]
    if prp == "rain":
        return "bagnata"
    if prp == "mixed":
        return "umida / mista"
    if prp == "snow" and snow > 0.3:
        if t >= -1.0: return "neve nuova umida"
        return "neve nuova fredda"
    # senza precipitazione
    if t >= -0.3: return "bagnata"
    if -3 <= t < -0.3 and rh>80: return "umida"
    if -8 <= t < -3: return "compatta / trasformata"
    return "polverosa fredda"

def confidence(df):
    # confidenza semplice: più dati coerenti = maggiore
    span = df["T_surf"].max() - df["T_surf"].min()
    prp = df["precip"].mean()
    cloud_var = df["cloud"].std()
    c = 0.6
    if span < 1.5: c += 0.15
    if prp < 0.2: c += 0.1
    if cloud_var < 0.2: c += 0.1
    return int( max(0, min(100, round(c*100))) )

def glide_index(t_surf, rh, prp_type):
    """
    Indice di scorrevolezza (0–100).
    - vicino a 0°C e umido: +, ma pioggia penalizza
    - molto freddo e secco: -, ma neve compatta media = ok
    """
    base = 50
    # temperatura rispetto a 0°C
    base += 20 * max(0, 1 - abs((t_surf)/3.0))    # migliore se |T| < 3°C
    # umidità aiuta scorrimento (fino a un punto)
    base += (rh-60)*0.2
    # precipitazione
    if prp_type == "rain": base -= 15
    if prp_type == "snow": base += 5
    return int(max(0, min(100, round(base))))

# ========================= WAX BRANDS =========================
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
def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def logo_badge(text:str, path:str)->str:
    if os.path.exists(path):
        b64 = base64.b64encode(open(path,"rb").read()).decode("utf-8")
        return f"<img src='data:image/png;base64,{b64}'/>"
    return f"<div style='font-weight:700'>{text}</div>"

# ========================= UI: RICERCA =========================
st.markdown("### 1) Località & orizzonte")

c1,c2 = st.columns([1,2])
with c1:
    country_label = st.selectbox("Nazione (opzionale, accelera la ricerca)", list(COUNTRIES.keys()), index=0)
    st.session_state["_country_filter"] = COUNTRIES[country_label]
with c2:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (es. Champoluc, Plateau Rosa, Sestriere)",
        clear_on_submit=False,
        default=None
    )

# decode selection
lat = st.session_state.get("lat", 45.831)
lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label","🇮🇹  Champoluc, Valle d’Aosta — IT")

if selected and "|||" in selected and "_geo_opts" in st.session_state:
    info = st.session_state._geo_opts.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"] = lat; st.session_state["lon"] = lon
        st.session_state["place_label"] = place_label

elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {place_label}{alt_txt}")

# Orizzonte e data di riferimento (NOVITÀ)
c3, c4 = st.columns([1,1])
with c3:
    tzname = "Europe/Rome"
    hours = st.slider("Ore previsione", 12, 168, 72, 12)
with c4:
    base_day = st.date_input("Giorno per le finestre A/B/C", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))

st.markdown("### 2) Finestre A · B · C")
a1,a2,a3 = st.columns(3)
with a1:
    A_start = st.time_input("Inizio A", time(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11,0), key="A_e")
with a2:
    B_start = st.time_input("Inizio B", time(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13,0), key="B_e")
with a3:
    C_start = st.time_input("Inizio C", time(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16,0), key="C_e")

# ========================= RUN =========================
st.markdown("### 3) Meteo & raccomandazioni")
go = st.button("Scarica previsioni + calcola")

def slice_window(res: pd.DataFrame, tzname, selected_day: date, s: time, e: time):
    t = res["time"].dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    W = D[(D["dt"].dt.date==selected_day) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(6)

if go:
    try:
        js = fetch_open_meteo(lat, lon, tzname)
        raw = build_df(js, hours, tzname)
        res = compute_surface(raw)

        # tabella compatta e chiara
        tbl = res.copy()
        tbl["Ora"] = tbl["time"].dt.strftime("%d/%m %H:%M")
        tbl = tbl[["Ora","T2m","Td","RH","cloud","wind","precip","rain","snowfall","prp_type","Tw","T_surf","T_top5"]]
        tbl = tbl.rename(columns={
            "RH":"UR%","cloud":"Nuvol.","wind":"Vento m/s","precip":"Prp mm/h","snowfall":"Neve cm/h",
            "prp_type":"Tipo prp","Tw":"T wet-bulb","T_surf":"T neve (surf)","T_top5":"T neve (5mm)"
        })
        st.dataframe(tbl, use_container_width=True)

        # grafici compatti
        t = res["time"]
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T neve (surf)"); plt.plot(t,res["T_top5"],label="T neve (5mm)")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["precip"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)

        # blocchi
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L} · {base_day.strftime('%d %b')}")
            W = slice_window(res, tzname, base_day, s, e)
            if W.empty:
                st.info("Nessun dato in finestra.")
                continue

            t_med = float(W["T_surf"].mean())
            rh_med = float(W["RH"].mean())
            prp_dom = W["prp_type"].value_counts().idxmax()
            cond = classify_snow(W.iloc[int(len(W)/2)])

            # Indice di scorrevolezza (0–100) — (ex “indice cromatico”)
            glide = glide_index(t_med, rh_med, prp_dom)
            conf = confidence(W)

            # banner descrizione
            st.markdown(
                f"<div class='banner'><b>Condizione neve:</b> {cond} · "
                f"<b>T_surf medio:</b> {t_med:.1f}°C · <b>UR:</b> {rh_med:.0f}% · "
                f"<b>Indice di scorrevolezza:</b> {glide}/100 · <b>Affidabilità:</b> {conf}%</div>",
                unsafe_allow_html=True
            )

            # Scioline (8 marchi)
            cols1 = st.columns(4); cols2 = st.columns(4)
            all_b = BRANDS[:4], BRANDS[4:]
            for i,(name,path,bands) in enumerate(all_b[0]):
                rec = pick_wax(bands, t_med)
                cols1[i].markdown(
                    f"<div class='brand'>{logo_badge(name,path)}<div><div class='small'>{name}</div>"
                    f"<div style='font-weight:800;color:#fef3c7'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(name,path,bands) in enumerate(all_b[1]):
                rec = pick_wax(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'>{logo_badge(name,path)}<div><div class='small'>{name}</div>"
                    f"<div style='font-weight:800;color:#fef3c7'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # Struttura (SOLO NOME — niente immagini)
            def structure_name(ts):
                if ts <= -10:   return "Lineare fine (freddo/secco)"
                if ts <= -3:    return "Incrociata leggera (universale)"
                return "Scarico diagonale / V (umido/caldo)"
            st.markdown(f"**Struttura consigliata:** {structure_name(t_med)}")

            # Angoli per discipline (tabella diretta)
            def tune_angles(ts, disc):
                if ts <= -10:
                    base = 0.5; sides = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}
                elif ts <= -3:
                    base = 0.7; sides = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}
                else:
                    base = 0.8 if ts<=0.5 else 1.0
                    sides = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}
                return sides.get(disc,88.0), base

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                side, base_ang = tune_angles(t_med, d)
                rows.append([d, f"{side:.1f}°", f"{base_ang:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Lamina SIDE (°)","Lamina BASE (°)"]))

        # download CSV
        st.download_button("Scarica CSV (tutta la serie)", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
