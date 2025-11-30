# core/maps.py
# Mappa + piste da Overpass per Telemark · Pro Wax & Tune

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# ---------------------------------------------------------
# Geometria di base
# ---------------------------------------------------------


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza approssimata in metri tra due (lat, lon)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _nearest_point_on_polyline(
    click_lat: float,
    click_lon: float,
    line: List[Tuple[float, float]],
) -> Tuple[float, Tuple[float, float]]:
    """
    Ritorna (distanza_min_m, (lat, lon) più vicino) su una singola polilinea.
    Usiamo un'approssimazione semplice: punto della polyline con distanza minore.
    """
    best_d = 1e12
    best_pt = line[0]
    for lat, lon in line:
        d = _haversine_m(click_lat, click_lon, lat, lon)
        if d < best_d:
            best_d = d
            best_pt = (lat, lon)
    return best_d, best_pt


def _snap_to_nearest_piste(
    click_lat: float,
    click_lon: float,
    lines: List[List[Tuple[float, float]]],
    max_dist_m: float = 200.0,
) -> Tuple[Optional[int], float, Optional[Tuple[float, float]]]:
    """
    Cerca la pista più vicina al click.
    Ritorna: (index_pista, distanza_m, punto_snap) — index_pista può essere None.
    """
    if not lines:
        return None, 1e12, None

    best_idx = None
    best_d = 1e12
    best_pt: Optional[Tuple[float, float]] = None

    for idx, line in enumerate(lines):
        d, pt = _nearest_point_on_polyline(click_lat, click_lon, line)
        if d < best_d:
            best_d = d
            best_pt = pt
            best_idx = idx

    if best_idx is None or best_d > max_dist_m:
        return None, best_d, None

    return best_idx, best_d, best_pt


# ---------------------------------------------------------
# Overpass: piste downhill
# ---------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float = 10.0,
) -> Tuple[int, List[List[Tuple[float, float]]], List[Optional[str]]]:
    """
    Scarica piste:type=downhill da Overpass attorno a (lat, lon).

    Ritorna:
      - num_piste
      - lista di polilinee [ [(lat, lon), ...], ... ]
      - lista nomi (stessa lunghezza, può contenere None)
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
            data={"data": query},
            headers=UA,
            timeout=30,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return 0, [], []

    elements = js.get("elements", [])
    nodes: Dict[int, Tuple[float, float]] = {}
    ways: Dict[int, Dict[str, Any]] = {}

    # indicizziamo nodes & ways
    for el in elements:
        if el.get("type") == "node":
            nid = el.get("id")
            nodes[nid] = (float(el.get("lat", 0.0)), float(el.get("lon", 0.0)))
        elif el.get("type") == "way":
            wid = el.get("id")
            ways[wid] = el

    polylines: List[List[Tuple[float, float]]] = []
    names: List[Optional[str]] = []

    # tutte le way downhill
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        if tags.get("piste:type") != "downhill":
            continue

        coords: List[Tuple[float, float]] = []
        for nid in el.get("nodes", []):
            if nid in nodes:
                coords.append(nodes[nid])

        if len(coords) < 2:
            continue

        name = (
            tags.get("piste:name")
            or tags.get("name")
            or tags.get("ref")
            or None
        )
        polylines.append(coords)
        names.append(name)

    # relations che raggruppano più ways
    for el in elements:
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {})
        if tags.get("piste:type") != "downhill":
            continue

        rel_coords: List[Tuple[float, float]] = []
        for mem in el.get("members", []):
            if mem.get("type") != "way":
                continue
            wid = mem.get("ref")
            way = ways.get(wid)
            if not way:
                continue
            for nid in way.get("nodes", []):
                if nid in nodes:
                    rel_coords.append(nodes[nid])

        if len(rel_coords) < 2:
            continue

        name = (
            tags.get("piste:name")
            or tags.get("name")
            or tags.get("ref")
            or None
        )
        polylines.append(rel_coords)
        names.append(name)

    return len(polylines), polylines, names


# ---------------------------------------------------------
# Stato mappa per contesto (località / gara)
# ---------------------------------------------------------


def _get_map_state_key(ctx: Dict[str, Any]) -> str:
    return f"map_state_{ctx.get('map_context', 'default')}"


def _load_map_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    key = _get_map_state_key(ctx)
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))
    if key not in st.session_state:
        st.session_state[key] = {
            "lat": base_lat,
            "lon": base_lon,
            "selected_idx": None,
        }
    return st.session_state[key]


def _save_map_state(ctx: Dict[str, Any], state: Dict[str, Any]) -> None:
    key = _get_map_state_key(ctx)
    st.session_state[key] = state


# ---------------------------------------------------------
# Render mappa principale
# ---------------------------------------------------------


def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna mappa Folium con piste.
    - Mostra piste se la checkbox è attiva.
    - Aggiorna marker ad ogni click.
    - Se vicino ad una pista (< 200 m) evidenzia la pista e la salva in ctx.
    """
    map_ctx = ctx.get("map_context", "default")

    state = _load_map_state(ctx)
    lat = float(state.get("lat", ctx.get("lat", 45.83333)))
    lon = float(state.get("lon", ctx.get("lon", 7.73333)))
    selected_idx: Optional[int] = state.get("selected_idx")

    # Checkbox per attivare/disattivare le piste
    show_pistes = st.checkbox(
        "Mostra piste sci alpino sulla mappa",
        value=True,
        key=f"show_pistes_{map_ctx}",
    )

    piste_count = 0
    piste_lines: List[List[Tuple[float, float]]] = []
    piste_names: List[Optional[str]] = []

    if show_pistes:
        piste_count, piste_lines, piste_names = _fetch_downhill_pistes(lat, lon)
    st.write(f"Piste downhill trovate: {piste_count}")

    # --- Crea mappa Folium ---
    fmap = folium.Map(
        location=(lat, lon),
        zoom_start=14,
        tiles="Esri.WorldImagery",
        control_scale=True,
    )

    # layer piste
    for idx, line in enumerate(piste_lines):
        if not line:
            continue
        is_selected = selected_idx is not None and idx == selected_idx
        color = "#ffd60a" if is_selected else "#38bdf8"  # giallo / azzurro
        weight = 5 if is_selected else 2

        folium.PolyLine(
            locations=line,
            color=color,
            weight=weight,
            opacity=0.9 if is_selected else 0.7,
        ).add_to(fmap)

        # aggiungiamo un'etichetta testuale semplice (primo punto)
        name = piste_names[idx]
        if name:
            folium.Marker(
                location=line[len(line) // 2],
                icon=folium.DivIcon(
                    html=f'<div style="color:white;font-size:10px;'
                    f'text-shadow:0 0 4px black;">{name}</div>'
                ),
            ).add_to(fmap)

    # marker centrale (sempre sulla posizione corrente, anche se non su pista)
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(fmap)

    # --- Mostra mappa e leggi click ---
    map_key = f"folium_{map_ctx}"
    map_data = st_folium(fmap, width=None, height=500, key=map_key)

    # Gestione click NUOVA: ad ogni click muovo SEMPRE il marker.
    if map_data and map_data.get("last_clicked"):
        click = map_data["last_clicked"]
        click_lat = float(click["lat"])
        click_lon = float(click["lng"])

        # Aggiorno sempre la posizione marker
        lat = click_lat
        lon = click_lon
        snapped_idx = None
        snapped_pt: Optional[Tuple[float, float]] = None

        # Se abbiamo piste, provo lo snap ma senza bloccare il movimento del marker
        if piste_lines:
            snapped_idx, dist_m, snapped_pt = _snap_to_nearest_piste(
                click_lat, click_lon, piste_lines, max_dist_m=200.0
            )
            if snapped_idx is not None and snapped_pt is not None:
                lat, lon = snapped_pt  # centra sulla pista
                selected_idx = snapped_idx

        # salva nuovo stato
        state["lat"] = lat
        state["lon"] = lon
        state["selected_idx"] = selected_idx
        _save_map_state(ctx, state)

    # Aggiorno ctx
    ctx["lat"] = state["lat"]
    ctx["lon"] = state["lon"]

    selected_name: Optional[str] = None
    if state.get("selected_idx") is not None:
        idx = int(state["selected_idx"])
        if 0 <= idx < len(piste_names):
            selected_name = piste_names[idx]

    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
        ctx["selected_piste_name"] = selected_name
    else:
        ctx.pop("selected_piste_name", None)

    return ctx
