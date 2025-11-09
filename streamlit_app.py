# telemark_pro_app.py
import streamlit as st
import pandas as pd
import requests, base64, math
import matplotlib.pyplot as plt
from datetime import time
from dateutil import tz
from streamlit_searchbox import st_searchbox  # live dropdown stile meteoblue

# ------------------------ PAGE ------------------------
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown("### Telemark · Pro Wax & Tune")
st.caption("Ricerca rapida tipo Meteoblue · Blocchi A/B/C · 8 marchi sciolina · Struttura + Angoli (SIDE)")

# ------------------------ UTILS ------------------------
def flag_emoji(country_code: str) -> str:
    try:
        cc = country_code.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def _short_label(addr: dict) -> tuple[str,str]:
    """Costruisce etichetta breve: Flag + 'Località, Regione (CC)' e ritorna anche (lat,lon)."""
    name = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") \
        or addr.get("municipality") or addr.get("county") or addr.get("state_district") \
        or addr.get("state") or addr.get("country", "Unknown")
    region = addr.get("state") or addr.get("province") or addr.get("county") or addr.get("region") or ""
    cc = (addr.get("country_code") or "").upper()
    short = name
    if region and region != name:
        # accorcia region a 2-3 sigle se possibile (es. Valais -> VS, Aosta Valley -> AO)
        short_region = region
        # micro mappa di abbreviations comuni senza librerie extra
        abbr = {
            "Valle d'Aosta": "AO", "Aosta Valley": "AO", "Valais": "VS", "Baden-Württemberg": "BW",
            "Piedmont": "PIE", "Lombardy": "LOM", "Trentino-Alto Adige": "TAA", "Tyrol": "TIR"
        }
        short_region = abbr.get(region, region)
        short = f"{name}, {short_region}"
    tail = f" ({cc})" if cc else ""
    label = f"{flag_emoji(cc)}  {short}{tail}"
    return label

# Search function (richiamata a ogni tasto, niente Enter)
def nominatim_search(text: str):
    if not text or len(text) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": text, "format": "json", "limit": 10, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=8
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        seen = set()
        for item in r.json():
            addr = (item.get("address") or {})
            label = _short_label(addr)
            lat = float(item.get("lat", 0)); lon = float(item.get("lon", 0))
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            if key in seen:  # evita duplicati in dropdown
                continue
            seen.add(key)
            st.session_state._geo_map[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

# ------------------------ 1) LOCALITÀ ------------------------
st.subheader("1) Cerca località")
selected = st_searchbox(
    nominatim_search,
    key="place",
    placeholder="Digita e scegli… (es. Champoluc, Zermatt, Cervinia)",
    clear_on_submit=False,
    default=None,
)

# decode selection -> lat,lon,label (fallback Champoluc)
if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc, AO (IT)"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc, AO (IT)")

coltz, colh = st.columns([1,2])
with coltz:
    tzname = st.selectbox("Timezone", ["Europe/Rome", "UTC"], index=0)
with colh:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ 2) FINESTRE A/B/C ------------------------
st.subheader("2) Finestre orarie A · B · C (oggi)")
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

# ------------------------ METEO PIPELINE ------------------------
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

# ------------------------ WAX (8 marchi) ------------------------
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

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ STRUTTURE & ANGOLI ------------------------
STRUCT_OPTIONS = {
    "Lineare fine (freddo/secco)": "linear",
    "Incrociata (universale)": "cross",
    "Scarico a V / diagonale (umido)": "V",
    "Onda convessa (universale)": "wave",
}
def _auto_family(t_surf: float, discipline: str):
    if t_surf <= -10:
        fam = ("Lineare fine (freddo/secco)", "linear")
        base = 0.5; side_map = {"SL":88.5, "GS":88.0, "SG":87.5, "DH":87.5}
    elif t_surf <= -3:
        fam = ("Incrociata (universale)", "cross")
        base = 0.7; side_map = {"SL":88.0, "GS":88.0, "SG":87.5, "DH":87.0}
    else:
        fam = ("Scarico a V / diagonale (umido)", "V")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL":88.0, "GS":87.5, "SG":87.0, "DH":87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    """Preview essenziale ispirata a schemi Wintersteiger (senza dipendenze extra)."""
    fig = plt.figure(figsize=(3.4, 2.0), dpi=180)
    ax = plt.gca(); ax.set_facecolor("#d9d9d9")
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis('off')
    color = "#2b2b2b"
    # tracce un po' più realistiche
    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=color, linewidth=2.6, solid_capstyle="round")
    elif kind == "cross":
        for x in range(-10, 120, 10):
            ax.plot([x, x+50], [6, 54], color=color, linewidth=2.2, alpha=0.95)
        for x in range(10, 110, 10):
            ax.plot([x, x-50], [6, 54], color=color, linewidth=2.2, alpha=0.95)
    elif kind == "V":
        for x in range(-10, 120, 8):
            ax.plot([x, 50], [6, 30], color=color, linewidth=2.6, alpha=0.95)
            ax.plot([x, 50], [54, 30], color=color, linewidth=2.6, alpha=0.95)
    elif kind == "wave":
        # 9 colonne di archi sinusoidali
        for xi in range(8, 98, 10):
            yvals = []
            xvals = []
            for i in range(0, 60):
                t = (i / 59.0) * math.pi  # 0..pi
                y = 30 + 20*math.sin(t)
                xvals.append(xi)
                yvals.append(y)
            ax.plot(xvals, yvals, color=color, linewidth=2.4, solid_capstyle="round")
    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

# ------------------------ 3) RUN ------------------------
st.subheader("3) Scarica meteo & calcola")
go = st.button("Scarica previsioni per la località selezionata", type="primary")

if go:
    try:
        js = fetch_open_meteo(lat, lon, tzname)
        src = build_df(js, hours)
        res = compute_snow_temperature(src, dt_hours=1.0)
        st.success(f"Dati per **{label}** caricati.")
        st.dataframe(res, use_container_width=True)

        # grafici rapidi
        t = pd.to_datetime(res["time"])
        fig1 = plt.figure(); plt.plot(t,res["T2m"],label="T2m"); plt.plot(t,res["T_surf"],label="T_surf"); plt.plot(t,res["T_top5"],label="T_top5")
        plt.legend(); plt.title("Temperature"); plt.xlabel("Ora"); plt.ylabel("°C"); st.pyplot(fig1)
        fig2 = plt.figure(); plt.bar(t,res["prp_mmph"]); plt.title("Precipitazione (mm/h)"); plt.xlabel("Ora"); plt.ylabel("mm/h"); st.pyplot(fig2)
        st.download_button("Scarica CSV", data=res.to_csv(index=False), file_name="forecast_with_snowT.csv", mime="text/csv")

        # blocchi A/B/C
        for L,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, tzname, s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # 8 marchi – due righe da 4
            cols = st.columns(4); cols2 = st.columns(4)
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[:4]):
                rec = pick(bands, t_med)
                cols[i].markdown(
                    f"<div style='display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid #e5e7eb;border-radius:12px'>"
                    f"<img src='{logo_badge(brand.upper(), col)}' style='height:22px'/>"
                    f"<div><div style='font-size:.8rem;opacity:.7'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )
            for i,(brand,col,bands) in enumerate(BRAND_BANDS[4:]):
                rec = pick(bands, t_med)
                cols2[i].markdown(
                    f"<div style='display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid #e5e7eb;border-radius:12px'>"
                    f"<img src='{logo_badge(brand.upper(), col)}' style='height:22px'/>"
                    f"<div><div style='font-size:.8rem;opacity:.7'>{brand}</div>"
                    f"<div style='font-weight:800'>{rec}</div></div></div>", unsafe_allow_html=True
                )

            # —— TOGGLE AUTO/MANUALE PER STRUTTURA ——
            col_auto, col_disc = st.columns([1,1])
            with col_auto:
                auto = st.toggle(f"Struttura: Auto (consigliata) – Blocco {L}", value=True, key=f"auto_{L}")
            with col_disc:
                disc = st.selectbox(f"Disciplina (Blocco {L})", ["SL","GS","SG","DH"], index=1, key=f"disc_{L}")

            if auto:
                fam, side, base = _auto_family(t_med, disc)
                title, kind = fam[0], fam[1]
            else:
                manual_choice = st.selectbox(
                    f"Scegli impronta manuale (Blocco {L})",
                    list(STRUCT_OPTIONS.keys()),
                    index=1, key=f"man_{L}"
                )
                kind = STRUCT_OPTIONS[manual_choice]
                title = manual_choice
                # angoli indicativi se manuale: mantieni quelli della disciplina auto per coerenza
                _, side, base = _auto_family(t_med, disc)

            st.markdown(f"**Impronta:** {title}  ·  **Lamina SIDE:** {side:.1f}°  ·  **BASE:** {base:.1f}°")
            draw_structure(kind, title)

    except Exception as e:
        st.error(f"Errore: {e}")
