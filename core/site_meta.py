# core/site_meta.py
import streamlit as st
from .meteo import get_elev, detect_timezone
from .dem_tools import dem_patch, slope_aspect_from_dem, aspect_to_compass

import streamlit as st
from .meteo import get_elev, detect_timezone
from .dem_tools import dem_patch, slope_aspect_from_dem, aspect_to_compass

def render_site_meta(T, ctx):
    lat = float(ctx["lat"]); lon = float(ctx["lon"]); place_label = ctx["place_label"]

    # modalità sync: "auto" (default) o "manual"
    mode = st.session_state.get("alt_sync_mode", "auto")

    # metadati base
    elev = get_elev(lat, lon)
    tzname = detect_timezone(lat, lon)

    # ricalcola solo quando cambiano le coordinate
    coords_key = (round(lat,6), round(lon,6))
    coords_changed = (st.session_state.get("_alt_sync_key") != coords_key)

    if coords_changed:
        # DEM/pendenza/aspect
        try:
            dem = dem_patch(lat, lon)
            if dem:
                sdeg, spct, a_deg = slope_aspect_from_dem(dem["Z"], dem["spacing_m"])
                st.session_state["slope_deg"]  = round(sdeg, 1)
                st.session_state["slope_pct"]  = round(spct)
                st.session_state["aspect_deg"] = round(a_deg)
                st.session_state["aspect_txt"] = aspect_to_compass(a_deg)
            else:
                st.session_state["slope_deg"]=st.session_state["slope_pct"]=st.session_state["aspect_deg"]=None
                st.session_state["aspect_txt"]=None
        except Exception:
            st.session_state["slope_deg"]=st.session_state["slope_pct"]=st.session_state["aspect_deg"]=None
            st.session_state["aspect_txt"]=None

        # aggiornamento altitudine automatico SOLO se non in manual
        if mode != "manual":
            st.session_state["alt_m"] = int(elev) if elev is not None else st.session_state.get("alt_m", 1800)

        st.session_state["_alt_sync_key"] = coords_key

    # badge sintetico
    dem_bits = ""
    if st.session_state.get("slope_deg") is not None:
        dem_bits = (
            f" · ⛰️ {T['slope_deg']} <b>{st.session_state['slope_deg']}°</b>"
            f" ({T['slope_pct']} <b>{st.session_state['slope_pct']}%</b>)"
            f" · 🧭 {T['aspect_dir']} <b>{st.session_state['aspect_txt']}</b>"
        )
    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b>"
        f" · Altitudine <b>{int(elev) if elev is not None else '—'} m</b>"
        f" · TZ <b>{tzname}</b>{dem_bits}</div>",
        unsafe_allow_html=True
    )

    # Toggle: manuale vs auto
    col_tog, col_in = st.columns([1,2])
    with col_tog:
        manual = st.toggle("🔒 Imposta altitudine manualmente", value=(mode=="manual"))
        # aggiorna lo stato se cambia
        new_mode = "manual" if manual else "auto"
        if new_mode != mode:
            st.session_state["alt_sync_mode"] = new_mode
            mode = new_mode

    with col_in:
        if mode == "manual":
            # input manuale che sovrascrive alt_m
            new_alt = st.number_input(
                T['alt_lbl'], min_value=0, max_value=5000,
                value=int(st.session_state.get('alt_m', int(elev or 1800))),
                step=50, key='alt_m'
            )
            if new_alt < 300:
                st.caption("⚠️ " + T["low_alt"])
        else:
            # mostra solo valore che verrà auto-aggiornato a ogni click mappa / cambio coord
            st.metric(T['alt_lbl'], f"{int(st.session_state.get('alt_m', int(elev or 1800)))} m")

    # aggiorna ctx e restituisci
    ctx.update({
        "alt_m": st.session_state.get("alt_m"),
        "tzname": tzname,
        "slope_deg": st.session_state.get("slope_deg"),
        "slope_pct": st.session_state.get("slope_pct"),
        "aspect_deg": st.session_state.get("aspect_deg"),
        "aspect_txt": st.session_state.get("aspect_txt"),
        "alt_sync_mode": mode,
    })
    return ctx

# alias
render = render_site_meta

    # badge sintetico
    dem_bits = ""
    if st.session_state.get("slope_deg") is not None:
        dem_bits = (
            f" · ⛰️ {T['slope_deg']} <b>{st.session_state['slope_deg']}°</b>"
            f" ({T['slope_pct']} <b>{st.session_state['slope_pct']}%</b>)"
            f" · 🧭 {T['aspect_dir']} <b>{st.session_state['aspect_txt']}</b>"
        )
    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b>"
        f" · Altitudine <b>{int(elev) if elev is not None else '—'} m</b>"
        f" · TZ <b>{tzname}</b>{dem_bits}</div>",
        unsafe_allow_html=True
    )

    # input altitudine pista (compatto)
    col_alt, _ = st.columns([1,3])
    with col_alt:
        new_alt = st.number_input(
            T['alt_lbl'], min_value=0, max_value=5000,
            value=st.session_state.get('alt_m', int(elev or 1800)),
            step=50, key='alt_m'
        )
        if new_alt < 300:
            st.caption("⚠️ " + T["low_alt"])

    # aggiorna ctx e restituisci
    ctx.update({
        "alt_m": st.session_state.get("alt_m"),
        "tzname": tzname,
        "slope_deg": st.session_state.get("slope_deg"),
        "slope_pct": st.session_state.get("slope_pct"),
        "aspect_deg": st.session_state.get("aspect_deg"),
        "aspect_txt": st.session_state.get("aspect_txt"),
    })
    return ctx

# alias generico per l’orchestratore
render = render_site_meta
