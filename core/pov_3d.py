from __future__ import annotations

from typing import Dict, Any, List, Optional
import os
import streamlit as st
import pydeck as pdk

def _get_mapbox_token() -> Optional[str]:
    """Recupera la token Mapbox da secrets oppure environment."""
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            token = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if token:
                return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    return token or None


def _build_pov_dataframe(points: List[Dict[str, float]]):
    """Converte punti pista in formato PathLayer."""
    if not points:
        return []

    elevs = [p.get("elev", 0.0) for p in points]
    min_e = min(elevs)
    max_e = max(elevs)
    span = max(max_e - min_e, 1.0)

    scaled = []
    for p, e in zip(points, elevs):
        z = (e - min_e) / span * 200
        scaled.append([p["lon"], p["lat"], z])

    return [{"path": scaled}]


def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Mostra POV 3D della pista estratta."""
    points = ctx.get("pov_piste_points") or []
    if not points:
        st.info("POV 3D non disponibile: nessun tracciato pista.")
        return ctx

    token = _get_mapbox_token()
    mapbox_active = bool(token)

    if mapbox_active:
        try:
            pdk.settings.mapbox_api_key = token
        except Exception:
            mapbox_active = False

    mid = points[len(points) // 2]
    center_lat = float(mid["lat"])
    center_lon = float(mid["lon"])

    path_data = _build_pov_dataframe(points)

    line_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 80, 40],
        width_scale=4,
        width_min_pixels=3,
        pickable=False,
    )

    start = points[0]
    start_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lon": start["lon"], "lat": start["lat"]}],
        get_position="[lon, lat]",
        get_radius=40,
        get_fill_color=[0, 255, 100],
        pickable=False,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=13,
        pitch=60,
        bearing=-45,
    )

    map_style = (
        "mapbox://styles/mapbox/satellite-v9"
        if mapbox_active else
        "light"
    )

    deck = pdk.Deck(
        layers=[line_layer, start_layer],
        initial_view_state=view_state,
        map_style=map_style,
        tooltip={"text": "Tracciato POV pista"},
    )

    st.pydeck_chart(deck)

    pname = ctx.get("pov_piste_name", "pista selezionata")
    if mapbox_active:
        st.caption(f"POV 3D attivo (Mapbox token ok: {token[:3]}…)")
    else:
        st.caption("POV 3D attivo (senza satellite — token assente).")

    return ctx
