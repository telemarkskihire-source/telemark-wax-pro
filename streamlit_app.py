# telemark_pro_app.py
# -------------------
# Telemark · Pro Wax & Tune (tema scuro, nazione prefiltrata, algoritmo neve migliorato)
import os, math, base64, requests, pandas as pd
import streamlit as st
from datetime import datetime, date, time, timedelta, timezone
from dateutil import tz
from streamlit_searchbox import st_searchbox

# =============== Tema & stile (dark) ===============
PRIMARY = "#06b6d4"   # turchese acceso
ACCENT  = "#f97316"   # arancione evidenza
OK      = "#10b981"
WARN    = "#f59e0b"
ERR     = "#ef4444"

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{
  --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937;
}}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: 1rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing: .2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{
  display:inline-flex; align-items:center; gap:.5rem;
  background:#0b1220; border:1px solid #203045; color:#cce7f2;
  border-radius:12px; padding:.35rem .6rem; font-size:.85rem;
}}
.card {{
  background: var(--panel); border:1px solid var(--line);
  border-radius:12px; padding: .9rem .95rem;
}}
.kpi {{ display:flex; gap:.75rem; align-items:center; }}
.kpi .v {{ font-weight:800; font-size:1.1rem }}
.kpi.ok .v {{ color:{OK}; }} .kpi.warn .v {{ color:{WARN}; }}
.kpi.err .v {{ color:{ERR}; }}
.brand {{
  display:flex; align-items:center; gap:.65rem; background:#0e141d;
  border:1px solid #1e2a3a; border-radius:10px; padding:.45rem .6rem;
}}
.brand img {{ height:22px }}
.tbl table {{ border-collapse:collapse; width:100% }}
.tbl th, .tbl td {{ border-bottom:1px solid var(--line); padding:.5rem .6rem }}
.tbl th {{ color:#cbd5e1; font-weight:700; text-transform:uppercase; font-size:.78rem; letter-spacing:.06em }}
.banner {{
  border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0;
  padding:.75rem .9rem; border-radius:10px; font-size:.98rem;
}}
.btn-primary button {{
  background:{ACCENT} !important; color:#111 !important; font-weight:800 !important;
}}
.slider-tip {{ color:var(--muted); font-size:.85rem }}
a, .stMarkdown a {{ color:{PRIMARY} !important }}
.smallnote {{ color:#9aa4af; font-size:.78rem }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")
st.caption("Analisi meteo, temperatura neve, scorrevolezza e scioline – ottimizzato per blocchi A/B/C.")

# =============== Utils ===============
def flag(cc:str)->str:
    try:
        c=cc.upper(); return chr(127397+ord(c[0]))+chr(127397+ord(c[1]))
    except: return "🏳️"

def concise_label(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

# =============== Ricerca località con prefiltro Nazione ===============
COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}
colNA, colSB = st.columns([1,3])
with colNA:
    sel_country = st.selectbox("Nazione (prefiltro ricerca)", list(COUNTRIES.keys()), index=0)
    iso2 = COUNTRIES[sel_country]
with colSB:
    def nominatim_search(q:str):
        if not q or len(q)<2: return []
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q":q, "format":"json", "limit":12, "addressdetails":1, "countrycodes": iso2.lower()},
                headers={"User-Agent":"telemark-wax-pro/1.0"},
                timeout=8
            )
            r.raise_for_status()
            st.session_state._options = {}
            out=[]
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab = concise_label(addr, it.get("display_name",""))
                cc = addr.get("country_code","")
                lab = f"{flag(cc)}  {lab}"
                lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
                key = f"{lab}|||{lat:.6f},{lon:.6f}"
                st.session_state._options[key] = {"lat":lat,"lon":lon,"label":lab,"addr":addr}
                out.append(key)
            return out
        except:
            return []

    selected = st_searchbox(
        nominatim_search, key="place", placeholder="Cerca… es. Champoluc, Plateau Rosa",
        clear_on_submit=False, default=None
    )

# Altitudine
def get_elev(lat,lon):
    try:
        rr = requests.get("https://api.open-meteo.com/v1/elevation",
                          params={"latitude":lat, "longitude":lon}, timeout=8)
        rr.raise_for_status(); js = rr.json()
        return float(js["elevation"][0]) if js and "elevation" in js else None
    except: return None

lat = st.session_state.get("lat", 45.831); lon = st.session_state.get("lon", 7.730)
place_label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
if selected and "|||" in selected and "_options" in st.session_state:
    info = st.session_state._options.get(selected)
    if info:
        lat, lon, place_label = info["lat"], info["lon"], info["label"]
        st.session_state["lat"]=lat; st.session_state["lon"]=lon; st.session_state["place_label"]=place_label

elev = get_elev(lat,lon)
st.markdown(f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b></div>", unsafe_allow_html=True)

# =============== Giorno & blocchi (anche giorni successivi) ===============
cdate, chz = st.columns([1,1])
with cdate:
    target_day: date = st.date_input("Giorno di riferimento", value=date.today())
with chz:
    tzname = "Europe/Rome"  # fisso, niente toggle
    st.text_input("Fuso orario (fisso)", tzname, disabled=True)

st.write("")  # spacing
st.subheader("1) Finestre orarie A · B · C")
c1,c2,c3 = st.columns(3)
def tt(h,m): return time(h,m)
with c1:
    A_start = st.time_input("Inizio A", tt(9,0), key="A_s")
    A_end   = st.time_input("Fine A",   tt(11,0), key="A_e")
with c2:
    B_start = st.time_input("Inizio B", tt(11,0), key="B_s")
    B_end   = st.time_input("Fine B",   tt(13,0), key="B_e")
with c3:
    C_start = st.time_input("Inizio C", tt(13,0), key="C_s")
    C_end   = st.time_input("Fine C",   tt(16,0), key="C_e")

st.write("")
st.subheader("2) Orizzonte previsionale")
hours = st.slider("Ore previsione (da ora)", 12, 168, 72, 12)
st.markdown("<div class='slider-tip'>Suggerimento: < 48h → stime più affidabili</div>", unsafe_allow_html=True)

# =============== Open-Meteo ===============
def fetch_open_meteo(lat, lon, tzname):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=lat, longitude=lon, timezone=tzname,
            hourly="temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,rain,snowfall,cloudcover,windspeed_10m,weathercode,is_day",
            forecast_days=7,
        ),
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def build_df(js, hours):
    h = js["hourly"]; df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    now0 = pd.Timestamp.now(tz=tz.gettz(js.get("timezone","UTC"))).floor("H").tz_localize(None)
    df = df[df["time"]>=now0].head(int(hours)).reset_index(drop=True)
    out = pd.DataFrame()
    out["time"] = df["time"]
    out["T2m"]  = df["temperature_2m"].astype(float)
    if "relative_humidity_2m" in df: out["RH"] = df["relative_humidity_2m"].astype(float)
    else: out["RH"] = pd.NA
    out["td"]   = df.get("dew_point_2m", out["T2m"]).astype(float)
    out["cloud"]= (df["cloudcover"].astype(float)/100).clip(0,1)
    out["wind"] = (df["windspeed_10m"].astype(float)/3.6)  # m/s
    out["sunup"]= df["is_day"].astype(int)
    out["prp_mmph"] = df["precipitation"].astype(float)
    out["rain"] = df.get("rain",0.0).astype(float)
    out["snowfall"] = df.get("snowfall",0.0).astype(float)
    out["wcode"] = df.get("weathercode",0).astype(int)
    return out

# Precipitazione tipo
def prp_type_row(row):
    if row.prp_mmph<=0 or pd.isna(row.prp_mmph): return "none"
    if row.rain>0 and row.snowfall>0: return "mixed"
    if row.snowfall>0 and row.rain==0: return "snow"
    if row.rain>0 and row.snowfall==0: return "rain"
    snow_codes = {71,73,75,77,85,86}; rain_codes={51,53,55,61,63,65,80,81,82}
    if int(row.wcode) in snow_codes: return "snow"
    if int(row.wcode) in rain_codes: return "rain"
    return "mixed"

# =============== Algoritmo Temperatura Neve & Scorrevolezza ===============
def snow_temperature_model(df: pd.DataFrame, dt_hours=1.0):
    X = df.copy()
    X["ptyp"] = X.apply(prp_type_row, axis=1)

    sunup = X["sunup"]==1
    near0 = X["T2m"].between(-1.2, 1.2)
    wet = (
        (X["ptyp"].isin(["rain","mixed"])) |
        ((X["ptyp"]=="snow") & X["T2m"].ge(-1.0)) |
        (sunup & (X["cloud"]<0.35) & X["T2m"].ge(-2.0)) |
        (X["T2m"]>0.0)
    )

    T_surf = pd.Series(index=X.index, dtype=float)
    T_surf.loc[wet] = 0.0

    dry = ~wet
    clear = (1.0 - X["cloud"]).clip(0,1)
    windc = X["wind"].clip(upper=6.0)
    drad = (1.8 + 3.3*clear - 0.35*windc).clip(0.5, 5.0)
    T_surf.loc[dry] = X["T2m"][dry] - drad[dry]

    sunny_cold = sunup & dry & X["T2m"].between(-12,0, inclusive="both")
    T_surf.loc[sunny_cold] = pd.concat([
        (X["T2m"] + 0.4*(1.0 - X["cloud"]))[sunny_cold],
        pd.Series(-0.8, index=X.index)[sunny_cold]
    ], axis=1).min(axis=1)

    T_top5 = pd.Series(index=X.index, dtype=float)
    tau = pd.Series(6.0, index=X.index, dtype=float)
    tau.loc[(X["ptyp"]!="none") | (X["wind"]>=6)] = 3.0
    tau.loc[((X["sunup"]==0) & (X["wind"]<2) & (X["cloud"]<0.3))] = 8.0
    alpha = 1.0 - (math.e ** (-dt_hours / tau))
    if len(X)>0:
        T_top5.iloc[0] = float(min(X["T2m"].iloc[0], 0.0))
        for i in range(1,len(X)):
            T_top5.iloc[i] = T_top5.iloc[i-1] + alpha.iloc[i] * (T_surf.iloc[i] - T_top5.iloc[i-1])

    X["T_surf"] = T_surf.round(2)
    X["T_top5"] = T_top5.round(2)

    base_speed = 100 - (abs(X["T_surf"] + 6.0)*7.5).clip(0,100)
    wet_pen   = (X["ptyp"].isin(["rain","mixed"]) | near0).astype(int)*25
    stick_pen = ((X["RH"].fillna(75) > 90) & (X["T_surf"] > -1.0)).astype(int)*10
    speed_idx = (base_speed - wet_pen - stick_pen).clip(0,100)
    X["speed_index"] = speed_idx.round(0)

    return X

def classify_snow(row):
    if row.ptyp=="rain": return "Neve bagnata/pioggia"
    if row.ptyp=="mixed": return "Mista/pioggia-neve"
    if row.ptyp=="snow" and row.T_surf>-2: return "Neve nuova umida"
    if row.ptyp=="snow" and row.T_surf<=-2: return "Neve nuova fredda"
    if row.T_surf<=-8 and row.cloud<0.4 and row.sunup==0: return "Rigelata/ghiacciata"
    if row.sunup==1 and row.T_surf>-2 and row.cloud<0.3: return "Primaverile/trasformata"
    return "Compatta"

def reliability(hours_ahead):
    x = float(hours_ahead)
    if x<=24: return 85
    if x<=48: return 75
    if x<=72: return 65
    if x<=120: return 50
    return 40

# =============== Scioline (brand) ===============
SWIX = [("PS5 Turquoise",-18,-10),("PS6 Blue",-12,-6),("PS7 Violet",-8,-2),("PS8 Red",-4,4),("PS10 Yellow",0,10)]
TOKO = [("Blue",-30,-9),("Red",-12,-4),("Yellow",-6,0)]
VOLA = [("MX-E Blue",-25,-10),("MX-E Violet",-12,-4),("MX-E Red",-5,0),("MX-E Yellow",-2,6)]
RODE = [("R20 Blue",-18,-8),("R30 Violet",-10,-3),("R40 Red",-5,0),("R50 Yellow",-1,10)]
HOLM = [("UltraMix Blue",-20,-8),("BetaMix Red",-14,-4),("AlphaMix Yellow",-4,5)]
MAPL = [("Univ Cold",-12,-6),("Univ Medium",-7,-2),("Univ Soft",-5,0)]
START= [("SG Blue",-12,-6),("SG Purple",-8,-2),("SG Red",-3,7)]
SKIGO= [("Blue",-12,-6),("Violet",-8,-2),("Red",-3,2)]
BRANDS = [("Swix","assets/brands/swix.png",SWIX),("Toko","assets/brands/toko.png",TOKO),
          ("Vola","assets/brands/vola.png",VOLA),("Rode","assets/brands/rode.png",RODE),
          ("Holmenkol","assets/brands/holmenkol.png",HOLM),("Maplus","assets/brands/maplus.png",MAPL),
          ("Start","assets/brands/start.png",START),("Skigo","assets/brands/skigo.png",SKIGO)]

def pick_wax(bands, t):
    for n,tmin,tmax in bands:
        if t>=tmin and t<=tmax: return n
    return bands[-1][0] if t>bands[-1][2] else bands[0][0]

def recommended_structure(Tsurf):
    if Tsurf <= -10: return "Linear Fine (freddo/secco)"
    if Tsurf <= -3:  return "Cross Hatch leggera (universale freddo)"
    if Tsurf <= 0.5: return "Diagonal/Scarico V (umido)"
    return "Wave/Scarico marcato (bagnato caldo)"

# === NOVITÀ: tipo sciolina (solida/liquida) + sequenza spazzole ===
def wax_process_for(Tsurf: float, RH: float|None):
    """Restituisce (formato, sequenza_spazzole) in base a T_neve media e UR."""
    rh = 70.0 if RH is None or pd.isna(RH) else float(RH)
    # Forma (regola semplice ma pratica)
    # molto freddo → solida dura; vicino a 0 e UR alta → liquida/rapida
    if Tsurf <= -6:
        form = "solida (hard)"
    elif Tsurf <= -2 and rh < 80:
        form = "solida (medium)"
    else:
        form = "liquida (race/quick)"

    # Sequenza spazzole (concisa e realistica)
    # solida: raschiata → ottone → nylon → crine
    # liquida: feltro/applicatore → attesa → nylon fine → crine
    if form.startswith("solida"):
        sequence = "Raschiata → Ottone → Nylon → Crine"
    else:
        sequence = "Feltro/Applicatore → Attesa → Nylon fine → Crine"
    return form, sequence

# =============== NOAA opzionale (climatologia RH) ===============
NOAA_TOKEN = st.secrets.get("NOAA_TOKEN", None)
def try_enrich_with_noaa(df, lat, lon, when_day: date):
    if not NOAA_TOKEN: return df
    try:
        _ = (lat, lon, when_day)  # placeholder soft
        corr = (70 - df["RH"].fillna(70)) * 0.03
        df["RH"] = (df["RH"].fillna(70) + corr).clip(5, 100)
        return df
    except:
        return df

# =============== Sezione calcolo ===============
st.write("")
st.subheader("3) Meteo & calcolo")
btn = st.button("Scarica/aggiorna previsioni", type="primary", use_container_width=True)

if btn:
    try:
        js = fetch_open_meteo(lat,lon,tzname)
        raw = build_df(js, hours)

        # Enrichment NOAA (soft)
        raw = try_enrich_with_noaa(raw, lat, lon, target_day)

        # Calcolo
        res = snow_temperature_model(raw)

        # Tabella principale
        show = pd.DataFrame({
            "Ora":    res["time"].dt.strftime("%Y-%m-%d %H:%M"),
            "T aria (°C)": res["T2m"].round(1),
            "Td (°C)":     res["td"].round(1),
            "UR (%)":      res["RH"].round(0),
            "Vento (m/s)": res["wind"].round(1),
            "Nuvolosità":  (res["cloud"]*100).round(0),
            "Prp (mm/h)":  res["prp_mmph"].round(2),
            "Tipo prp":    res["ptyp"].apply(lambda s: {"none":"—","rain":"pioggia","snow":"neve","mixed":"mista"}.get(s,s)),
            "T neve surf (°C)": res["T_surf"].round(1),
            "T top5mm (°C)":    res["T_top5"].round(1),
            "Indice scorrevolezza": res["speed_index"].astype(int),
        })

        st.markdown("<div class='card tbl'>", unsafe_allow_html=True)
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Blocchi
        blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
        for L,(s,e) in blocks.items():
            st.markdown("---")
            st.markdown(f"### Blocco {L}")

            # Finestra nel giorno scelto
            tzobj = tz.gettz(tzname)
            mask = (res["time"].dt.tz_localize(tzobj, nonexistent='shift_forward', ambiguous='NaT')
                        .dt.tz_convert(tzobj).dt.date == target_day)
            day_df = res[mask].copy()
            if day_df.empty:
                W = res.head(7).copy()
            else:
                cut = day_df[(day_df["time"].dt.time>=s) & (day_df["time"].dt.time<=e)]
                W = cut if not cut.empty else day_df.head(6)

            t_med = float(W["T_surf"].mean()) if not W.empty else 0.0
            k = classify_snow(W.iloc[0]) if not W.empty else "—"
            rel = reliability((W.index[0] if not W.empty else 0) + 1)

            # Banner condizioni
            st.markdown(f"<div class='banner'><b>Condizioni previste:</b> {k} · "
                        f"<b>T_neve med</b> {t_med:.1f}°C · <b>Affidabilità</b> ≈ {rel}%</div>",
                        unsafe_allow_html=True)

            # Struttura (nome)
            st.markdown(f"**Struttura consigliata:** {recommended_structure(t_med)}")

            # Scioline brand + (NOVITÀ) forma & spazzole
            # Determiniamo forma e spazzole in base a media finestra (T_surf) e UR media della finestra
            rh_med = float(W["RH"].mean()) if not W.empty else None
            wax_form, brush_seq = wax_process_for(t_med, rh_med)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Scioline suggerite (per temperatura neve media):**")
                st.markdown(f"<div class='smallnote'>Formato consigliato: <b>{wax_form}</b> · Spazzole: <b>{brush_seq}</b></div>", unsafe_allow_html=True)
                ccols1 = st.columns(4); ccols2 = st.columns(4)
                for i,(name,path,bands) in enumerate(BRANDS[:4]):
                    rec = pick_wax(bands, t_med)
                    ccols1[i].markdown(
                        f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{rec}</div>"
                        f"<div class='smallnote'>[{wax_form}] · {brush_seq}</div></div></div>",
                        unsafe_allow_html=True
                    )
                for i,(name,path,bands) in enumerate(BRANDS[4:]):
                    rec = pick_wax(bands, t_med)
                    ccols2[i].markdown(
                        f"<div class='brand'><div><b>{name}</b><div style='color:#a9bacb'>{rec}</div>"
                        f"<div class='smallnote'>[{wax_form}] · {brush_seq}</div></div></div>",
                        unsafe_allow_html=True
                    )
            with col2:
                if not W.empty:
                    mini = pd.DataFrame({
                        "Ora": W["time"].dt.strftime("%H:%M"),
                        "T aria": W["T2m"].round(1),
                        "T neve": W["T_surf"].round(1),
                        "UR%":   W["RH"].round(0),
                        "V m/s": W["wind"].round(1),
                        "Prp":   W["ptyp"].map({"none":"—","snow":"neve","rain":"pioggia","mixed":"mista"})
                    })
                    st.dataframe(mini, use_container_width=True, hide_index=True)
                else:
                    st.info("Nessun dato nella finestra scelta.")

        # Download CSV completo
        csv = res.copy()
        csv["time"] = csv["time"].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button("Scarica CSV completo", data=csv.to_csv(index=False),
                           file_name="forecast_snow_telemark.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Errore: {e}")
