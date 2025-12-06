# core/pov_3d.py — versione compatibile (NO PathLayer)

from __future__ import annotations
from typing import Dict, Any, List, Optional
import os
import streamlit as st
import pydeck as pdk


# ---------------------------------------------------
# GET MAPBOX TOKEN
# ---------------------------------------------------
def _get_token() -> Optional[str]:
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            t = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if t:
                return t
    except Exception:
        pass
    t = os.environ.get("MAPBOX_API_KEY", "").strip()
    return t or None


# ---------------------------------------------------
# PREPARA COORDINATE PER LAYER LINEARE
# ---------------------------------------------------
def _build_line(points: List[Dict[str, float]]):
    """
    Converte i punti in formato utilizzabile da LineLayer.
    """
    out = []
    for p in points:
        out.append([p["lon"], p["lat"], p.get("elev", 0.0)])
    return out


# ---------------------------------------------------
# RENDER POV 3D (compatibile)
# ---------------------------------------------------
def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    pts = ctx.get("pov_piste_points")
    if not pts:
        st.info("POV 3D non disponibile: nessun tracciato pista.")
        return ctx

    token = _get_token()
    if token:
        try:
            pdk.settings.mapbox_api_key = token
        except Exception:
            pass

    # centro pista
    mid = pts[len(pts) // 2]
    center_lat = float(mid["lat"])
    center_lon = float(mid["lon"])

    # dati linea
    line_data = [{"coords": _build_line(pts)}]

    # LineLayer — SEMPRE SUPPORTATO
    line_layer = pdk.Layer(
        "LineLayer",
        data=line_data,
        get_source_position="coords[0]",
        get_target_position="coords[-1]",
        get_color=[255, 60, 60],
        get_width=8,
        pickable=False,
    )

    # punti singoli come fallback estetico
    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lon": p["lon"], "lat": p["lat"]} for p in pts],
        get_position="[lon, lat]",
        get_radius=10,
        get_fill_color=[255, 0, 0],
    )

    # vista 3D inclinata
    view = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=13,
        pitch=60,
        bearing=-45,
    )

    style = "mapbox://styles/mapbox/satellite-v9" if token else None

    deck = pdk.Deck(
        layers=[line_layer, scatter_layer],
        initial_view_state=view,
        map_style=style,
        tooltip={"text": "POV 3D pista"},
    )

    st.pydeck_chart(deck)

    name = ctx.get("pov_piste_name", "pista")
    st.caption(f"POV 3D pista {name} — modalità compatibile (senza PathLayer).")

    return ctx
