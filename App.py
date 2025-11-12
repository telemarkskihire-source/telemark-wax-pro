# app.py — Telemark · Pro Wax & Tune (skeleton modulare)

import streamlit as st
from datetime import date, time as dtime
from dateutil import tz
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from core.i18n import L
from core.utils import flag, persist, tt, c_to_f, ms_to_kmh
from core.utils import concise_label
from core.meteo import (
    fetch_open_meteo, build_df, detect_timezone, get_elev,
    enrich_meteo_quickwins, snow_temperature_model, noaa_bias_correction,
    classify_snow, reliability, recommended_structure, tune_for
)
from core.maps import nominatim_searchbox, pistes_map
from core.dem_tools import dem_patch, slope_aspect_from_dem, aspect_to_compass
from core.wax_logic import BRANDS, get_brand_logo_b64, pick_wax, pick_liquid, wax_form_and_brushes

# ---------------- THEME ----------------
PRIMARY = "#06b6d4"; ACCENT  = "#f97316"; OK = "#10b981"; WARN = "#f59e0b"; ERR = "#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: 0.6rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing: .2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{ display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }}
.card {{ background: var(--panel); border:1px solid var(--line); border-radius:12px; padding: .9rem .95rem; }}
.banner {{ border-left: 6px solid {ACCENT}; background:#1a2230; color:#e2e8f0; padding:.75rem .9rem; border-radius:10px; font-size:.98rem; }}
.brand {{ display:flex; align-items:flex-start; gap:.65rem; background:#0e141d; border:1px solid #1e2a3a; border-radius:10px; padding:.75rem .8rem; width:100% }}
.brand h4 {{ margin:0 0 .25rem 0; font-size:1rem; color:#fff }}
.brand .muted {{ color:#a9bacb }}
.brand .sub {{ color:#93b2c6; font-size:.85rem }}
.brand .logo {{ flex:0 0 auto; display:flex; align-items:center; justify-content:center; width:54px; height:54px; background:#0b121a; border:1px solid #1e2a3a; border-radius:10px; overflow:hidden }}
.brand .logo img {{ max-width:52px; max-height:52px; display:block }}
.grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:.6rem; }}
.tune ul {{ margin:.5px 0 0 1rem; padding:0; }}
.small {{ font-size:.85rem; color:#cbd5e1 }}
.badge-red {{ border-left:6px solid {ERR}; background:#2a1518; color:#fee2e2; padding:.6rem .8rem; border-radius:10px; }}
.leaflet-control {{ z-index: 1000 !important; }}
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# -------------- SIDEBAR: lingua/unità/debug --------------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang=="IT" else L["en"]
units = st.sidebar.radio(T["unit"], [T["unit_c"], T["unit_f"]], index=0, horizontal=False)
use_fahrenheit = (units==T["unit_f"])
show_debug = st.sidebar.checkbox(T["debug"], value=False)

# -------------- TOP BAR: ricerca + offset + reset --------------
COUNTRIES = {"Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"}
col_top = st.columns([2,1,1,1])
with col_top[1]:
    sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
    iso2 = COUNTRIES[sel_country]
with col_top[2]:
    offset = st.slider(T["offset"], -1.5, 1.5, 0.0, 0.1, key="cal_offset")
with col_top[3]:
    if st.button(T["reset"], use_container_width=True):
        for k in list(st.session_state.keys()):
            if k not in ("country_sel",):  # conserva paese
                del st.session_state[k]
        st.rerun()

with col_top[0]:
    # Searchbox veloce (filtra per paese, debounce interno)
    selected, info = nominatim_searchbox(T["search_ph"], iso2)
    if info:
        st.session_state["lat"] = info["lat"]
        st.session_state["lon"] = info["lon"]
        st.session_state["place_label"] = info["label"]

# -------------- Stato coordinate --------------
lat = persist("lat", 45.831)
lon = persist("lon", 7.730)
place_label = persist("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

# -------------- Metadati: quota, tz, DEM --------------
elev = get_elev(lat, lon)
tzname = detect_timezone(lat, lon)

coords_key = (round(lat,6), round(lon,6))
if st.session_state.get("_alt_sync_key") != coords_key:
    st.session_state["alt_m"] = int(elev) if elev is not None else st.session_state.get("alt_m", 1800)
    try:
        dem = dem_patch(lat, lon)
        if dem:
            slope_deg, slope_pct, aspect_deg = slope_aspect_from_dem(dem["Z"], dem["spacing_m"])
            st.session_state["slope_deg"]  = round(slope_deg, 1)
            st.session_state["slope_pct"]  = round(slope_pct)
            st.session_state["aspect_deg"] = round(aspect_deg)
            st.session_state["aspect_txt"] = aspect_to_compass(aspect_deg)
        else:
            st.session_state["slope_deg"]=st.session_state["slope_pct"]=st.session_state["aspect_deg"]=None
            st.session_state["aspect_txt"]=None
    except Exception:
        st.session_state["slope_deg"]=st.session_state["slope_pct"]=st.session_state["aspect_deg"]=None
        st.session_state["aspect_txt"]=None
    st.session_state["_alt_sync_key"] = coords_key

dem_badge = ""
if st.session_state.get("slope_deg") is not None:
    dem_badge = f" · ⛰️ {T['slope_deg']} <b>{st.session_state['slope_deg']}°</b> ({T['slope_pct']} <b>{st.session_state['slope_pct']}%</b>) · 🧭 {T['aspect_dir']} <b>{st.session_state['aspect_txt']}</b>"
st.markdown(
    f"<div class='badge'>📍 <b>{place_label}</b> · Altitudine <b>{int(elev) if elev is not None else '—'} m</b> · TZ <b>{tzname}</b>{dem_badge}</div>",
    unsafe_allow_html=True
)

# -------------- Mappa (solo piste alpine) --------------
pistes_map(lat, lon, place_label)

# -------------- Data & blocchi --------------
cdate, calt = st.columns([1,1])
with cdate:
    target_day = st.date_input(T["ref_day"], value=persist("ref_day", date.today()), key="ref_day")
with calt:
    pista_alt = st.number_input(T["alt_lbl"], min_value=0, max_value=5000, value=st.session_state.get("alt_m", int(elev or 1800)), step=50, key="alt_m")
    if pista_alt < 300: st.warning(T["low_alt"])

st.subheader(T["blocks"])
c1,c2,c3 = st.columns(3)
with c1:
    A_start = st.time_input(T["start"]+" A", dtime(9,0),  key="A_s")
    A_end   = st.time_input(T["end"]+" A",   dtime(11,0), key="A_e")
with c2:
    B_start = st.time_input(T["start"]+" B", dtime(11,0), key="B_s")
    B_end   = st.time_input(T["end"]+" B",   dtime(13,0), key="B_e")
with c3:
    C_start = st.time_input(T["start"]+" C", dtime(13,0), key="C_s")
    C_end   = st.time_input(T["end"]+" C",   dtime(16,0), key="C_e")

st.subheader(T["horizon"])
hours = st.slider(T["horizon"]+" ("+("da ora" if lang=="IT" else "from now")+")", 12, 168, persist("hours",72), 12, key="hours")
st.markdown(f"<div class='slider-tip'>{T['tip']}</div>", unsafe_allow_html=True)

# -------------- RUN --------------
st.subheader("3) Meteo & calcolo")
btn = st.button(T["fetch"], type="primary", use_container_width=True)

def windows_valid():
    ok = True
    for lbl,(s,e) in {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}.items():
        if s>=e:
            st.error(T["invalid_win"].format(lbl=lbl)); ok=False
    return ok

def plot_speed_mini(res):
    fig = plt.figure(figsize=(6,2.2))
    plt.plot(res["time_local"].dt.tz_localize(None), res["speed_index"])
    plt.title(T["speed_chart"]); plt.grid(alpha=.2)
    st.pyplot(fig); plt.close(fig)

def brand_card_html(name, base_solid, form, topcoat, brushes, logo_b64):
    logo_html = f"<div class='logo'><img src='data:image/png;base64,{logo_b64}'/></div>" if logo_b64 else "<div class='logo'></div>"
    return f"""
    <div class='brand'>
      {logo_html}
      <div style='flex:1'>
        <h4>{name}</h4>
        <div class='muted'>{T['base_solid']}: <b>{base_solid}</b></div>
        <div class='sub'>Forma: {form}</div>
        <div class='sub'>{T['topcoat_lbl']}: {topcoat}</div>
        <div class='sub'>Spazzole: {brushes}</div>
      </div>
    </div>
    """

if btn and windows_valid():
    with st.status(T["status_title"], expanded=False) as status:
        try:
            js = fetch_open_meteo(lat, lon)
            raw = build_df(js, hours)
            if raw.empty:
                st.error("Nessun dato meteo disponibile adesso."); status.update(state="error"); st.stop()
            raw = noaa_bias_correction(raw, lat, lon)
            base_alt = st.session_state.get("alt_m", elev or 1800)
            X = enrich_meteo_quickwins(raw, lat, lon, base_alt, st.session_state.get("alt_m", base_alt))
            res = snow_temperature_model(X)
            tzobj = tz.gettz(tzname)
            res["time_local"] = res["time_utc"].dt.tz_convert(tzobj)

            if abs(st.session_state.get("cal_offset",0))>0:
                off = st.session_state["cal_offset"]
                res["T_surf"] = (res["T_surf"] + off).round(2)
                res["T_top5"] = (res["T_top5"] + off).round(2)
                # ricalcolo speed_index con offset (stessa formula usata nel monolite)
                near_zero_bonus = 20 * np.exp(-((res["T_surf"] + 0.4)/1.1)**2)
                humidity_bonus  = np.clip((res["RH"]-60)/40, 0, 1)*10
                radiation_bonus = np.clip(res["SW_down"]/600, 0, 1)*8
                wind_pen        = np.clip(res["wind"]/10, 0, 1)*10
                wet_pen         = np.clip(res["liq_water_pct"]/6, 0, 1)*25
                base_speed      = 55 + near_zero_bonus + humidity_bonus + radiation_bonus
                res["speed_index"] = np.clip(base_speed - wind_pen - wet_pen, 0, 100).round(0)

            disp = res.copy()
            if use_fahrenheit:
                for col in ["T2m","td","Tw","T_surf","T_top5"]:
                    disp[col] = c_to_f(disp[col])

            # --- GRAFICI COMPATTI ---
            tloc = disp["time_local"].dt.tz_localize(None)
            fig1 = plt.figure(figsize=(10,3))
            plt.plot(tloc, disp["T2m"], label=T["t_air"].replace("°C","°F") if use_fahrenheit else T["t_air"])
            plt.plot(tloc, disp["T_surf"], label=T["t_surf"].replace("°C","°F") if use_fahrenheit else T["t_surf"])
            plt.plot(tloc, disp["T_top5"], label=T["t_top5"].replace("°C","°F") if use_fahrenheit else T["t_top5"])
            plt.legend(); plt.title(T["temp"]); plt.xlabel(T["hour"]); plt.ylabel("°F" if use_fahrenheit else "°C"); plt.grid(alpha=0.2)
            st.pyplot(fig1); plt.close(fig1)

            fig2 = plt.figure(figsize=(10,2.6))
            plt.bar(tloc, disp["prp_mmph"], width=0.025)
            plt.title(T["prec"]); plt.xlabel(T["hour"]); plt.ylabel("mm/h"); plt.grid(alpha=0.2)
            st.pyplot(fig2); plt.close(fig2)

            fig3 = plt.figure(figsize=(10,2.6))
            plt.plot(tloc, disp["SW_down"], label="SW↓")
            plt.plot(tloc, disp["RH"], label=T["rh"])
            plt.legend(); plt.title(T["radhum"]); plt.grid(alpha=0.2)
            st.pyplot(fig3); plt.close(fig3)

            # --- TABELLE METEO (AGGIUNTE) ---
            st.subheader("Tabelle meteo")
            tbl_cols = ["time_local","T2m","td","Tw","RH","wind","SW_down","cloud","prp_mmph","rain","snowfall","T_surf","T_top5","liq_water_pct","speed_index"]
            table_df = disp[tbl_cols].copy()
            table_df["time_local"] = table_df["time_local"].dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(table_df, use_container_width=True, height=350)

            # --- Blocchi A/B/C + wax cards ---
            blocks = {"A":(A_start,A_end),"B":(B_start,B_end),"C":(C_start,C_end)}
            wind_unit_lbl = "m/s" if not use_fahrenheit else "km/h"
            for L,(s,e) in blocks.items():
                st.markdown("---")
                st.markdown(f"### Blocco {L}")
                mask_day = disp["time_local"].dt.date == target_day
                day_df = disp[mask_day].copy()
                if day_df.empty:
                    W = disp.head(7).copy()
                else:
                    sel = day_df[(day_df["time_local"].dt.time>=s) & (day_df["time_local"].dt.time<=e)]
                    W = sel if not sel.empty else day_df.head(6)
                if W.empty:
                    st.info(T["nodata"]); continue

                t_med = float(W["T_surf"].mean())
                rh_med = float(W["RH"].mean())
                any_alert = ((W["T_surf"] > (-0.5 if not use_fahrenheit else c_to_f(-0.5))) & (W["RH"]>85)).any()
                if any_alert:
                    st.markdown(f"<div class='badge-red'>⚠ {T['alert'].format(lbl=L)}</div>", unsafe_allow_html=True)
                k = classify_snow(W.iloc[0])
                rel = reliability((W.index[0] if not W.empty else 0) + 1)
                v_eff = (W["wind"] if not use_fahrenheit else ms_to_kmh(W["wind"])).mean()
                st.markdown(
                    f"<div class='banner'><b>{T['cond']}</b> {k} · "
                    f"<b>T_neve med</b> {t_med:.1f}{'°F' if use_fahrenheit else '°C'} · <b>H₂O liquida</b> {float(W['liq_water_pct'].mean()):.1f}% · "
                    f"<b>Affidabilità</b> ≈ {rel}% · "
                    f"<b>V eff</b> {v_eff:.1f} {wind_unit_lbl}</div>",
                    unsafe_allow_html=True
                )

                t_for_struct = t_med if not use_fahrenheit else (t_med-32)*5/9
                st.markdown(f"**{T['struct']}** {recommended_structure(t_for_struct)}")
                wax_form, brush_seq, use_topcoat = wax_form_and_brushes(t_for_struct, rh_med)

                st.markdown("<div class='grid'>", unsafe_allow_html=True)
                for (name, solid_bands, liquid_bands) in BRANDS:
                    rec_solid  = pick_wax(solid_bands, t_for_struct, rh_med)
                    topcoat = (pick_liquid(liquid_bands, t_for_struct, rh_med) if use_topcoat else ("non necessario" if lang=="IT" else "not needed"))
                    logo_b64 = get_brand_logo_b64(name)
                    html = brand_card_html(name, rec_solid, wax_form, topcoat, brush_seq, logo_b64)
                    st.markdown(html, unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

                # tabella riassuntiva blocco
                st.markdown("**Tabella blocco**")
                st.dataframe(
                    W[["time_local","T2m","RH","wind","prp_mmph","T_surf","T_top5","liq_water_pct","speed_index"]].assign(
                        time_local=lambda d: d["time_local"].dt.strftime("%Y-%m-%d %H:%M")
                    ),
                    use_container_width=True, height=220
                )

            status.update(label=f"{T['last_upd']}", state="complete", expanded=False)

        except Exception as e:
            status.update(label=f"Errore: {e}", state="error", expanded=True)
            if show_debug: st.exception(e)
