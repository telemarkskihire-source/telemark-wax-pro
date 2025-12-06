# core/pov_3d.py
# POV 3D pista con pydeck + Mapbox (satellite se disponibile)
#
# - Legge i punti puliti da ctx["pov_piste_points"]
# - Ripulisce la traccia da "salti folli" (punti lontanissimi)
# - Tiene solo il segmento continuo più lungo
# - Mostra un PathLayer 3D compatibile con la versione di pydeck di Streamlit Cloud

from __future__ import annotations

from typing import Dict, Any, List, Optional

import math
import os

import streamlit as st
import pydeck as pdk


# ---------------------------------------------------------------------
# CONFIG TOKEN MAPBOX
# ---------------------------------------------------------------------
def _get_mapbox_token() -> Optional[str]:
    """
    Ritorna la Mapbox API key se configurata in:
      - st.secrets["MAPBOX_API_KEY"]
      - variabile d'ambiente MAPBOX_API_KEY
    Altrimenti None.
    """
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            token = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if token:
                return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    return token or None


# ---------------------------------------------------------------------
# UTILS GEO
# ---------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due punti lat/lon (formula haversine semplificata)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _pick_main_segment(points: List[Dict[str, float]], max_jump_m: float = 2000.0) -> List[Dict[str, float]]:
    """
    Dato un elenco di punti [{lat, lon, elev}, ...] prende il segmento continuo
    più lungo, dove la distanza fra due punti consecutivi non supera max_jump_m.

    Serve per eliminare salti assurdi (tipo Italia → Francia in una polyline).
    """
    if len(points) < 2:
        return points

    segments: List[List[Dict[str, float]]] = []
    current: List[Dict[str, float]] = [points[0]]

    for i in range(1, len(points)):
        p_prev = points[i - 1]
        p = points[i]
        d = _dist_m(
            float(p_prev.get("lat", 0.0)),
            float(p_prev.get("lon", 0.0)),
            float(p.get("lat", 0.0)),
            float(p.get("lon", 0.0)),
        )
        if d <= max_jump_m:
            current.append(p)
        else:
            # chiudo segmento e ne apro uno nuovo
            if len(current) >= 2:
                segments.append(current)
            current = [p]

    if len(current) >= 2:
        segments.append(current)

    if not segments:
        return points

    # prendo il segmento con lunghezza totale maggiore
    def seg_length(seg: List[Dict[str, float]]) -> float:
        tot = 0.0
        for i in range(1, len(seg)):
            a = seg[i - 1]
            b = seg[i]
            tot += _dist_m(
                float(a.get("lat", 0.0)),
                float(a.get("lon", 0.0)),
                float(b.get("lat", 0.0)),
                float(b.get("lon", 0.0)),
            )
        return tot

    best = max(segments, key=seg_length)
    return best


def _build_pov_path(points: List[Dict[str, float]]):
    """
    Converte punti pista in formato compatibile PathLayer:
      data = [{"path": [[lon, lat, z], ...]}]
    dove z è una quota normalizzata (0–200 m).
    """
    if not points:
        return []

    elevs = [float(p.get("elev", 0.0)) for p in points]
    min_e = min(elevs)
    max_e = max(elevs)
    span = max(max_e - min_e, 1.0)

    path_coords: List[List[float]] = []
    for p, e in zip(points, elevs):
        lat = float(p.get("lat", 0.0))
        lon = float(p.get("lon", 0.0))
        z = (e - min_e) / span * 200.0  # max 200 m di differenza
        # pydeck vuole [lon, lat, z]
        path_coords.append([lon, lat, z])

    return [{"path": path_coords}]


# ---------------------------------------------------------------------
# RENDER 3D
# ---------------------------------------------------------------------
def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mostra una vista 3D della pista corrente (se ctx contiene 'pov_piste_points').

    Richiede:
      ctx["pov_piste_points"] = [
        {"lat": float, "lon": float, "elev": float}, ...
      ]
    """
    raw_points = ctx.get("pov_piste_points") or []
    if not raw_points:
        st.info("POV 3D non disponibile: nessun tracciato pista estratto.")
        return ctx

    # 1) normalizzo in dict puliti
    points: List[Dict[str, float]] = []
    for p in raw_points:
        try:
            lat = float(p.get("lat"))  # type: ignore[arg-type]
            lon = float(p.get("lon"))  # type: ignore[arg-type]
            elev = float(p.get("elev", 0.0))  # type: ignore[arg-type]
        except Exception:
            continue
        points.append({"lat": lat, "lon": lon, "elev": elev})

    if len(points) < 2:
        st.info("POV 3D non disponibile: traccia con troppo pochi punti.")
        return ctx

    # 2) elimino salti assurdi e prendo il segmento principale
    cleaned = _pick_main_segment(points, max_jump_m=2000.0)
    if len(cleaned) < 4:
        st.info("POV 3D non disponibile: segmento pista troppo corto dopo la pulizia.")
        return ctx

    # 3) preparo dati PathLayer
    data = _build_pov_path(cleaned)

    # 4) setup Mapbox token (se presente)
    token = _get_mapbox_token()
    mapbox_active = bool(token)
    if mapbox_active:
        try:
            pdk.settings.mapbox_api_key = token
        except Exception:
            mapbox_active = False

    # 5) centro la vista circa a metà pista
    mid = cleaned[len(cleaned) // 2]
    center_lat = float(mid["lat"])
    center_lon = float(mid["lon"])

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=13,
        pitch=60,
        bearing=-45,
    )

    # 6) PathLayer + marker partenza
    line_layer = pdk.Layer(
        "PathLayer",
        data=data,
        get_path="path",
        get_color=[255, 80, 40],
        width_scale=4,
        width_min_pixels=3,
        pickable=False,
    )

    start = cleaned[0]
    start_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lon": start["lon"], "lat": start["lat"]}],
        get_position="[lon, lat]",
        get_radius=40,
        get_fill_color=[0, 255, 100],
        pickable=False,
    )

    if mapbox_active:
        map_style = "mapbox://styles/mapbox/satellite-v9"
    else:
        map_style = "light"  # stile base generico

    deck = pdk.Deck(
        layers=[line_layer, start_layer],
        initial_view_state=view_state,
        map_style=map_style,
        tooltip={"text": "Tracciato POV pista"},
    )

    st.pydeck_chart(deck)

    piste_name = ctx.get("pov_piste_name") or ctx.get("selected_piste_name") or "pista selezionata"

    if mapbox_active:
        prefix = token[:3] + "…" if len(token) >= 3 else "pk…"
        st.caption(
            f"POV 3D della pista {piste_name} "
            f"(satellite · Mapbox key attiva, prefisso: {prefix})."
        )
    else:
        st.caption(
            f"POV 3D della pista {piste_name} "
            f"(tracciato 3D su base map generica, senza sfondo satellite Mapbox)."
        )

    return ctx
