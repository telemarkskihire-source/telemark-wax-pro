# core/site_meta.py
import streamlit as st
from .meteo import get_elev, detect_timezone
from .dem_tools import dem_patch, slope_aspect_from_dem, aspect_to_compass

def render_site_meta(T, ctx):
    lat = float(ctx["lat"]); lon = float(ctx["lon"]); place_label = ctx["place_label"]

    elev = get_elev(lat, lon)
    tzname = detect_timezone(lat, lon)

    # sync quando cambiano le coordinate
    coords_key = (round(lat,6), round(lon,6))
    if st.session_state.get("_alt_sync_key") != coords_key:
        st.session_state["alt_m"] = int(elev) if elev is not None else st.session_state.get("alt_m", 1800)
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
