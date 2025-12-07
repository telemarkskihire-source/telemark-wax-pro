# core/maps.py
# Mappa & piste Telemark – versione FINALE
#
# - Nessuna pista selezionata al primo load (zero rosso automatico)
# - Snap dinamico alla pista più vicina sul click
# - Zoom iniziale vicino (15)
# - Nessuna duplicazione nomi
# - Esporta sempre ctx["pov_piste_points"] per POV 2D/3D/VIDEO

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional
import math

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.1"}

# raggio snap base (zoom vicino)
BASE_SNAP_M = 300.0


# ----------------------------------------------------------------------
# Utility distanza
# ----------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza approssimata in metri (haversine)."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


# ----------------------------------------------------------------------
# Snap dinamico basato sullo zoom
# ----------------------------------------------------------------------
def _snap_radius(prev_state: Optional[Dict[str, Any]]) -> float:
    """Raggio di snap (m) in base allo zoom corrente salvato da st_folium."""
    if not isinstance(prev_state, dict):
        return BASE_SNAP_M
    z = prev_state.get("zoom")
    if not isinstance(z, (int, float)):
        return BASE_SNAP_M

    z = float(z)
    if z <= 10:
        return 2500.0
    if z <= 12:
        return 1500.0
    if z <= 14:
        return 600.0
    return BASE_SNAP_M


# ----------------------------------------------------------------------
# Fetch piste da Overpass
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_pistes(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
) -> Tuple[int, List[List[Tuple[float, float]]], List[Optional[str]]]:
    """
    Scarica piste:type=downhill attorno a (lat, lon) entro radius_km.

    Ritorna:
      - numero segmenti
      - lista polilinee [ [(lat,lon), ...], ... ]
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
            data=query.encode("utf-8"),
            headers=UA,
            timeout=25,
        )
        r.raise_for_status()
        js = r.json() or {}
    except Exception:
        return 0, [], []

    elements = js.get("elements", [])
    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}

    polylines: List[List[Tuple[float, float]]] = []
    names: List[Optional[str]] = []
    count = 0

    def _name_from_tags(tags: Dict[str, Any]) -> Optional[str]:
        if not tags:
            return None
        for key in ("name", "piste:name", "ref"):
            val = tags.get(key)
            if val:
                s = str(val).strip()
                if s:
                    return s
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
                if nd:
                    coords.append((float(nd["lat"]), float(nd["lon"])))
        else:  # relation
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (w for w in elements if w.get("type") == "way" and w.get("id") == wid),
                    None,
                )
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if nd:
                        coords.append((float(nd["lat"]), float(nd["lon"])))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_name_from_tags(tags))
            count += 1

    return count, polylines, names


# ----------------------------------------------------------------------
# RENDER MAPPA COMPLETA
# ----------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mappa principale:
      - Nessuna pista selezionata al primo load
      - Click → snap alla pista più vicina (entro raggio dinamico)
      - Lista piste opzionale
      - Esporta ctx["pov_piste_points"] per POV 2D/3D/VIDEO
    """
    map_id = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_id}"
    sel_key = f"selected_piste_{map_id}"

    # ---------- LOCALITÀ BASE (centro query Overpass – fisso per la sessione) ----------
    base_lat = float(ctx.get("base_lat", ctx.get("lat", 45.83333)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", 7.73333)))

    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # posizione marker visivo (può essere spostata da click)
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # ---------- NOME PISTA SELEZIONATA ----------
    # IMPORTANTE: al primo load per questo map_id NON selezioniamo nulla.
    selected_name = st.session_state.get(sel_key)
    if not isinstance(selected_name, str):
        selected_name = None

    # ---------- CARICO PISTE ----------
    segment_count, polylines, names = _fetch_pistes(base_lat, base_lon, radius_km=5.0)

    # solo piste con nome per la lista
    named_pairs = [(coords, nm) for coords, nm in zip(polylines, names) if nm]
    unique_names = sorted({nm for _, nm in named_pairs})

    # ---------- SNAP DINAMICO SU CLICK ----------
    prev_state = st.session_state.get(map_key)
    snap_r = _snap_radius(prev_state)

    if isinstance(prev_state, dict) and polylines:
        click = prev_state.get("last_clicked")
        # solo se l'utente ha cliccato davvero
        if click and isinstance(click, dict) and "lat" in click and "lng" in click:
            try:
                c_lat = float(click["lat"])
                c_lon = float(click["lng"])
            except Exception:
                c_lat = marker_lat
                c_lon = marker_lon

            best_d = float("inf")
            best_lat = c_lat
            best_lon = c_lon
            best_nm: Optional[str] = None

            for coords, nm in zip(polylines, names):
                for lat, lon in coords:
                    d = _dist_m(c_lat, c_lon, lat, lon)
                    if d < best_d:
                        best_d = d
                        best_lat = lat
                        best_lon = lon
                        best_nm = nm

            if best_d <= snap_r:
                marker_lat = best_lat
                marker_lon = best_lon
                if best_nm:
                    selected_name = best_nm

    # ---------- ZOOM INIZIALE ----------
    zoom_start = 15.0
    if isinstance(prev_state, dict):
        z = prev_state.get("zoom")
        if isinstance(z, (int, float)):
            zoom_start = float(z)

    # ---------- COSTRUZIONE MAPPA FOLIUM ----------
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=zoom_start,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer("OpenStreetMap", name="Strade", control=True).add_to(m)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m)

    folium.LayerControl().add_to(m)

    # ---------- DISEGNO PISTE ----------
    drawn_labels = set()

    for coords, nm in zip(polylines, names):
        is_selected = (nm is not None and nm == selected_name)

        folium.PolyLine(
            locations=coords,
            color="red" if is_selected else "blue",
            weight=6 if is_selected else 3,
            opacity=1.0 if is_selected else 0.6,
        ).add_to(m)

        # etichetta (una sola per nome)
        if nm and nm not in drawn_labels and coords:
            mid_idx = len(coords) // 2
            mid_lat, mid_lon = coords[mid_idx]
            folium.Marker(
                location=[mid_lat, mid_lon],
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size:10px;color:white;"
                        "text-shadow:0 0 3px black;"
                        "background:rgba(0,0,0,0.35);"
                        "padding:1px 3px;border-radius:3px;'>"
                        f"{nm}</div>"
                    )
                ),
            ).add_to(m)
            drawn_labels.add(nm)

    # ---------- MARKER UTENTE ----------
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # ---------- RENDER IN STREAMLIT ----------
    st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    st.caption(f"Piste downhill trovate: {segment_count} — raggio snap ≈ {int(snap_r)} m")

    # ---------- LISTA PISTE OPZIONALE ----------
    use_list = st.checkbox(
        "Attiva selezione da lista piste",
        value=False,
        key=f"use_piste_list_{map_id}",
    )

    if use_list and unique_names:
        if selected_name in unique_names:
            default_idx = unique_names.index(selected_name)
        else:
            default_idx = 0

        with st.expander(
            T.get("piste_select_label", "Seleziona pista dalla lista"),
            expanded=False,
        ):
            chosen_name = st.selectbox(
                "Pista",
                options=unique_names,
                index=default_idx,
                key=f"piste_select_{map_id}",
            )

        if chosen_name != selected_name:
            selected_name = chosen_name
            for coords, nm in named_pairs:
                if nm == selected_name and coords:
                    mid_idx = len(coords) // 2
                    marker_lat, marker_lon = coords[mid_idx]
                    break

    # ---------- SALVATAGGIO STATO ----------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected_name
    st.session_state[sel_key] = selected_name

    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
    else:
        st.markdown("**Pista selezionata:** nessuna (clicca sulla mappa o usa la lista)")

    # ---------- ESPORTAZIONE PER POV (2D/3D/VIDEO) ----------
    pov_points: Optional[List[Dict[str, float]]] = None
    if selected_name:
        for coords, nm in zip(polylines, names):
            if nm == selected_name:
                pov_points = [
                    {"lat": float(lat), "lon": float(lon), "elev": 0.0}
                    for (lat, lon) in coords
                ]
                break

    ctx["pov_piste_name"] = selected_name
    ctx["pov_piste_points"] = pov_points

    return ctx
