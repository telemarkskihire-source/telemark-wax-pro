# core/pov_3d.py
# POV 3D pista con pydeck + Mapbox (satellite se disponibile)

from __future__ import annotations

from typing import Dict, Any, List, Optional

import os

import streamlit as st
import pydeck as pdk


def _get_mapbox_token() -> Optional[str]:
    """
    Ritorna la Mapbox API key se configurata in:
      - st.secrets["MAPBOX_API_KEY"]
      - variabile d'ambiente MAPBOX_API_KEY
    Altrimenti None.
    """
    # 1) Streamlit secrets
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            token = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if token:
                return token
    except Exception:
        pass

    # 2) Environment
    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    return token or None


def _build_pov_dataframe(points: List[Dict[str, float]]):
    """
    Converte i punti della pista in una lista per PathLayer:
      [{"path": [[lon, lat, z], ...]}]
    dove z è una quota normalizzata per dare un minimo effetto 3D.
    """
    if not points:
        return []

    # Normalizziamo la quota: se non presente, usiamo 0.
    lats = [p.get("lat", 0.0) for p in points]
    lons = [p.get("lon", 0.0) for p in points]
    elevs = [p.get("elev", 0.0) for p in points]

    # Rescale semplice della quota così da non "sparare" in alto la traccia
    min_elev = min(elevs)
    max_elev = max(elevs) if elevs else min_elev
    span = max(max_elev - min_elev, 1.0)

    scaled = []
    for p, e in zip(points, elevs):
        z = (e - min_elev) / span  # 0–1
        z *= 200  # scala verticale (200 m max)
        scaled.append([p.get("lon", 0.0), p.get("lat", 0.0), z])

    return [{"path": scaled}]


def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mostra una vista 3D della pista corrente (se ctx contiene 'pov_piste_points').

    Richiede:
      ctx["pov_piste_points"] = [
        {"lat": float, "lon": float, "elev": float}, ...
      ]
      ctx["pov_piste_name"] (opzionale)
    """
    points: List[Dict[str, float]] = ctx.get("pov_piste_points") or []
    if not points:
        # Niente pista: non alziamo errori, semplicemente non facciamo nulla.
        st.info("POV 3D non disponibile: nessun tracciato pista estratto.")
        return ctx

    token = _get_mapbox_token()
    mapbox_active = bool(token)

    # Configuriamo pydeck col token SOLO se presente
    if mapbox_active:
        try:
            pdk.settings.mapbox_api_key = token
        except Exception:
            mapbox_active = False

    # Centroid per il view_state
    mid_idx = len(points) // 2
    mid = points[mid_idx]
    center_lat = float(mid.get("lat", 0.0))
    center_lon = float(mid.get("lon", 0.0))

    # Prepara dati per PathLayer
    path_data = _build_pov_dataframe(points)

    # Layer linea pista
    line_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 80, 40],
        width_scale=4,
        width_min_pixels=3,
        pickable=False,
    )

    # Layer punto di partenza evidenziato
    start = points[0]
    start_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lon": start.get("lon", center_lon), "lat": start.get("lat", center_lat)}],
        get_position="[lon, lat]",
        get_radius=40,
        get_fill_color=[0, 255, 100],
        pickable=False,
    )

    # Vista 3D: inclinata e leggermente ruotata
    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=13,
        pitch=60,
        bearing=-45,
    )

    # Stile mappa: satellite se token attivo, altrimenti base "light"
    if mapbox_active:
        map_style = "mapbox://styles/mapbox/satellite-v9"
    else:
        # stile generico senza bisogno di chiave (dipende dalla versione di pydeck)
        map_style = "light"

    deck = pdk.Deck(
        layers=[line_layer, start_layer],
        initial_view_state=view_state,
        map_style=map_style,
        tooltip={"text": "Tracciato POV pista"},
    )

    st.pydeck_chart(deck)

    piste_name = ctx.get("pov_piste_name") or ctx.get("piste_name") or "pista selezionata"

    if mapbox_active:
        prefix = token[:3] + "…" if len(token) >= 3 else "pk…"
        st.caption(
            f"POV 3D della pista {piste_name} "
            f"(satellite · Mapbox key attiva, prefisso: {prefix})."
        )
    else:
        st.caption(
            f"POV 3D della pista {piste_name} "
            f"(tracciato su base map generica, senza sfondo satellite Mapbox)."
        )

    return ctx
