# core/maps.py
# Mappa + piste sci alpino per Telemark · Pro Wax & Tune
#
# - Folium + streamlit_folium
# - Tile OSM + Satellite
# - Piste da Overpass (solo sci alpino / downhill)
# - Puntatore agganciato alla pista più vicina (se presente)
#   e SEMPRE sincronizzato con ctx['lat'], ctx['lon']

from __future__ import annotations

import math
from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/2.0"}
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# -------------------------------------------------------------------
# Utilità Geo
# -------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza approssimata in metri tra due punti."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _nearest_vertex(
    polylines: List[List[Tuple[float, float]]],
    lat: float,
    lon: float,
) -> Optional[Tuple[float, float]]:
    """Trova il vertice di pista più vicino al punto dato."""
    best = None
    best_d = 1e12
    for line in polylines:
        for la, lo in line:
            d = _haversine_m(lat, lon, la, lo)
            if d < best_d:
                best_d = d
                best = (la, lo)
    return best


# -------------------------------------------------------------------
# Overpass: scarica piste alpine
# -------------------------------------------------------------------
def _is_downhill(tags: Dict[str, str]) -> bool:
    """
    Filtra SOLO piste di sci alpino / discesa.
    - piste:type = downhill / alpine
    - oppure route=piste con piste:difficulty presente
    """
    t = (tags.get("piste:type") or "").lower()
    route = (tags.get("route") or "").lower()

    if t in {"downhill", "alpine"}:
        return True

    if route == "piste" and tags.get("piste:difficulty"):
        return True

    return False


def _fetch_pistes_alpine(
    lat: float,
    lon: float,
    radius_km: float = 12.0,
) -> Tuple[List[List[Tuple[float, float]]], int]:
    """
    Ritorna:
      - lista di polilinee [ [(lat,lon), ...], ... ] per piste alpine
      - numero di elementi grezzi Overpass
    """
    r_m = int(radius_km * 1000)

    query = f"""
[out:json][timeout:30];
(
  way["piste:type"](around:{r_m},{lat},{lon});
  relation["piste:type"](around:{r_m},{lat},{lon});
  way["route"="piste"](around:{r_m},{lat},{lon});
);
out body;
>;
out skel qt;
"""

    try:
        resp = requests.get(
            OVERPASS_URL,
            params={"data": query},
            headers=UA,
            timeout=30,
        )
        resp.raise_for_status()
        js = resp.json() or {}
    except Exception:
        return [], 0

    elems = js.get("elements") or []
    nodes: Dict[int, Tuple[float, float]] = {}
    ways: Dict[int, Dict[str, Any]] = {}

    for el in elems:
        if el.get("type") == "node":
            nodes[el["id"]] = (float(el["lat"]), float(el["lon"]))
        elif el.get("type") == "way":
            ways[el["id"]] = el

    polylines: List[List[Tuple[float, float]]] = []

    # ways diretti
    for w in ways.values():
        tags = w.get("tags", {})
        if not _is_downhill(tags):
            continue
        coords = [
            nodes[nid] for nid in w.get("nodes", []) if nid in nodes
        ]
        if len(coords) >= 2:
            polylines.append(coords)

    # relations che raggruppano più ways
    for el in elems:
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {})
        if not _is_downhill(tags):
            continue
        coords: List[Tuple[float, float]] = []
        for m in el.get("members", []):
            if m.get("type") == "way":
                w = ways.get(m.get("ref"))
                if not w:
                    continue
                coords.extend(
                    [nodes[nid] for nid in w.get("nodes", []) if nid in nodes]
                )
        if len(coords) >= 2:
            polylines.append(coords)

    return polylines, len(elems)


# -------------------------------------------------------------------
# RENDER MAP
# -------------------------------------------------------------------
def render_map(T, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa principale.
    Usa:
      - ctx['lat'], ctx['lon']
      - ctx['map_context'] per key univoco su Streamlit
    Aggiorna ctx e st.session_state con ultimi lat/lon (snap a pista).
    """
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))
    map_context = ctx.get("map_context", "default")

    # checkbox per piste
    show_pistes = st.checkbox(
        "Mostra piste sci alpino sulla mappa",
        value=True,
        key=f"chk_pistes_alpine_{map_context}",
    )

    pistes: List[List[Tuple[float, float]]] = []
    raw_count = 0

    if show_pistes:
        with st.spinner("Cerco piste sci alpino da OpenStreetMap…"):
            pistes, raw_count = _fetch_pistes_alpine(lat, lon)

        st.caption(
            f"Piste alpine trovate: {len(pistes)} "
            f"(elementi Overpass grezzi: {raw_count})"
        )

        if not pistes:
            st.warning(
                "Nessuna pista sci alpino trovata in questo comprensorio "
                "(OSM/Overpass)."
            )

    # Se ci sono piste, agganciamo il puntatore al vertice più vicino
    marker_lat = lat
    marker_lon = lon
    if pistes:
        snap = _nearest_vertex(pistes, lat, lon)
        if snap is not None:
            marker_lat, marker_lon = snap

    # costruiamo la mappa Folium
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    # base OSM
    folium.TileLayer(
        "OpenStreetMap",
        name="Mappa stradale",
        control=True,
    ).add_to(m)

    # satellite (Esri World Imagery)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles © Esri — Sources: Esri, DeLorme, NAVTEQ, USGS, Intermap, and others",
        name="Satellite",
        control=True,
    ).add_to(m)

    # layer piste
    if pistes:
        fg = folium.FeatureGroup(name="Piste sci alpino", show=True)
        for line in pistes:
            folium.PolyLine(
                locations=line,
                weight=3,
                opacity=0.9,
            ).add_to(fg)
        fg.add_to(m)

    # marker posizione attuale
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
        tooltip="Posizione selezionata",
    ).add_to(m)

    folium.LayerControl().add_to(m)

    # chiave univoca in base al contesto
    map_key = f"map_{map_context}"

    # usiamo st_folium solo per renderizzare; ignoro i click così
    # il puntatore segue SEMPRE il centro logico (località / gara)
    st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # sincronizza verso ctx + session_state (dopo eventuale snap a pista)
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    st.session_state["lat"] = marker_lat
    st.session_state["lon"] = marker_lon

    return ctx
