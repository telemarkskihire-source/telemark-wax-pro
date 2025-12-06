# core/pov_3d.py
# POV 3D pista (beta) per Telemark · Pro Wax & Tune
#
# - Usa i punti estratti da core.pov (ctx["pov_piste_points"])
# - Se trova una MAPBOX_API_KEY (env o st.secrets) usa stile satellite Mapbox
# - Altrimenti mostra solo il tracciato su sfondo semplice
#
# Richiede: pydeck

from __future__ import annotations

from typing import Any, Dict, List

import os

import streamlit as st

try:
    import pydeck as pdk
except Exception:  # pydeck non disponibile
    pdk = None  # type: ignore[assignment]


def _get_mapbox_token() -> str:
    """
    Ritorna la Mapbox API key se disponibile.
    - Prima guarda in os.environ["MAPBOX_API_KEY"]
    - Poi in st.secrets["MAPBOX_API_KEY"]
    Se la trova, la rimette in os.environ per pydeck.
    """
    token = os.getenv("MAPBOX_API_KEY", "")

    try:
        if (not token) and ("MAPBOX_API_KEY" in st.secrets):
            token = st.secrets["MAPBOX_API_KEY"]
    except Exception:
        # st.secrets potrebbe non essere disponibile in alcuni contesti
        pass

    if token:
        os.environ["MAPBOX_API_KEY"] = token

    return token


def _normalize_points(raw_points: Any) -> List[Dict[str, float]]:
    """
    Normalizza ctx["pov_piste_points"] in una lista di dict:
      [{ "lat": ..., "lon": ..., "elev": ...}, ...]
    Supporta:
      - lista di dict con chiavi lat/lon/elev_m
      - lista di tuple/list [lat, lon] o [lat, lon, elev] o [lon, lat, elev]
    """
    if not raw_points:
        return []

    out: List[Dict[str, float]] = []

    for p in raw_points:
        lat = lon = elev = None

        # Caso dict
        if isinstance(p, dict):
            lat = p.get("lat") or p.get("latitude")
            lon = p.get("lon") or p.get("longitude")
            elev = p.get("elev_m") or p.get("elevation") or 0.0

        # Caso lista/tuple
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            a, b = float(p[0]), float(p[1])

            # euristica: lon ha modulo > 90 tipicamente
            if abs(a) > 90 and abs(b) <= 90:
                lon, lat = a, b
            else:
                lat, lon = a, b

            elev = float(p[2]) if len(p) > 2 else 0.0

        if lat is None or lon is None:
            continue

        try:
            out.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "elev": float(elev or 0.0),
                }
            )
        except Exception:
            continue

    return out


def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mostra un POV 3D della pista corrente usando pydeck.
    Richiede che ctx contenga:
      - "pov_piste_points": lista di punti (vedi _normalize_points)
      - "pov_piste_name": nome pista (opzionale)
    """
    if pdk is None:
        st.info("POV 3D non disponibile: il modulo pydeck non è installato.")
        return ctx

    raw_points = ctx.get("pov_piste_points")
    norm_points = _normalize_points(raw_points)

    if not norm_points:
        st.info("POV 3D non disponibile per questa località (nessun tracciato estratto).")
        return ctx

    piste_name = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or T.get("selected_slope", "pista")
    )

    # Path 3D: lista di [lon, lat, elev]
    path = [[p["lon"], p["lat"], p["elev"]] for p in norm_points]

    # ------------------- MAPBOX TOKEN & STILE -------------------
    token = _get_mapbox_token()
    use_mapbox = bool(token)

    if use_mapbox:
        st.caption(f"Mapbox key attiva: True (prefisso: {token[:4]})")
        map_style = "mapbox://styles/mapbox/satellite-streets-v12"
    else:
        st.caption(
            "Mapbox API key non trovata: viene mostrato solo il tracciato, "
            "senza sfondo satellitare."
        )
        # stile di default pydeck (basemap vettoriale)
        map_style = "light"

    # ------------------- LAYER 3D -------------------
    line_layer = pdk.PathLayer(
        "pista_3d",
        data=[{"path": path}],
        get_path="path",
        get_color=[255, 80, 60],
        width_scale=3,
        width_min_pixels=2,
        get_width=3,
    )

    # Punto di partenza (marker verde)
    start = norm_points[0]
    start_layer = pdk.ScatterplotLayer(
        "start_point",
        data=[{"lon": start["lon"], "lat": start["lat"]}],
        get_position="[lon, lat]",
        get_color=[0, 255, 80],
        get_radius=20,
        radius_min_pixels=6,
    )

    # View state centrato circa a metà pista
    mid = norm_points[len(norm_points) // 2]
    view_state = pdk.ViewState(
        longitude=mid["lon"],
        latitude=mid["lat"],
        zoom=13,
        pitch=60,
        bearing=0,
    )

    deck = pdk.Deck(
        layers=[line_layer, start_layer],
        initial_view_state=view_state,
        tooltip={"text": piste_name},
        map_style=map_style,
    )

    st.pydeck_chart(deck)
    st.caption(
        f"POV 3D della pista {piste_name} "
        "(satellite se disponibile; puoi ruotare e zoomare la vista con le dita o il mouse)."
    )

    return ctx
