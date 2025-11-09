# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox

# ---------- UI THEME (light, elementi in evidenza) ----------
PRIMARY = "#0ea5e9"   # azzurro evidenza
ACCENT  = "#0ea5e9"
TEXT    = "#0f172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(
f"""
<style>
:root {{
  --primary: {PRIMARY};
}}
h1,h2,h3,h4,h5, label, p, span, div {{ color:{TEXT}; }}
.badge {{
  display:inline-block; border:1px solid #e5e7eb; padding:6px 10px; border-radius:999px;
  font-size:.78rem; background:#f8fafc; color:#334155;
}}
.brand {{ display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:12px;
         background:#f8fafc; border:1px solid #e5e7eb; }}
.brand img {{ height:22px; }}
hr {{ border:0; border-top:1px solid #e5e7eb; margin:4px 0 14px 0; }}
</style>
""",
unsafe_allow_html=True,
)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown("<span class='badge'>Ricerca tipo Meteoblue · Blocchi A/B/C · 8 marchi · Strutture Wintersteiger · Angoli SIDE/BASE</span>", unsafe_allow_html=True)

# ---------- Helpers ----------
def flag_emoji(cc: str) -> str:
    try:
        cc = (cc or "").upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def short_label_from_nominatim(item: dict) -> str:
    """Costruisce etichetta corta: 'Città, Regione (CC)'."""
    addr = item.get("address", {}) or {}
    name = addr.get("city") or addr.get("town") or addr.get("village") or item.get("display_name","").split(",")[0]
    region = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    pieces = [p for p in [name, region] if p]
    label = ", ".join(pieces[:2])
    return f"{flag_emoji(cc)}  {label} ({cc})"

# ricerca live (senza Enter)
def nominatim_search(q: str):
    if not q or len(q) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 10, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        st.session_state._geo_map = {}
        out = []
        for item in r.json():
            label = short_label_from_nominatim(item)
            lat = float(item.get("lat", 0.0)); lon = float(item.get("lon", 0.0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_map[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

# ---------- Sezione 1: Località ----------
st.markdown("#### 1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (es. Champoluc, Cervinia, Sestriere)",
    clear_on_submit=False,
)

# applica selezione se c'è
if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

lat   = st.session_state.get("sel_lat", 45.831)
lon   = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc, Aosta (IT)")

coltz, colh = st.columns([1,2])
with coltz:
    tzname = st.selectbox("Timezone", ["Europe/Rome", "UTC"], index=0)
with colh:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ---------- Sezione 2: Finestre orarie ----------
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

# ---------- Meteo + calcolo ----------
@st.cache_data(show_spinner=False)
def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": timezone_str,
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30); r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71,73,75,77,85,86}
    rain_codes = {51,53,55,61,63,65,80,81,82}
    def f(row):
        prp = row.precipitation; rain = getattr(row,"rain",0.0); snow = getattr(row,"snowfall",0.0)
        if prp<=0 or pd.isna(prp): return "none"
        if rain>0 and snow>0: return "mixed"
        if snow>0 and not rain: return "snow"
        if rain>0 and not snow: return "rain"
        code = int(getattr(row,"weathercode",0)) if pd.notna(getattr(row,"weathercode",None)) else 0
        if code in snow_codes: return "snow"
        if code in rain_codes: return "rain"
        return "mixed"
    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
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

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent='shift_forward', ambiguous='NaT')
    D = res.copy(); D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date==today) & (D["dt"].dt.time>=s) & (D["dt"].dt.time<=e)]
    return W if not W.empty else D.head(7)

# ---------- Wax bands (8 marchi) ----------
SWIX = [("PS5 Turquoise", -18,-10), ("PS6 Blue",-12,-6), ("PS7 Violet",-8,-2), ("PS8 Red",-4,4), ("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9), ("Red",-12,-4), ("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10), ("MX-E Violet",-12,-4), ("MX-E Red",-5,0), ("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8), ("R30 Violet",-10,-3), ("R40 Red",-5,0), ("R50 Yellow",-1,10)]
HOLM = [("Ultra/Alpha Mix Blue",-20,-8), ("BetaMix Red",-14,-4), ("AlphaMix Yellow",-4,5)]
MAPL = [("Universal Cold",-12,-6), ("Universal Medium",-7,-2), ("Universal Soft",-5,0)]
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

# ---------- Strutture & Angoli ----------
# famiglie "alla Wintersteiger": lineare, incrociata (cross), V (chevron), diagonale, onda (convessa)
STRUCT_NAMES = {
    "linear":   "Lineare fine (freddo/secco)",
    "cross":    "Incrociata / Universale",
    "V":        "Scarico a V / Chevron (umido)",
    "diagonal": "Scarico diagonale",
    "wave":     "Onda convessa",
}

def recommended_family(t_surf):
    if t_surf <= -10: return "linear"
    if t_surf <= -3:  return "cross"
    return "V"

def tune_for(t_surf, discipline):
    fam = recommended_family(t_surf)
    # angoli SIDE in gradi (numerazione “88.0°”)
    if fam == "linear":
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif fam == "cross":
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:  # V / caldo
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    # base chiara + gole scure, proporzioni realistiche
    fig = plt.figure(figsize=(3.5, 2.0), dpi=180)
    ax = plt.gca(); ax.set_facecolor("#e5e7eb")
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    col = "#111827"
    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=col, linewidth=2.6, solid_capstyle="round")
    elif kind == "cross":
        for x in range(-10, 120, 10):
            ax.plot([x, x+50], [6, 54], color=col, linewidth=2.2, alpha=0.95)
        for x in range(10, 110, 10):
            ax.plot([x, x-50], [6, 54], color=col, linewidth=2.2, alpha=0.95)
    elif kind == "V":
        for x in range(-10, 120, 8):
            ax.plot([x, 50], [6, 30], color=col, linewidth=2.4, alpha=0.95)
            ax.plot([x, 50], [54, 30], color=col, linewidth=2.4, alpha=0.95)
    elif kind == "diagonal":
        for x in range(-20, 120, 8):
            ax.plot([x, x+50], [6, 54], color=col, linewidth=2.8, solid_capstyle="round")
    elif kind == "wave":
        import numpy as np
        xs = np.linspace(5, 95, 9)
        for x in xs:
            yy = 30 + 18*np.sin(np.linspace(-math.pi, math.pi, 70))
            ax.plot(np.full_like(yy, x), yy, color=col, linewidth=2.4, solid_capstyle="round")
    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ---------- Sezione 3: Calcolo ----------
st.markdown("#### 3) Scarica dati & calcola")
if st.button("Scarica previsioni per la località selezionata", type="primary"):
    js = fetch_open_meteo(lat, lon, tzname)
    src = build_df(js, hours)
    res = compute_snow_temperature(src, dt_hours=1.0)
    st.session_state.res = res
    st.success(f"Dati per **{label}** caricati.")

# usa i dati in sessione (così il toggle non rifà il download)
res = st.session_state.get("res")

if res is not None:
    # Preview rapida
    with st.expander("Anteprima dati (CSV)"):
        st.dataframe(res, use_container_width=True)
        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

    # blocchi A/B/C
    for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
        st.markdown(f"### Blocco {L}")
        W = window_slice(res, tzname, s, e)
        t_med = float(W["T_surf"].mean())
        st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

        # 8 marchi (due righe)
        cols = st.columns(4); cols2 = st.columns(4)
        for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
            rec = pick(bands, t_med)
            cols[i].markdown(
                f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
            )
        for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
            rec = pick(bands, t_med)
            cols2[i].markdown(
                f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
            )

        st.markdown("---")

        # Toggle Auto / Manuale (switch non rifà il download perché usiamo session_state.res)
        cauto, csel, cdisc = st.columns([1,1.2,1.4])
        with cauto:
            auto = st.toggle("Auto struttura", value=st.session_state.get(f"auto_{L}", True), key=f"auto_{L}")
            st.session_state[f"auto_{L}"] = auto

        with csel:
            if auto:
                fam_key = recommended_family(t_med)
            else:
                fam_key = st.selectbox(
                    "Struttura manuale",
                    list(STRUCT_NAMES.keys()),
                    format_func=lambda k: STRUCT_NAMES[k],
                    index=list(STRUCT_NAMES.keys()).index(st.session_state.get(f"fam_{L}", "linear")),
                    key=f"fam_sel_{L}",
                )
                st.session_state[f"fam_{L}"] = fam_key

        # Angoli + disegno
        fam_auto, side_ref, base_ref = tune_for(t_med, "GS")
        family_to_draw = fam_key if not auto else fam_auto
        st.markdown(f"**Struttura:** {STRUCT_NAMES[family_to_draw]}  ·  **Lamina SIDE (GS):** {side_ref:.1f}°  ·  **BASE:** {base_ref:.1f}°")
        draw_structure(family_to_draw, STRUCT_NAMES[family_to_draw])

        # Per disciplina
        with cdisc:
            disc = st.multiselect(f"Discipline (Blocco {L})", ["SL","GS","SG","DH"], default=["SL","GS"], key=f"disc_{L}")
        rows = []
        for d in disc:
            fam_d, side_d, base_d = tune_for(t_med, d)
            # se manuale manteniamo SOLO il disegno, non forziamo angoli (lasciamo consigli automatici per disciplina)
            rows.append([d, STRUCT_NAMES[fam_d], f"{side_d:.1f}°", f"{base_d:.1f}°"])
        if rows:
            st.table(pd.DataFrame(rows, columns=["Disciplina","Struttura consigliata","Lamina SIDE (°)","Lamina BASE (°)"]))
else:
    st.info("Carica i dati meteo con il pulsante qui sopra.")
