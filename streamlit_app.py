# telemark_pro_app.py
# — Telemark · Pro Wax & Tune (dark) —
# Reintroduce wax brands (8), ricerca con Enter, date future,
# T_surf corretta, umidità, “tipo neve”, indice di scorrevolezza.

import streamlit as st
import pandas as pd
import numpy as np
import requests, math, base64, datetime as dt
from datetime import time, date, timedelta

# ------------------------ THEME / PAGE ------------------------
PRIMARY = "#10bfcf"   # Telemark turquoise
BG      = "#0f172a"   # slate-900
CARD    = "#111827"   # slate-800
TEXT    = "#e5e7eb"   # slate-200

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --primary: {PRIMARY};
}}
[data-testid="stAppViewContainer"] > .main {{ background: linear-gradient(180deg,{BG} 0%, #0b1223 100%); }}
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5, p, span, div, label {{ color:{TEXT}; }}
.card {{ background:{CARD}; border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:14px; box-shadow:0 10px 22px rgba(0,0,0,.35); }}
.badge {{ display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,.15); font-size:.78rem; opacity:.9; }}
.brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px; background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); }}
.brand img {{ height:22px; }}
.kpi {{ display:flex; gap:10px; align-items:center; background:rgba(16,191,207,.08); border:1px dashed rgba(16,191,207,.45);
       padding:10px 12px; border-radius:12px; }}
.kpi .lab {{ font-size:.78rem; color:#93c5fd; }}
.kpi .val {{ font-size:1rem; font-weight:800; }}
.banner {{
  background: rgba(16,191,207,.12);
  border: 1px solid rgba(16,191,207,.35);
  padding: 10px 12px; border-radius: 12px; margin: 6px 0 14px 0;
}}
.table small {{ opacity:.8; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")

# ------------------------ HELPERS ------------------------
def flag(cc:str)->str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    # nome corto + admin1 (o valle) + ISO-paese, senza diventare “Zermatt” se cerchi Plateau Rosa
    name = (addr.get("peak") or addr.get("hamlet") or addr.get("neighbourhood")
            or addr.get("village") or addr.get("town") or addr.get("locality")
            or addr.get("suburb") or addr.get("ski") or fallback.split(",")[0])
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    short = ", ".join(parts[:2])
    return f"{short} — {cc}" if cc else short

def search_places(query:str, limit:int=10):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format":"json", "limit":limit, "addressdetails":1},
            headers={"User-Agent":"telemark-wax-pro/1.0"},
            timeout=8
        )
        r.raise_for_status()
        out = []
        for item in r.json():
            addr = item.get("address", {}) or {}
            lat = float(item.get("lat", 0)); lon = float(item.get("lon", 0))
            label_short = concise_label(addr, item.get("display_name",""))
            lab = f"{flag(addr.get('country_code',''))}  {label_short}"
            out.append({"label": lab, "lat": lat, "lon": lon})
        return out
    except Exception:
        return []

def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude":lat,"longitude":lon}, timeout=8)
        r.raise_for_status()
        js = r.json()
        if js and "elevation" in js and js["elevation"]:
            return float(js["elevation"][0])
    except Exception:
        pass
    return None

def fetch_open_meteo(lat, lon, start_date:date, hours:int, tzname="Europe/Rome"):
    # chiediamo da 'start_date' a start_date+7gg e poi ritagliamo 'hours'
    end_date = start_date + timedelta(days=7)
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":lat, "longitude":lon, "timezone":tzname,
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "hourly":"temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        }, timeout=30
    )
    r.raise_for_status()
    js = r.json()
    h = js["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    # taglio alle prossime 'hours' ore a partire da adesso oppure dall’inizio del giorno scelto
    start_ts = pd.Timestamp(dt.datetime.now().astimezone().tzinfo).floor("H")
    if start_date != date.today():
        start_ts = pd.Timestamp(start_date).tz_localize(None)  # inizio del giorno (naive)
    df = df[df["time"] >= start_ts].head(hours).reset_index(drop=True)
    return df

# Magnus (da T e Td) — RH di riferimento quando manca
def rh_from_t_td(Tc, TDc):
    a=17.625; b=243.04
    es  = np.exp((a*Tc)/(b+Tc))
    e   = np.exp((a*TDc)/(b+TDc))
    return np.clip(100 * (e/es), 0, 100)

def prp_type_row(prp, rain, snow, code):
    if prp<=0 or np.isnan(prp): return "none"
    if (rain>0) and (snow>0):   return "mixed"
    if (snow>0) and (rain==0):  return "snow"
    if (rain>0) and (snow==0):  return "rain"
    # fallback da weathercode
    snow_codes={71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(code) in snow_codes: return "snow"
    if int(code) in rain_codes: return "rain"
    return "mixed"

def build_df(df:pd.DataFrame):
    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    out["td"]   = df["dew_point_2m"].astype(float)
    if "relative_humidity_2m" in df:
        out["rh"] = df["relative_humidity_2m"].astype(float)
    else:
        out["rh"] = rh_from_t_td(out["T2m"].to_numpy(), out["td"].to_numpy())
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"]  = (df["windspeed_10m"].astype(float)/3.6).clip(0, None)  # m/s
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"]  = df["rain"].astype(float)
    out["snow"]  = df["snowfall"].astype(float)
    out["wcode"] = df["weathercode"].astype(int)
    out["prp_type"] = [
        prp_type_row(prp, rain, snow, code)
        for prp, rain, snow, code in zip(out["prp_mmph"], out["rain"], out["snow"], out["wcode"])
    ]
    return out

# Modello semplice e robusto per T_surf e T_top5 (senza Series.iloc sul vettore alpha)
def compute_snow_temp(df:pd.DataFrame, dt_hours=1.0):
    T2  = df["T2m"].to_numpy(dtype=float)
    TD  = df["td"].to_numpy(dtype=float)
    CC  = df["cloud"].to_numpy(dtype=float)
    W   = df["wind"].to_numpy(dtype=float)          # m/s
    DAY = df["sunup"].to_numpy(dtype=int)
    PR  = df["prp_mmph"].to_numpy(dtype=float)
    PT  = df["prp_type"].astype(str).str.lower().to_numpy()

    tw = (T2 + TD) / 2.0
    rain = (PT=="rain") | (PT=="mixed")
    snow = (PT=="snow")
    # condizioni bagnato
    wet  = (rain) | (T2>0.0) | ((DAY==1)&(CC<0.3)&(T2>=-3.0)) | (snow & ((T2>=-1.0) | (tw>=-0.5)))

    T_surf = np.empty_like(T2, dtype=float)
    T_surf[:] = np.nan
    T_surf[wet] = 0.0

    dry = ~wet
    clear = (1.0 - CC).clip(0,1)
    windc = np.minimum(W, 6.0)
    drad = np.clip(1.6 + 3.0*clear - 0.3*windc, 0.5, 4.5)  # perdita radiativa/convettiva
    T_surf[dry] = T2[dry] - drad[dry]

    sunny_cold = (DAY==1) & dry & (T2<=0) & (T2>=-10)
    T_surf[sunny_cold] = np.minimum(T2[sunny_cold] + 0.5*(1.0 - CC[sunny_cold]), -0.5)

    # T_top5 con time-constant variabile
    tau = np.full_like(T2, 6.0, dtype=float)
    tau[(rain | snow | (W>=6))] = 3.0
    tau[((DAY==0) & (W<2) & (CC<0.3))] = 8.0
    alpha = 1.0 - np.exp(-dt_hours / tau)

    T_top5 = np.empty_like(T2, dtype=float)
    if T2.size:
        T_top5[0] = min(T2[0], 0.0)
        for i in range(1, T2.size):
            T_top5[i] = T_top5[i-1] + alpha[i] * (T_surf[i] - T_top5[i-1])

    out = df.copy()
    out["T_surf"] = T_surf
    out["T_top5"] = T_top5
    return out

# Classificazione neve + indice di scorrevolezza (0–100)
def describe_snow(row):
    t  = row.T_surf
    rh = row.rh
    wind = row.wind
    prp = row.prp_type
    # consistenza
    if prp in ("rain","mixed") or (t>-0.3) or (rh>90 and row.T2m>0):
        typ = "bagnata / primaverile"
    elif prp=="snow" and row.T2m<=-1:
        typ = "neve nuova asciutta"
    elif (row.T2m<-6 and row.cloud<0.4):
        typ = "molto fredda / secca"
    else:
        typ = "trasformata / granulosa"
    # scorrevolezza euristica
    score = 70.0
    score -= max(0, t+0.5)*15    # vicino allo 0 peggiora
    score -= max(0, rh-85)/2.0   # aria molto umida peggiora
    score -= min(10, wind*2.0)   # tanto vento = neve spazzata, non sempre male ma prudente
    if prp=="rain": score -= 15
    if prp=="snow": score += 5
    score = int(np.clip(score, 5, 95))
    # affidabilità molto semplice
    reliab = 85
    if prp!="none": reliab -= 15
    if row.cloud>0.7: reliab -= 10
    reliab = int(np.clip(reliab, 40, 95))
    return typ, score, reliab

# ---------- WAX BANDS (8 marchi) ----------
SWIX = [("PS5 Turquoise",-18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("Ultra/Alpha Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6), ("Univ Medium",-7,-2), ("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]
BRAND_BANDS = [
    ("Swix"      ,"#ef4444", SWIX),
    ("Toko"      ,"#f59e0b", TOKO),
    ("Vola"      ,"#3b82f6", VOLA),
    ("Rode"      ,"#22c55e", RODE),
    ("Holmenkol" ,"#06b6d4", HOLM),
    ("Maplus"    ,"#f97316", MAPL),
    ("Start"     ,"#eab308", START),
    ("Skigo"     ,"#a855f7", SKIGO),
]
def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def svg_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ UI — 1) RICERCA ------------------------
st.markdown("#### 1) Cerca località")
with st.form("f_search", border=False):
    q = st.text_input("Digita il nome (es. Plateau Rosa, Champoluc, Cervinia)", "", help="Premi Invio per cercare")
    start_day = st.date_input("Giorno di riferimento", value=date.today(), min_value=date.today(), max_value=date.today()+timedelta(days=6))
    submitted = st.form_submit_button("Cerca", type="primary")
if submitted and q.strip():
    options = search_places(q.strip(), limit=12)
    if options:
        st.session_state["place_list"] = options
        # auto-seleziona la prima (effetto “Enter automatico”)
        st.session_state["sel_place"] = options[0]
    else:
        st.session_state["place_list"] = []
        st.session_state["sel_place"] = None

place  = st.session_state.get("sel_place", {"label":"🇮🇹  Champoluc — IT","lat":45.831,"lon":7.730})
lat, lon, place_label = place["lat"], place["lon"], place["label"]
elev = get_elevation(lat, lon)
alt_txt = f" · Altitudine **{int(elev)} m**" if elev is not None else ""
st.markdown(f"**Località:** {place_label}{alt_txt}")

# ------------------------ UI — 2) FINESTRE ------------------------
st.markdown("#### 2) Finestre orarie A · B · C")
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9,0))
    A_end   = st.time_input("Fine A",   time(11,0))
with c2:
    B_start = st.time_input("Inizio B", time(11,0))
    B_end   = st.time_input("Fine B",   time(13,0))
with c3:
    C_start = st.time_input("Inizio C", time(13,0))
    C_end   = st.time_input("Fine C",   time(16,0))
hours = st.slider("Ore previsione (orizzonte)", 12, 168, 72, 12)

# ------------------------ UI — 3) CALCOLO ------------------------
st.markdown("#### 3) Dati meteo & calcolo")
if st.button("Scarica/aggiorna previsioni", type="primary"):
    try:
        raw = fetch_open_meteo(lat, lon, start_day, hours, "Europe/Rome")
        src = build_df(raw)
        res = compute_snow_temp(src, dt_hours=1.0)

        # descrizione + indice
        desc = res.apply(describe_snow, axis=1, result_type="expand")
        res["snow_type"] = desc[0]
        res["scorrevolezza"] = desc[1]
        res["affidabilita_%"] = desc[2]

        st.success(f"Dati per **{place_label}** caricati.")
        show = res.rename(columns={
            "time":"Ora", "T2m":"T aria (°C)", "td":"T rugiada (°C)",
            "rh":"UR (%)", "cloud":"Nuvolosità (0–1)", "wind":"Vento (m/s)",
            "prp_mmph":"Prec. (mm/h)", "prp_type":"Tipo precipitazione",
            "T_surf":"T neve superficie (°C)", "T_top5":"T neve top 5mm (°C)",
            "snow_type":"Tipo neve",
            "scorrevolezza":"Indice di scorrevolezza (0–100)",
            "affidabilita_%":"Affidabilità (%)"
        })
        # tabella più leggibile
        st.dataframe(
            show[[
                "Ora","T aria (°C)","UR (%)","Vento (m/s)","Nuvolosità (0–1)","Prec. (mm/h)","Tipo precipitazione",
                "T neve superficie (°C)","T neve top 5mm (°C)",
                "Tipo neve","Indice di scorrevolezza (0–100)","Affidabilità (%)"
            ]],
            use_container_width=True, height=420
        )
        st.download_button("Scarica CSV (risultato)", data=show.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # finestre A/B/C
        def slice_window(df, s, e):
            dd = df.copy()
            dd["date"] = pd.to_datetime(dd["time"]).dt.date
            dd["t"] = pd.to_datetime(dd["time"]).dt.time
            mask = (dd["date"]==start_day) & (dd["t"]>=s) & (dd["t"]<=e)
            w = dd[mask]
            return w if not w.empty else dd.head(6)

        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown(f"---\n### Blocco {L}")
            W = slice_window(res, s, e)
            t_med = float(W["T_surf"].mean())
            t_air = float(W["T2m"].mean())
            sc_med = int(W["scorrevolezza"].mean())
            snow_mode = W["snow_type"].mode().iloc[0] if not W.empty else "—"
            reliab = int(W["affidabilita_%"].mean())
            st.markdown(f"<div class='banner'><b>Condizioni:</b> {snow_mode} · "
                        f"<b>T neve media:</b> {t_med:.1f}°C · <b>T aria:</b> {t_air:.1f}°C · "
                        f"<b>Indice di scorrevolezza:</b> {sc_med}/100 · <b>Affidabilità:</b> {reliab}%</div>",
                        unsafe_allow_html=True)

            # 8 marchi – carte con consiglio
            cols = st.columns(4); cols2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div class='brand'><img src='{svg_badge(brand.upper(), col)}'/>"
                    f"<div><div style='opacity:.8;font-size:.8rem'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div class='brand'><img src='{svg_badge(brand.upper(), col)}'/>"
                    f"<div><div style='opacity:.8;font-size:.8rem'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # tabella angoli/struttura (nomi, niente immagini)
            def tune_for(t_surf, discipline):
                if t_surf <= -10:
                    fam = "Lineare fine (freddo/secco)"; base = 0.5; side = {"SL":88.5,"GS":88.0,"SG":87.5,"DH":87.5}[discipline]
                elif t_surf <= -3:
                    fam = "Cross / leggera onda (universale)"; base = 0.7; side = {"SL":88.0,"GS":88.0,"SG":87.5,"DH":87.0}[discipline]
                else:
                    fam = "Diagonale / V (umido/caldo)"; base = 0.8 if t_surf<=0.5 else 1.0; side = {"SL":88.0,"GS":87.5,"SG":87.0,"DH":87.0}[discipline]
                return fam, side, base

            rows=[]
            for d in ["SL","GS","SG","DH"]:
                fam, side, base = tune_for(t_med, d)
                rows.append([d, fam, f"{side:.1f}°", f"{base:.1f}°"])
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
