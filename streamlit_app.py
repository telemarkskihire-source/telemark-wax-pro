# telemark_pro_app.py
# — Telemark · Pro Wax & Tune (ricerca “meteoblue”, strutture stile Wintersteiger, preset macchina)

import math, base64, requests
from datetime import time

import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from dateutil import tz

# ---- prova a usare streamlit-searchbox; se manca, fallback su text_input ----
try:
    from streamlit_searchbox import st_searchbox  # pip: streamlit-searchbox
    HAVE_SEARCHBOX = True
except Exception:
    HAVE_SEARCHBOX = False

# ------------------------ THEME (white app, elementi evidenti) ------------------------
PRIMARY = "#10bfcf"
ACCENT  = "#0ea5e9"
DARKTXT = "#0f172a"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(
    """
    <style>
      .brand {display:flex;gap:10px;align-items:center;padding:8px 10px;border-radius:12px;
              background:#f8fafc;border:1px solid #e2e8f0}
      .brand img{height:22px}
      .badge {display:inline-block;border:1px solid #e2e8f0;padding:6px 10px;border-radius:999px;
              font-size:.78rem;color:#334155;background:#f8fafc}
      .card  {background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:14px}
      .kpi   {display:flex;gap:8px;align-items:center;background:rgba(16,191,207,.06);
              border:1px dashed rgba(16,191,207,.45);padding:10px 12px;border-radius:12px}
      .kpi .lab{font-size:.78rem;color:#64748b}
      .kpi .val{font-size:1rem;font-weight:800;color:#0f172a}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("### Telemark · Pro Wax & Tune")
st.markdown(
    "<span class='badge'>Ricerca tipo Meteoblue · Blocchi A/B/C · Sciolina · Struttura · Angoli (SIDE) · Preset macchina</span>",
    unsafe_allow_html=True,
)

# ------------------------ UTILS ------------------------
def flag_emoji(cc: str) -> str:
    try:
        cc = (cc or "").upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"

def _compact_label(item: dict) -> str:
    """Compatta display_name in 'Città, Regione, Paese' + bandierina."""
    name = item.get("display_name", "")
    parts = name.split(",")
    parts = [p.strip() for p in parts]
    short = ", ".join(parts[:3]) if len(parts) >= 3 else name
    cc = (item.get("address", {}) or {}).get("country_code", "") or ""
    return f"{flag_emoji(cc)}  {short}"

def nominatim_search(query: str):
    if not query or len(query) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 12, "addressdetails": 1},
            headers={"User-Agent": "telemark-wax-app/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        out = []
        st.session_state._geo_map = {}
        for it in r.json():
            lat = float(it.get("lat", 0))
            lon = float(it.get("lon", 0))
            label = _compact_label(it)
            key = f"{label}|||{lat:.6f},{lon:.6f}"
            st.session_state._geo_map[key] = (lat, lon, label)
            out.append(key)
        return out
    except Exception:
        return []

# ------------------------ LOCATION ------------------------
st.markdown("#### 1) Cerca località")
if HAVE_SEARCHBOX:
    selected = st_searchbox(
        nominatim_search,
        key="place",
        placeholder="Digita e scegli… (es. Champoluc, Cervinia, Sestriere)",
        clear_on_submit=False,
        default=None,
    )
else:
    # Fallback se il pacchetto non è disponibile
    st.info("Suggerimenti live non disponibili (manca `streamlit-searchbox`). Usiamo una ricerca semplice.")
    q = st.text_input("Località (scrivi città, Paese)", "Champoluc, Aosta, Italia")
    # se premi invio, prova a cercare una singola soluzione
    selected = None
    if q.strip():
        res = nominatim_search(q.strip())
        selected = res[0] if res else None

if selected and "|||" in selected and "_geo_map" in st.session_state:
    lat, lon, label = st.session_state._geo_map.get(selected, (45.831, 7.730, "Champoluc (Ramey)"))
    st.session_state.sel_lat, st.session_state.sel_lon, st.session_state.sel_label = lat, lon, label

lat = st.session_state.get("sel_lat", 45.831)
lon = st.session_state.get("sel_lon", 7.730)
label = st.session_state.get("sel_label", "Champoluc (Ramey)")

coltz, colh = st.columns([1, 2])
with coltz:
    tzname = st.selectbox("Timezone", ["Europe/Rome", "UTC"], index=0)
with colh:
    hours = st.slider("Ore previsione", 12, 168, 72, 12)

# ------------------------ A/B/C windows ------------------------
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

# ------------------------ Meteo & fisica neve ------------------------
def fetch_open_meteo(lat, lon, timezone_str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone_str,
        "hourly": "temperature_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,is_day,weathercode",
        "forecast_days": 7,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def _prp_type(df):
    snow_codes = {71, 73, 75, 77, 85, 86}
    rain_codes = {51, 53, 55, 61, 63, 65, 80, 81, 82}

    def f(row):
        prp = row.precipitation
        rain = getattr(row, "rain", 0.0)
        snow = getattr(row, "snowfall", 0.0)
        if prp <= 0 or pd.isna(prp):
            return "none"
        if rain > 0 and snow > 0:
            return "mixed"
        if snow > 0 and rain == 0:
            return "snow"
        if rain > 0 and snow == 0:
            return "rain"
        code = int(getattr(row, "weathercode", 0)) if pd.notna(getattr(row, "weathercode", None)) else 0
        if code in snow_codes:
            return "snow"
        if code in rain_codes:
            return "rain"
        return "mixed"

    return df.apply(f, axis=1)

def build_df(js, hours):
    h = js["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now().floor("H")
    df = df[df["time"] >= now0].head(hours).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["T2m"] = df["temperature_2m"].astype(float)
    out["cloud"] = (df["cloudcover"].astype(float) / 100).clip(0, 1)
    out["wind"] = (df["windspeed_10m"].astype(float) / 3.6).round(3)
    out["sunup"] = df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    extra = df[["precipitation", "rain", "snowfall", "weathercode"]].copy()
    out["prp_type"] = _prp_type(extra)
    out["td"] = df["dew_point_2m"].astype(float)
    return out

def compute_snow_temperature(df, dt_hours=1.0):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    rain = df["prp_type"].str.lower().isin(["rain", "mixed"])
    snow = df["prp_type"].str.lower().eq("snow")
    sunup = df["sunup"].astype(int) == 1
    tw = (df["T2m"] + df["td"]) / 2.0

    wet = (
        rain
        | (df["T2m"] > 0)
        | (sunup & (df["cloud"] < 0.3) & (df["T2m"] >= -3))
        | (snow & (df["T2m"] >= -1))
        | (snow & tw.ge(-0.5).fillna(False))
    )

    T_surf = pd.Series(index=df.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - df["cloud"]).clip(0, 1)
    windc = df["wind"].clip(upper=6.0)
    drad = (1.5 + 3.0 * clear - 0.3 * windc).clip(0.5, 4.5)
    T_surf.loc[dry] = df["T2m"][dry] - drad[dry]

    sunny_cold = sunup & dry & df["T2m"].between(-10, 0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat(
        [
            (df["T2m"] + 0.5 * (1.0 - df["cloud"]))[sunny_cold],
            pd.Series(-0.5, index=df.index)[sunny_cold],
        ],
        axis=1,
    ).min(axis=1)

    T_top5 = pd.Series(index=df.index, dtype=float)
    tau = pd.Series(6.0, index=df.index, dtype=float)
    tau.loc[rain | snow | (df["wind"] >= 6)] = 3.0
    tau.loc[(~sunup) & (df["wind"] < 2) & (df["cloud"] < 0.3)] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(df) > 0:
        T_top5.iloc[0] = min(df["T2m"].iloc[0], 0.0)
        for i in range(1, len(df)):
            T_top5.iloc[i] = T_top5.iloc[i - 1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i - 1])

    df["T_surf"] = T_surf
    df["T_top5"] = T_top5
    return df

def window_slice(res, tzname, s, e):
    t = pd.to_datetime(res["time"]).dt.tz_localize(tz.gettz(tzname), nonexistent="shift_forward", ambiguous="NaT")
    D = res.copy()
    D["dt"] = t
    today = pd.Timestamp.now(tz=tz.gettz(tzname)).date()
    W = D[(D["dt"].dt.date == today) & (D["dt"].dt.time >= s) & (D["dt"].dt.time <= e)]
    return W if not W.empty else D.head(7)

# ------------------------ WAX BRANDS ------------------------
SWIX = [("PS5 Turquoise", -18, -10), ("PS6 Blue", -12, -6), ("PS7 Violet", -8, -2), ("PS8 Red", -4, 4), ("PS10 Yellow", 0, 10)]
TOKO = [("Blue", -30, -9), ("Red", -12, -4), ("Yellow", -6, 0)]
VOLA = [("MX-E Blue", -25, -10), ("MX-E Violet", -12, -4), ("MX-E Red", -5, 0), ("MX-E Yellow", -2, 6)]
RODE = [("R20 Blue", -18, -8), ("R30 Violet", -10, -3), ("R40 Red", -5, 0), ("R50 Yellow", -1, 10)]
HOLM = [("Ultra/Alpha Mix Blue", -20, -8), ("BetaMix Red", -14, -4), ("AlphaMix Yellow", -4, 5)]
MAPL = [("Universal Cold", -12, -6), ("Universal Medium", -7, -2), ("Universal Soft", -5, 0)]
START = [("SG Blue", -12, -6), ("SG Purple", -8, -2), ("SG Red", -3, 7)]
SKIGO = [("Blue", -12, -6), ("Violet", -8, -2), ("Red", -3, 2)]
BRAND_BANDS = [
    ("Swix", "#ef4444", SWIX),
    ("Toko", "#f59e0b", TOKO),
    ("Vola", "#3b82f6", VOLA),
    ("Rode", "#22c55e", RODE),
    ("Holmenkol", "#06b6d4", HOLM),
    ("Maplus", "#f97316", MAPL),
    ("Start", "#eab308", START),
    ("Skigo", "#a855f7", SKIGO),
]

def pick(bands, t):
    for n, tmin, tmax in bands:
        if t >= tmin and t <= tmax:
            return n
    return bands[-1][0] if t > bands[-1][2] else bands[0][0]

def logo_badge(text, color):
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='36'><rect width='160' height='36' rx='6' fill='{color}'/><text x='12' y='24' font-size='16' font-weight='700' fill='white'>{text}</text></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

# ------------------------ STRUTTURE & ANGOLI ------------------------
# famiglie “alla Wintersteiger”: linear, cross, V, wave
def tune_for(t_surf, discipline):
    if t_surf <= -10:
        fam = ("linear", "Lineare fine (freddo/secco)")
        base = 0.5
        side_map = {"SL": 88.5, "GS": 88.0, "SG": 87.5, "DH": 87.5}
    elif t_surf <= -3:
        fam = ("cross", "Incrociata (universale freddo)")
        base = 0.7
        side_map = {"SL": 88.0, "GS": 88.0, "SG": 87.5, "DH": 87.0}
    else:
        fam = ("V", "Scarico a V / diagonale (umido/caldo)")
        base = 0.8 if t_surf <= 0.5 else 1.0
        side_map = {"SL": 88.0, "GS": 87.5, "SG": 87.0, "DH": 87.0}
    return fam, side_map.get(discipline, 88.0), base

def draw_structure(kind: str, title: str):
    fig = plt.figure(figsize=(3.6, 2.2), dpi=190)
    ax = plt.gca()
    ax.set_facecolor("#d9d9db")  # “soletta” chiara
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.axis("off")
    color = "#2b2b2b"

    if kind == "linear":
        for x in range(8, 98, 5):
            ax.plot([x, x], [6, 54], color=color, linewidth=2.6, solid_capstyle="round")
    elif kind == "cross":
        for x in range(-10, 120, 10):
            ax.plot([x, x + 50], [6, 54], color=color, linewidth=2.2, alpha=0.95)
        for x in range(10, 110, 10):
            ax.plot([x, x - 50], [6, 54], color=color, linewidth=2.2, alpha=0.95)
    elif kind == "V":
        for x in range(-10, 120, 8):
            ax.plot([x, 50], [6, 30], color=color, linewidth=2.6, alpha=0.95)
            ax.plot([x, 50], [54, 30], color=color, linewidth=2.6, alpha=0.95)
    elif kind == "wave":
        import numpy as np
        xs = np.linspace(8, 92, 8)
        for x in xs:
            yy = 30 + 18 * np.sin(np.linspace(-math.pi, math.pi, 60))
            ax.plot(np.full_like(yy, x), yy, color=color, linewidth=2.4, solid_capstyle="round")

    ax.set_title(title, fontsize=10, pad=4)
    st.pyplot(fig)

# Preset macchina (indicativi) per struttura & T_surf
# valori generici: pressione (bar), avanzamento nastro (m/min), profondità (µm)
def machine_preset(kind: str, t_surf: float):
    if t_surf <= -10:
        temp = "Freddo/molto secco"
        mod = dict(pressure=0.18, feed=3.0, depth=4)
    elif t_surf <= -3:
        temp = "Freddo"
        mod = dict(pressure=0.26, feed=4.0, depth=6)
    else:
        temp = "Umido/caldo"
        mod = dict(pressure=0.36, feed=5.5, depth=8)
    # aggiusta in base alla famiglia
    if kind == "linear":
        mod["depth"] = max(3, mod["depth"] - 2)
        mod["feed"] -= 0.5
    elif kind == "V":
        mod["pressure"] += 0.05
    elif kind == "wave":
        mod["pressure"] = max(0.2, mod["pressure"] - 0.05)
        mod["feed"] -= 0.3
    return temp, mod

# ------------------------ RUN ------------------------
st.markdown("#### 3) Scarica dati meteo & calcola")
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
        fig1 = plt.figure()
        plt.plot(t, res["T2m"], label="T2m")
        plt.plot(t, res["T_surf"], label="T_surf")
        plt.plot(t, res["T_top5"], label="T_top5")
        plt.legend()
        plt.title("Temperature")
        plt.xlabel("Ora")
        plt.ylabel("°C")
        st.pyplot(fig1)

        fig2 = plt.figure()
        plt.bar(t, res["prp_mmph"])
        plt.title("Precipitazione (mm/h)")
        plt.xlabel("Ora")
        plt.ylabel("mm/h")
        st.pyplot(fig2)

        st.download_button(
            "Scarica CSV risultato",
            data=res.to_csv(index=False),
            file_name="forecast_with_snowT.csv",
            mime="text/csv",
        )

        # --- blocchi A/B/C ---
        blocks = {"A": (A_start, A_end), "B": (B_start, B_end), "C": (C_start, C_end)}
        for L, (s, e) in blocks.items():
            st.markdown(f"### Blocco {L}")
            W = window_slice(res, tzname, s, e)
            t_med = float(W["T_surf"].mean())
            st.markdown(f"**T_surf medio {L}: {t_med:.1f}°C**")

            # toggle Auto/Manuale – nessuna assegnazione diretta a session_state
            auto = st.toggle(f"Struttura Auto (in base a T_surf) – Blocco {L}", value=True, key=f"auto_toggle_{L}")
            manual_choice = None
            if not auto:
                manual_choice = st.selectbox(
                    f"Struttura manuale – Blocco {L}",
                    [
                        ("linear", "Lineare fine"),
                        ("cross", "Incrociata"),
                        ("V", "Scarico a V/diagonale"),
                        ("wave", "Onda fredda"),
                    ],
                    index=0,
                    key=f"manual_struct_{L}",
                    format_func=lambda x: x[1],
                )

            # Wax cards (8 marchi)
            cols = st.columns(4)
            cols2 = st.columns(4)
            for i, (brand, col, bands) in enumerate(BRAND_BANDS[:4]):
                cols[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                    f"<div style='font-weight:800'>{pick(bands, t_med)}</div></div></div>",
                    unsafe_allow_html=True,
                )
            for i, (brand, col, bands) in enumerate(BRAND_BANDS[4:]):
                cols2[i].markdown(
                    f"<div class='brand'><img src='{logo_badge(brand.upper(), col)}'/>"
                    f"<div><div style='font-size:.8rem;opacity:.85'>{brand}</div>"
                    f"<div style='font-weight:800'>{pick(bands, t_med)}</div></div></div>",
                    unsafe_allow_html=True,
                )

            # struttura + angoli
            fam, side, base = tune_for(t_med, "GS")
            if auto:
                kind, title = fam
            else:
                kind, title = manual_choice

            st.markdown(f"**Struttura consigliata:** {title}  ·  **Lamina SIDE:** {side:.1f}°  ·  **BASE:** {base:.1f}°")
            draw_structure(kind, title)

            # preset macchina (pressione/avanzamento/profondità)
            temp_lbl, mod = machine_preset(kind, t_med)
            cpm1, cpm2, cpm3 = st.columns(3)
            cpm1.markdown(f"<div class='kpi'><span class='lab'>Condizione</span><span class='val'>{temp_lbl}</span></div>", unsafe_allow_html=True)
            cpm2.markdown(f"<div class='kpi'><span class='lab'>Pressione</span><span class='val'>{mod['pressure']:.2f} bar</span></div>", unsafe_allow_html=True)
            cpm3.markdown(f"<div class='kpi'><span class='lab'>Avanzamento / Prof.</span><span class='val'>{mod['feed']:.1f} m/min · {mod['depth']} µm</span></div>", unsafe_allow_html=True)

            # Tuning discipline
            disc = st.multiselect(f"Discipline (Blocco {L})", ["SL", "GS", "SG", "DH"], default=["SL", "GS"], key=f"disc_{L}")
            rows = []
            for d in disc:
                fam_d, side_d, base_d = tune_for(t_med, d)
                rows.append([d, fam_d[1], f"{side_d:.1f}°", f"{base_d:.1f}°"])
            if rows:
                st.table(pd.DataFrame(rows, columns=["Disciplina", "Struttura", "Lamina SIDE (°)", "Lamina BASE (°)"]))

    except Exception as e:
        st.error(f"Errore: {e}")
