# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che:
#     · parte dalla località selezionata (ctx["lat"], ctx["lon"])
#     · si aggiorna al click
#     · viene "agganciato" al punto più vicino di una pista downhill
# - Evidenzia la pista selezionata (colore diverso / più spessa)
# - Nomi piste SEMPRE visibili in mappa
# - Mostra il nome della pista selezionata sotto la mappa
# - Marker separato per ogni contesto (ctx["map_context"])
# - Ritorna ctx aggiornato (lat/lon + marker_lat/lon + selected_piste_name)

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ----------------------------------------------------------------------
# Overpass: fetch piste downhill (cache generica)
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float,
) -> Tuple[int, List[List[Tuple[float, float]]], List[Optional[str]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.

    Ritorna:
      - numero di piste
      - lista di polilinee, ciascuna come lista di (lat, lon)
      - lista nomi (stessa lunghezza delle polilinee, può contenere None)
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
        return 0, [], []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    polylines: List[List[Tuple[float, float]]] = []
    names: List[Optional[str]] = []
    piste_count = 0

    def _name_from_tags(tags: Dict[str, Any]) -> Optional[str]:
        if not tags:
            return None
        for key in ("name", "piste:name", "ref"):
            if key in tags:
                val = str(tags[key]).strip()
                if val:
                    return val
        return None

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        coords: List[Tuple[float, float]] = []

        if el["type"] == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if not nd:
                    continue
                coords.append((nd["lat"], nd["lon"]))

        elif el["type"] == "relation":
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (e for e in elements if e.get("type") == "way" and e.get("id") == wid),
                    None,
                )
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if not nd:
                        continue
                    coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_name_from_tags(tags))
            piste_count += 1

    return piste_count, polylines, names


# ----------------------------------------------------------------------
# Utility: distanza e snapping alla pista più vicina
# ----------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distanza approssimata in metri tra due punti (lat/lon in gradi).
    """
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


def _snap_to_nearest_piste_point(
    click_lat: float,
    click_lon: float,
    polylines: List[List[Tuple[float, float]]],
    max_snap_m: float = 200.0,
) -> Tuple[float, float, Optional[int], Optional[float]]:
    """
    Trova il punto più vicino tra tutte le piste downhill.
    Se la distanza minima è <= max_snap_m:
        - ritorna (lat_snapped, lon_snapped, index_pista, distanza_m)
    Altrimenti:
        - ritorna (click_lat, click_lon, None, None)
    """
    best_lat = click_lat
    best_lon = click_lon
    best_dist = float("inf")
    best_idx: Optional[int] = None

    for idx, line in enumerate(polylines):
        for pt_lat, pt_lon in line:
            d = _haversine_m(click_lat, click_lon, pt_lat, pt_lon)
            if d < best_dist:
                best_dist = d
                best_lat = pt_lat
                best_lon = pt_lon
                best_idx = idx

    if best_idx is not None and best_dist <= max_snap_m:
        return best_lat, best_lon, best_idx, best_dist

    return click_lat, click_lon, None, None


# ----------------------------------------------------------------------
# Funzione principale chiamata dalla app
# ----------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro iniziale
      - ctx["marker_lat"], ["marker_lon"] → puntatore (fallback = lat/lon)
      - ctx["map_context"] → usato per separare lo stato fra pagine

    Ritorna ctx aggiornato con eventuale click sulla mappa.
    """
    map_context = str(ctx.get("map_context", "default"))
    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    map_key = f"map_{map_context}"
    selected_piste_idx_key = f"selected_piste_idx_{map_context}"

    # posizione base (centro comprensorio): usata per caricare le piste una volta sola
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    # posizione marker
    marker_lat = float(st.session_state.get(marker_lat_key, base_lat))
    marker_lon = float(st.session_state.get(marker_lon_key, base_lon))

    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon

    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # ------------------------------------------------------------------
    # Checkbox per piste & fetch piste (una volta per località)
    # ------------------------------------------------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    piste_count = 0
    polylines: List[List[Tuple[float, float]]] = []
    piste_names: List[Optional[str]] = []

    if show_pistes:
        piste_count, polylines, piste_names = _fetch_downhill_pistes(
            base_lat,
            base_lon,
            radius_km=10.0,
        )

    st.caption(f"Piste downhill trovate: {piste_count}")

    selected_idx: Optional[int] = st.session_state.get(selected_piste_idx_key, None)
    selected_dist_m: Optional[float] = ctx.get("selected_piste_distance_m")

    # ------------------------------------------------------------------
    # Costruisco la mappa Folium con il marker attuale
    # ------------------------------------------------------------------
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    # Base OSM
    folium.TileLayer("OpenStreetMap", name="Strade", control=True).add_to(m)

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

    # piste con tooltip nome + LABEL SEMPRE VISIBILE + highlight pista selezionata
    if show_pistes and polylines:
        for i, (coords, name) in enumerate(zip(polylines, piste_names)):
            is_selected = selected_idx is not None and i == selected_idx

            line_kwargs = {
                "locations": coords,
                "weight": 5 if is_selected else 3,
                "opacity": 1.0 if is_selected else 0.9,
                "color": "yellow" if is_selected else "blue",
            }

            folium.PolyLine(**line_kwargs).add_to(m)

            # LABEL fissa al centro pista
            if name:
                mid_idx = len(coords) // 2
                label_lat, label_lon = coords[mid_idx]

                text_color = "#fde047" if is_selected else "#e5e7eb"
                font_weight = "bold" if is_selected else "normal"

                html = (
                    f'<div style="'
                    f'font-size:10px; '
                    f'color:{text_color}; '
                    f'font-weight:{font_weight}; '
                    f'text-shadow:0 0 3px #000, 0 0 5px #000;'
                    f'">'
                    f"{name}"
                    f"</div>"
                )

                folium.Marker(
                    location=[label_lat, label_lon],
                    icon=folium.DivIcon(html=html),
                ).add_to(m)

    # marker puntatore
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # ------------------------------------------------------------------
    # Render Folium e leggo il click QUI (direttamente dal valore di ritorno)
    # ------------------------------------------------------------------
    map_data = st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # Gestiamo click utente sulla mappa
    if isinstance(map_data, dict) and map_data.get("last_clicked"):
        click = map_data["last_clicked"]
        try:
            click_lat = float(click.get("lat"))
            click_lon = float(click.get("lng"))
        except Exception:
            click_lat = marker_lat
            click_lon = marker_lon

        # Per lo SNAP usiamo un fetch locale (raggio 5 km) centrato sul click
        snap_polylines: List[List[Tuple[float, float]]] = []
        snap_names: List[Optional[str]] = []
        snap_count = 0

        if show_pistes:
            snap_count, snap_polylines, snap_names = _fetch_downhill_pistes(
                click_lat,
                click_lon,
                radius_km=5.0,
            )

        if show_pistes and snap_polylines:
            snapped_lat, snapped_lon, idx, dist_m = _snap_to_nearest_piste_point(
                click_lat,
                click_lon,
                snap_polylines,
                max_snap_m=200.0,
            )
        else:
            snapped_lat, snapped_lon, idx, dist_m = click_lat, click_lon, None, None

        # aggiorna ctx + session con posizione (snappata o no)
        marker_lat = snapped_lat
        marker_lon = snapped_lon

        ctx["lat"] = marker_lat
        ctx["lon"] = marker_lon
        ctx["marker_lat"] = marker_lat
        ctx["marker_lon"] = marker_lon
        st.session_state[marker_lat_key] = marker_lat
        st.session_state[marker_lon_key] = marker_lon

        # salva la pista selezionata (se c'è)
        if idx is not None and snap_names:
            selected_idx = idx
            st.session_state[selected_piste_idx_key] = idx
            selected_dist_m = dist_m
            ctx["selected_piste_distance_m"] = dist_m
            ctx["selected_piste_name"] = snap_names[idx] or "pista senza nome"
        else:
            selected_idx = None
            st.session_state[selected_piste_idx_key] = None
            ctx["selected_piste_distance_m"] = None
            ctx["selected_piste_name"] = None

    # ------------------------------------------------------------------
    # Info pista selezionata sotto la mappa
    # ------------------------------------------------------------------
    if ctx.get("selected_piste_name"):
        if ctx.get("selected_piste_distance_m") is not None:
            st.markdown(
                f"**Pista selezionata:** {ctx['selected_piste_name']} "
                f"(~{ctx['selected_piste_distance_m']:.0f} m dal punto cliccato)"
            )
        else:
            st.markdown(f"**Pista selezionata:** {ctx['selected_piste_name']}")

    return ctx
