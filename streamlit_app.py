# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox  # dropdown live, stile meteoblue

# ------------------------ PAGE & THEME (sfondo bianco "clean") ------------------------
PRIMARY = "#0ea5b7"   # turchese Telemark più saturo
ACCENT  = "#111827"   # testo scuro
MUTED   = "#6b7280"   # testo secondario
CARD_BG = "#ffffff"   # card bianche
BORDER  = "rgba(0,0,0,.08)"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
.block-container {{ padding-top: 0.8rem; }}
h1,h2,h3,h4,h5, label, p, span, div {{ color:{ACCENT}; }}
.badge {{
  display:inline-block; border:1px solid {BORDER}; padding:6px 10px; border-radius:999px;
  font-size:.80rem; color:{MUTED};
}}
.card {{
  background:{CARD_BG}; border:1px solid {BORDER}; border-radius:16px; padding:14px;
  box-shadow:0 10px 22px rgba(0,0,0,.04);
}}
.brand {{
  display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px;
  background:#f8fafc; border:1px solid {BORDER};
}}
.brand img {{ height:24px; }}
.kpi {{
  display:flex; gap:8px; align-items:center; background:#ecfeff;
  border:1px dashed #99f6e4; padding:10px 12px; border-radius:12px;
}}
.kpi .lab {{ font-size:.78rem; color:#0891b2; }}
.kpi .val {{ font-size:1rem; font-weight:800; color:{ACCENT}; }}
hr {{ border: none; border-top: 1px solid {BORDER}; margin: 12px 0; }}
.st-emotion-cache-1vbkxwb p {{ margin-bottom: 0.2rem; }}
</style>
""", unsafe_allow_html=True)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca live tipo meteoblue · Blocchi A/B/C · 8 marchi · Strutture stile Wintersteiger · Angoli SIDE/BASE</span>", unsafe_allow_html=True)

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def shorten_label_from_nominatim(item: dict) -> str:
    """
    Rende la label concisa ma chiara:
    - Nome principale (o localname) + comune/area breve + bandiera
    - Evita descrizioni chilometriche tipo Zermatt se non necessario.
    """
    addr = item.get("address", {}) or {}
    name = item.get("name") or item.get("display_name", "").split(",")[0]
    # Preferisci nomi locali (es. Plateau Rosa) quando presenti
    localname = item.get("localname")
    if localname and len(localname) >= 3 and len(localname) <= 40:
        name = localname

    town = addr.get("town") or addr.get("city") or addr.get("village") or addr.get("municipality") or addr.get("county")
    region = addr.get("state") or addr.get("region")
    country = addr.get("country_code", "").upper()

    tail = None
    # stringa compatta tipo "Valtournenche (AO)" o "Aosta Valley"
    if town and region:
        # prendi solo la parte corta della regione se è lunga
        short_region = region.split()[:2]
        tail = f"{town}, {' '.join(short_region)}"
    elif town:
        tail = town
    elif region:
        tail = region

    flag = flag_emoji(country) if country else "🏳️"
    if tail:
        return f"{flag} {name} — {tail}"
    else:
        return f"{flag} {name}"

def fetch_elevation(lat: float, lon: float) -> int | None:
    """
    Altitudine via Open-Meteo Elevation API (metri s.l.m.).
    """
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": lat, "longitude": lon}, timeout=8)
        if r.ok:
            js = r.json()
            if js and "elevation" in js and isinstance(js["elevation"], list) and js["elevation"]:
                elev = js["elevation"][0]
                return int(round(float(elev)))
    except Exception:
        pass
    return None

# Search function per st_searchbox (viene richiamata automaticamente ad ogni carattere)
def nominatim_search_live(q: str):
    if not q or len(q) < 2:
        return []
    try:
        # Bias su località/peaks/stazioni sci note; addressdetails+namedetails per avere campi puliti
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q, "format": "json", "limit": 10, "addressdetails": 1,
                "namedetails": 1, "extratags": 1
            },
            headers={"User-Agent": "telemark-wax-app/1.1"},
            timeout=8
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        for item in r.json():
            try:
                lat = float(item.get("lat", 0)); lon = float(item.get("lon", 0))
                label_short = shorten_label_from_nominatim(item)

                elev = fetch_elevation(lat, lon)
                if elev is not None:
                    label_short = f"{label_short} · {elev} m"

                key = f"{label_short}|||{lat:.6f},{lon:.6f}"
                st.session_state._geo_map[key] = (lat, lon, label_short, elev)
                out.append(key)
            except Exception:
                continue
        return out
    except Exception:
        return []

# ------------------------ LOCATION (Meteoblue-like, concisa + altitudine) ------------------------
st.markdown("#### 1) Cerca località (con altitudine)")
selected = st_searchbox(
    nominatim_search_live,
    key="place",
    placeholder="Digita e scegli… (es. Plateau Rosa, Cervinia, Sestriere)",
    clear_on_submit=False,
    default=None
)

# decode selection -> lat,lon,label,elev
if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label, elev = st.session_state._geo_map.get(
        selected, (45.931, 7.709, "🏳️ Plateau Rosa — Valtournenche, AO · 3480 m", 3480)
    )
    st.session_state.sel_lat  = lat
    st.session_state.sel_lon  = lon
    st.session_state.sel_label= label
    st.session_state.sel_elev = elev

# Fallback default se non selezionato ancora
lat   = st.session_state.get("sel_lat", 45.831)
lon   = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "🇮🇹 Champoluc — Ayas, AO · 1568 m")
elev  = st.session_state.get("sel_elev", None)

colh = st.columns([1])[0]
with colh:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ WINDOWS A/B/C ------------------------
st.markdown("#### 2) Finestre orarie A · B · C (oggi)")
c1, c2, c3 = st.columns(3)
with c1:
    A_start = st.time_input("Inizio A", time(9, 0), key="A_s")
    A_end   = st.time_input("Fine A",   time(11, 0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", time(11, 0), key="B_s")
    B_end   = st.time_input("Fine B",   time(13, 0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", time(13, 0), key="C_s")
    C_end   = st.time_input("Fine C",   time(16, 0), key="C_e")

# ------------------------ DATA PIPELINE ------------------------
def fetch_open_meteo(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp  = row.precipitation
        rain = getattr(row, "rain", 0.0)
        snow = getattr(row, "snowfall", 0.0)
        if prp <= 0 or pd.isna(prp): return "none"
        if rain > 0 and snow > 0:   return "mixed"
        if snow > 0 and rain == 0:  return "snow"
        if rain > 0 and snow == 0:  return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])         # naive
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6).round(3)
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation","rain","snowfall","weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["td"] = df["dew_point_2m"].astype(float)
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
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])
    df["T_surf"] = T_surf; df["T_top5"] = T_top5; return df

def window_slice(res, s, e, tzname_auto: str):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname_auto), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname_auto)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ------------------------ WAX BANDS (8 marchi) ------------------------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("Ultra/Alpha Mix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Universal Cold",-12,-6), ("Universal Medium",-7,-2), ("Universal Soft",-5,0)]
START= [("SG Blue",-12,-6), ("SG Purple",-8,-2), ("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6), ("Violet",-8,-2), ("Red",-3,2)]
BRAND_BANDS = [
    ("Swix"      ,"https://upload.wikimedia.org/wikipedia/commons/2/2e/Swix_logo.svg", SWIX),
    ("Toko"      ,"https://upload.wikimedia.org/wikipedia/commons/1/13/Toko_logo.svg", TOKO),
    ("Vola"      ,"https://upload.wikimedia.org/wikipedia/commons/6/6f/Vola_Racing_logo.png", VOLA),
    ("Rode"      ,"https://www.rodewax.com/themes/rode/assets/img/rode.svg", RODE),
    ("Holmenkol" ,"https://upload.wikimedia.org/wikipedia/commons/8/8e/Holmenkol_logo.svg", HOLM),
    ("Maplus"    ,"https://www.briko-maplus.com/wp-content/uploads/2022/11/Logo-Maplus-1.svg", MAPL),
    ("Start"     ,"https://upload.wikimedia.org/wikipedia/commons/3/3c/Start_logo_red.svg", START),
    ("Skigo"     ,"https://www.skigo.se/wp-content/uploads/2020/08/skigo-logo.svg", SKIGO),
]

def pick(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

# ------------------------ STRUCTURE & EDGES (stile Wintersteiger) ------------------------
def tune_for(t_surf, discipline):
    """
    SIDE (gradi) + BASE (gradi) e famiglia struttura:
    - freddo secco: lineare fine
    - universale: incrociata (tipo "M")/leggera onda
    - caldo/umido: a V/diagonale marcata o chevron
    """
    if t_surf <= -10:
        fam = ("linear","Lineare fine (freddo/secco)")
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        fam = ("cross","Incrociata universale (M)")
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        fam = ("chevron","Chevron / V diagonale (umido/caldo)")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    """
    Preview “alla Wintersteiger”: base chiara + gole scure, ritmo/passo regolare.
    Pattern: linear, cross (M), V/diagonale, chevron (><).
    """
    fig = plt.figure(figsize=(3.8, 2.0), dpi=180)
    ax = plt.gca(); ax.set_facecolor("#e5e7eb")  # base soletta
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    groove = "#374151"

    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=groove, linewidth=2.4, solid_capstyle="round")
    elif kind == "cross":
        # due famiglie incrociate (passo diverso per rendere la M)
        for x in range(-10, 120, 9):
            ax.plot([x, x+60], [6, 54], color=groove, linewidth=2.1, alpha=0.95)
        for x in range(10, 110, 12):
            ax.plot([x, x-60], [6, 54], color=groove, linewidth=2.1, alpha=0.95)
    elif kind == "chevron":
        # pattern >< con vertice centrale
        for x in range(-10, 120, 10):
            ax.plot([x, 50], [6, 30], color=groove, linewidth=2.4, alpha=0.98)
            ax.plot([x, 50], [54, 30], color=groove, linewidth=2.4, alpha=0.98)
        # riga centrale per dare l'idea del “solco di scarico”
        ax.plot([50,50],[8,52], color=groove, linewidth=2.0, alpha=0.5)
    elif kind == "v":
        # variante solo diagonale a V (meno marcata)
        for x in range(-20, 120, 8):
            ax.plot([x, x+55], [6, 54], color=groove, linewidth=2.2, alpha=0.95)

    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

# ------------------------ RUN ------------------------
st.markdown("#### 3) Scarica dati meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js  = fetch_open_meteo(lat, lon)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)

        # Intestazione località + altitudine
        st.markdown(f"**Località selezionata:** {label}")

        st.dataframe(res, use_container_width=True)

        # grafici
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T_surf"); plt.plot(t,res["T_top5"],label="T_top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV risultato", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, s, e, js.get("timezone","Europe/Rome"))
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # wax cards 8 marchi (con loghi reali + fallback)
            cols = st.columns(4)
            cols2 = st.columns(4)
            for i,(brand,logo_url,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                with cols[i]:
                    try:
                        st.markdown(f"<div class='brand'>"
                                    f"<img src='{logo_url}' onerror=\"this.style.display='none'\" />"
                                    f"<div><div style='font-size:.8rem;color:{MUTED}'>{brand}</div>"
                                    f"<div style='font-weight:800;color:{ACCENT}'>{rec}</div></div></div>", unsafe_allow_html=True)
                    except:
                        st.markdown(f"<div class='brand'><div style='font-weight:800'>{brand}</div>"
                                    f"<div>{rec}</div></div>", unsafe_allow_html=True)
            for i,(brand,logo_url,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                with cols2[i]:
                    try:
                        st.markdown(f"<div class='brand'>"
                                    f"<img src='{logo_url}' onerror=\"this.style.display='none'\" />"
                                    f"<div><div style='font-size:.8rem;color:{MUTED}'>{brand}</div>"
                                    f"<div style='font-weight:800;color:{ACCENT}'>{rec}</div></div></div>", unsafe_allow_html=True)
                    except:
                        st.markdown(f"<div class='brand'><div style='font-weight:800'>{brand}</div>"
                                    f"<div>{rec}</div></div>", unsafe_allow_html=True)

            # Struttura consigliata + disegno stile Wintersteiger
            fam, side, base = tune_for(t_med, "GS")  # riferimento
            st.markdown(f"**Struttura consigliata:** {fam[1]}  ·  **Lamina SIDE:** {side:.1f}°  ·  **BASE:** {base:.1f}°")
            draw_structure(fam[0], fam[1])

            # Tuning per discipline
            disc = st.multiselect(f"Discipline (Blocco {L})", ["SL","GS","SG","DH"], default=["SL","GS"], key=f"disc_{L}")
            rows = []
            for d in disc:
                fam_d, side_d, base_d = tune_for(t_med, d)
                rows.append([d, fam_d[1], f"{side_d:.1f}°", f"{base_d:.1f}°"])
            if rows:
                st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura","Lamina SIDE (°)","Lamina BASE (°)"]))
    except Exception as e:
        st.error(f"Errore: {e}")
