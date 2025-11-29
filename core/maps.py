# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill (+ nomi piste se presenti)
# - Puntatore che segue:
#     · selezione gara/località (via ctx["lat"]/["lon"])
#     · click sulla mappa (snap alla pista più vicina, se disponibile)
# - Ritorna ctx aggiornato (lat/lon + marker_lat/lon)

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# --------------------------------------------------
# UTILITÀ DISTANZE / SNAP
# --------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distanza approssimata in metri tra due coordinate (haversine).
    Precisione più che sufficiente per pochi km.
    """
    R = 6371000.0  # raggio medio Terra (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        dlambda / 2.0
    ) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def _snap_to_nearest_piste_point(
    click_lat: float,
    click_lon: float,
    pistes: List[Dict[str, Any]],
    max_snap_distance_m: float = 400.0,
) -> Tuple[float, float]:
    """
    Trova il punto più vicino sulle piste (come insieme di vertici) e restituisce
    quelle coordinate. Se non c'è nulla entro max_snap_distance_m, ritorna il click.
    """
    best_lat = click_lat
    best_lon = click_lon
    best_d = max_snap_distance_m + 1.0

    for piste in pistes:
        coords: List[Tuple[float, float]] = piste.get("coords", [])
        for plat, plon in coords:
            d = _haversine_m(click_lat, click_lon, plat, plon)
            if d < best_d:
                best_d = d
                best_lat = plat
                best_lon = plon

    if best_d <= max_snap_distance_m:
        return best_lat, best_lon
    return click_lat, click_lon


# --------------------------------------------------
# OVERPASS: PISTE DOWNHILL
# --------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float, lon: float, radius_km: float = 10.0
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.

    Ritorna:
      - numero di piste
      - lista di dict:
          {
            "coords": [(lat, lon), ...],
            "name": "Nome pista" oppure "Pista N",
          }
    """
    radius_m = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way["piste:type"="downhill"](around:{radius_m},{lat},{lon});
      relation["piste:type"="downhill"](around:{radius_m},{lat},{lon});
    );
    (._;>;);
    out body;
    """

    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query.encode("utf-8"),
            headers=UA,
            timeout=25,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return 0, []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    pistes: List[Dict[str, Any]] = []
    piste_count = 0

    # Per associare un id way/relation alle sue tag (nome pista, ecc.)
    way_tags = {
        el["id"]: el.get("tags", {})
        for el in elements
        if el.get("type") == "way"
    }
    rel_tags = {
        el["id"]: el.get("tags", {})
        for el in elements
        if el.get("type") == "relation"
    }

    for el in elements:
        el_type = el.get("type")
        if el_type not in ("way", "relation"):
            continue

        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        coords: List[Tuple[float, float]] = []

        if el_type == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if not nd:
                    continue
                coords.append((nd["lat"], nd["lon"]))
            name = tags.get("name") or tags.get("piste:name")

        else:  # relation
            name = tags.get("name") or tags.get("piste:name")
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (
                        e
                        for e in elements
                        if e.get("type") == "way" and e.get("id") == wid
                    ),
                    None,
                )
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if not nd:
                        continue
                    coords.append((nd["lat"], nd["lon"]))

        if len(coords) < 2:
            continue

        piste_count += 1
        if not name:
            name = f"Pista {piste_count}"

        pistes.append({"coords": coords, "name": name})

    return piste_count, pistes


# --------------------------------------------------
# RENDER MAPPA
# --------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro di default
      - ctx["marker_lat"], ["marker_lon"] → puntatore (fallback = lat/lon)
      - ctx["map_context"] → usato solo per key widget (forza refresh)
    Ritorna ctx aggiornato con eventuale click sulla mappa.
    """
    # Coordinate di base / puntatore
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # Usa il contesto per separare stato local / race
    map_context = str(ctx.get("map_context", "default"))

    # Checkbox per mostrare piste
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # Crea mappa Folium
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    # Base OSM
    folium.TileLayer(
        "OpenStreetMap",
        name="Strade",
        control=True,
    ).add_to(m)

    # Satellite (Esri World Imagery)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m)

    piste_count = 0
    pistes: List[Dict[str, Any]] = []

    # Disegna piste + nomi
    if show_pistes:
        piste_count, pistes = _fetch_downhill_pistes(
            marker_lat, marker_lon, radius_km=10.0
        )

        for piste in pistes:
            coords = piste["coords"]
            name = piste["name"]

            # Linea della pista
            folium.PolyLine(
                locations=coords,
                weight=3,
                opacity=0.9,
            ).add_to(m)

            # Etichetta al centro pista (DivIcon molto piccolo)
            mid_idx = len(coords) // 2
            mid_lat, mid_lon = coords[mid_idx]
            folium.Marker(
                location=[mid_lat, mid_lon],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:8px; color:white; '
                        f'text-shadow:0 0 3px black; white-space:nowrap;">'
                        f'{name}</div>'
                    )
                ),
            ).add_to(m)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # Puntatore (marker rosso)
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Render mappa in Streamlit
    map_key = f"map_{map_context}"
    map_data = st_folium(m, height=450, width=None, key=map_key)

    # --- Gestione click: aggiorna puntatore, ctx e sessione ---
    last_clicked: Optional[Dict[str, float]] = None
    if isinstance(map_data, dict):
        last_clicked = map_data.get("last_clicked")

    if last_clicked:
        click_lat = float(last_clicked.get("lat"))
        click_lon = float(last_clicked.get("lng"))

        # Snap alla pista più vicina se visibile, altrimenti usa il click
        if show_pistes and pistes:
            new_lat, new_lon = _snap_to_nearest_piste_point(
                click_lat, click_lon, pistes
            )
        else:
            new_lat, new_lon = click_lat, click_lon

        # Aggiorna ctx
        ctx["marker_lat"] = new_lat
        ctx["marker_lon"] = new_lon
        ctx["lat"] = new_lat
        ctx["lon"] = new_lon

        # Aggiorna anche session_state (separato per contesto + globale)
        st.session_state[f"marker_lat_{map_context}"] = new_lat
        st.session_state[f"marker_lon_{map_context}"] = new_lon
        st.session_state["lat"] = new_lat
        st.session_state["lon"] = new_lon

    else:
        # Nessun click: assicuriamoci di sincronizzare ctx con lo stato corrente
        ctx["marker_lat"] = marker_lat
        ctx["marker_lon"] = marker_lon
        ctx["lat"] = marker_lat
        ctx["lon"] = marker_lon

    return ctx
