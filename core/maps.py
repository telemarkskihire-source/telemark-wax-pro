# core/maps.py
# Telemark · Pro Wax & Tune — versione D fixata (puntatore reattivo + snap corretto + fetch piste una volta sola)

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ----------------------------------------------------------------------
# OVERPASS (cache una sola volta per località)
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_pistes_once(center_lat: float, center_lon: float) -> Tuple[int, List[List[Tuple[float, float]]], List[Optional[str]]]:
    """Scarica piste una volta sola per centro località/gara."""
    radius_km = 10.0
    radius_m = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way["piste:type"="downhill"](around:{radius_m},{center_lat},{center_lon});
      relation["piste:type"="downhill"](around:{radius_m},{center_lat},{center_lon});
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
        for k in ("name", "piste:name", "ref"):
            if k in tags and str(tags[k]).strip():
                return str(tags[k]).strip()
        return None

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        coords = []

        if el["type"] == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if nd:
                    coords.append((nd["lat"], nd["lon"]))

        elif el["type"] == "relation":
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next((e for e in elements if e.get("type") == "way" and e.get("id") == wid), None)
                if way:
                    for nid in way.get("nodes", []):
                        nd = nodes.get(nid)
                        if nd:
                            coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_name_from_tags(tags))
            piste_count += 1

    return piste_count, polylines, names


# ----------------------------------------------------------------------
# Distance + snapping
# ----------------------------------------------------------------------
def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi/2)**2 +
        math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def snap_to_piste(click_lat, click_lon, polylines, max_snap_m=400.0):
    """Snap SOLO al click."""
    best_lat, best_lon = click_lat, click_lon
    best_dist = float("inf")
    best_idx = None

    for idx, line in enumerate(polylines):
        for pt_lat, pt_lon in line:
            d = _haversine_m(click_lat, click_lon, pt_lat, pt_lon)
            if d < best_dist:
                best_dist = d
                best_lat, best_lon = pt_lat, pt_lon
                best_idx = idx

    if best_dist <= max_snap_m:
        return best_lat, best_lon, best_idx, best_dist

    return click_lat, click_lon, None, None


# ----------------------------------------------------------------------
# MAPPA PRINCIPALE
# ----------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Versione D — identica alla tua, ma corretta e fluida."""

    map_context = str(ctx.get("map_context", "default"))

    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    selected_idx_key = f"selected_piste_idx_{map_context}"
    map_key = f"map_{map_context}"

    # centro località/gara = BASE PISTE
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    # marker attuale
    marker_lat = float(st.session_state.get(marker_lat_key, base_lat))
    marker_lon = float(st.session_state.get(marker_lon_key, base_lon))

    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon

    # checkbox piste
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    piste_count, polylines, piste_names = (0, [], [])
    if show_pistes:
        piste_count, polylines, piste_names = fetch_pistes_once(base_lat, base_lon)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # costruzione mappa
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer("OpenStreetMap", name="Strade", control=True).add_to(m)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri",
        name="Satellite",
        control=True,
    ).add_to(m)

    # piste
    selected_idx = st.session_state.get(selected_idx_key, None)
    if show_pistes and polylines:
        for i, (coords, name) in enumerate(zip(polylines, piste_names)):
            is_selected = selected_idx == i

            kw = {
                "locations": coords,
                "weight": 5 if is_selected else 3,
                "opacity": 1.0 if is_selected else 0.9,
                "color": "yellow" if is_selected else "blue",
            }

            folium.PolyLine(**kw).add_to(m)

            if name:
                mid = len(coords) // 2
                tlat, tlon = coords[mid]

                html = (
                    f'<div style="font-size:10px; color:#fff; text-shadow:0 0 4px #000">'
                    f"{name}</div>"
                )

                folium.Marker(
                    location=[tlat, tlon],
                    icon=folium.DivIcon(html=html),
                ).add_to(m)

    # marker utente
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # render + click
    map_data = st_folium(m, height=450, width=None, key=map_key)

    if isinstance(map_data, dict) and map_data.get("last_clicked"):
        c = map_data["last_clicked"]

        try:
            click_lat = float(c.get("lat"))
            click_lon = float(c.get("lng"))
        except:
            click_lat, click_lon = marker_lat, marker_lon

        # snap SOLO quando clicchi
        if show_pistes and polylines:
            new_lat, new_lon, idx, dist = snap_to_piste(click_lat, click_lon, polylines)
        else:
            new_lat, new_lon, idx, dist = click_lat, click_lon, None, None

        # aggiorna marker
        marker_lat, marker_lon = new_lat, new_lon
        st.session_state[marker_lat_key] = marker_lat
        st.session_state[marker_lon_key] = marker_lon

        ctx["lat"] = marker_lat
        ctx["lon"] = marker_lon
        ctx["marker_lat"] = marker_lat
        ctx["marker_lon"] = marker_lon

        # pista selezionata
        if idx is not None:
            st.session_state[selected_idx_key] = idx
            ctx["selected_piste_name"] = piste_names[idx] or "pista senza nome"
            ctx["selected_piste_distance_m"] = dist
        else:
            st.session_state[selected_idx_key] = None
            ctx["selected_piste_name"] = None
            ctx["selected_piste_distance_m"] = None

    # info pista sotto la mappa
    idx = st.session_state.get(selected_idx_key)
    if (show_pistes and polylines and idx is not None and 0 <= idx < len(piste_names)):
        nm = piste_names[idx] or "pista senza nome"
        dist = ctx.get("selected_piste_distance_m")
        if dist:
            st.markdown(f"**Pista selezionata:** {nm} (~{dist:.0f} m)")
        else:
            st.markdown(f"**Pista selezionata:** {nm}")

    return ctx
