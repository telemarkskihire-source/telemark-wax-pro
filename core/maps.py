# core/maps.py

from __future__ import annotations
from typing import Dict, Any, List, Optional

import streamlit as st
from streamlit_folium import st_folium
import folium


# ---------------------------
# Utility: distanza punto-linea
# ---------------------------
def _distance_point_to_segment(lat: float, lon: float,
                               p1: List[float], p2: List[float]) -> float:
    # distanza euclidea leggera (per scelta pista)
    import math

    x0, y0 = lat, lon
    x1, y1 = p1
    x2, y2 = p2

    dx = x2 - x1
    dy = y2 - y1
    if dx == dy == 0:
        return math.hypot(x0 - x1, y0 - y1)

    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx*dx + dy*dy)
    t = max(0, min(1, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return math.hypot(x0 - px, y0 - py)


# ---------------------------
# Trova la pista più vicina
# ---------------------------
def _find_closest_piste(lat: float, lon: float,
                        pistas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:

    if not pistas:
        return None

    best = None
    best_d = 9999

    for p in pistas:
        pts = p.get("coords")
        if not pts or len(pts) < 2:
            continue

        for i in range(len(pts) - 1):
            d = _distance_point_to_segment(lat, lon, pts[i], pts[i+1])
            if d < best_d:
                best_d = d
                best = p

    # soglia realistica: 40 metri
    if best_d < 0.0004:
        return best

    return None


# ---------------------------
# Render principale della mappa
# ---------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:

    lat = ctx.get("lat", 45.83)
    lon = ctx.get("lon", 7.73)

    pistas: List[Dict[str, Any]] = ctx.get("pistes", [])

    # ---------------------------
    # CREA MAPPA
    # ---------------------------
    m = folium.Map(
        location=[lat, lon],
        zoom_start=14,
        tiles=None,
        prefer_canvas=True,
    )

    folium.TileLayer(
        "Esri.WorldImagery",
        attr="Esri",
        name="Satellite"
    ).add_to(m)

    # ---------------------------
    # Disegna tutte le piste
    # ---------------------------
    for p in pistas:
        coords = p.get("coords", [])
        if len(coords) >= 2:
            folium.PolyLine(
                coords,
                color="#3388ff",
                weight=3,
                opacity=0.7,
            ).add_to(m)

    # ---------------------------
    # Disegna la pista selezionata
    # ---------------------------
    sel = ctx.get("selected_piste")
    if sel and sel.get("coords"):
        folium.PolyLine(
            sel["coords"],
            color="yellow",
            weight=6,
            opacity=0.9,
        ).add_to(m)

    # ---------------------------
    # Marker
    # ---------------------------
    folium.Marker(
        [lat, lon],
        icon=folium.Icon(color="red", icon="flag")
    ).add_to(m)

    # ---------------------------
    # Lettura click
    # ---------------------------
    map_data = st_folium(
        m,
        height=550,
        width=None,
        key="telemark_map",
    )

    # CLICK SEMPRE LETTO
    click = None
    if map_data and "last_clicked" in map_data:
        click = map_data["last_clicked"]

    if click:
        new_lat = float(click["lat"])
        new_lon = float(click["lng"])

        ctx["lat"] = new_lat
        ctx["lon"] = new_lon

        # trova pista
        found = _find_closest_piste(new_lat, new_lon, pistas)
        ctx["selected_piste"] = found

        # salva in sessione
        st.session_state["lat"] = new_lat
        st.session_state["lon"] = new_lon
        st.session_state["selected_piste"] = found

    return ctx
