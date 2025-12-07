# core/maps.py
# Mappa & piste Telemark – versione FULL CORRETTA (v3 + POV friendly)
#
# - Snap dinamico in base allo zoom
# - Zoom iniziale vicino (15)
# - Nessuna duplicazione nomi
# - Reset selezione pista quando cambi località (niente blob rosso all'avvio)
# - Esporta sempre ctx["pov_piste_points"] semplificato per POV 2D/3D

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional
import math

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.1"}

BASE_SNAP = 300.0          # raggio snap quando sei vicino (zoom 15+)
MAX_POV_POINTS = 120       # limitiamo la densità della traccia esportata


# ----------------------------------------------------------------------
# Utility distanza
# ----------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _simplify_coords(coords: List[Tuple[float, float]], max_points: int) -> List[Tuple[float, float]]:
    """
    Semplifica la lista di coordinate mantenendo max_points punti,
    distribuiti uniformemente lungo la linea.
    """
    n = len(coords)
    if n <= max_points:
        return coords

    step = (n - 1) / float(max_points - 1)
    out: List[Tuple[float, float]] = []
    for k in range(max_points):
        idx = int(round(k * step))
        if idx >= n:
            idx = n - 1
        out.append(coords[idx])
    return out


# ----------------------------------------------------------------------
# Snap dinamico basato sullo zoom
# ----------------------------------------------------------------------
def _snap_radius(prev: Optional[Dict[str, Any]]) -> float:
    if not isinstance(prev, dict):
        return BASE_SNAP
    z = prev.get("zoom")
    if not isinstance(z, (int, float)):
        return BASE_SNAP

    if z <= 10:
        return 2500
    if z <= 12:
        return 1500
    if z <= 14:
        return 600
    return BASE_SNAP


# ----------------------------------------------------------------------
# Fetch piste da Overpass
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_pistes(lat: float, lon: float, radius_km: float = 5.0):
    radius_m = int(radius_km * 1000)

    q = f"""
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
            data=q.encode("utf-8"),
            headers=UA,
            timeout=25,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return 0, [], []

    elements = js.get("elements", [])
    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}

    polylines: List[List[Tuple[float, float]]] = []
    names: List[Optional[str]] = []
    count = 0

    def _nm(tags: Optional[Dict[str, Any]]) -> Optional[str]:
        if not tags:
            return None
        for k in ("name", "piste:name", "ref"):
            v = tags.get(k)
            if v:
                return str(v).strip()
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
                    coords.append((nd["lat"], nd["lon"]))
        else:
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (w for w in elements if w.get("type") == "way" and w.get("id") == wid),
                    None,
                )
                if way:
                    for nid in way.get("nodes", []):
                        nd = nodes.get(nid)
                        if nd:
                            coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_nm(tags))
            count += 1

    return count, polylines, names


# ----------------------------------------------------------------------
# RENDER MAPPA COMPLETA
# ----------------------------------------------------------------------
def render_map(T, ctx: Dict[str, Any]) -> Dict[str, Any]:
    map_id = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_id}"
    sel_key = f"selected_piste_{map_id}"
    base_key = f"{map_key}_base_center"

    # Località base (centro piste)
    base_lat = float(ctx.get("base_lat", ctx.get("lat", 45.83333)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", 7.73333)))
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # Marker visuale
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # Se la località è cambiata significativamente → reset selezione pista
    prev_base = st.session_state.get(base_key)
    moved_far = False
    if isinstance(prev_base, dict):
        try:
            d = _dist_m(
                base_lat,
                base_lon,
                float(prev_base.get("lat", base_lat)),
                float(prev_base.get("lon", base_lon)),
            )
            moved_far = d > 1500.0  # > 1.5 km consideriamo "nuova località"
        except Exception:
            moved_far = False
    st.session_state[base_key] = {"lat": base_lat, "lon": base_lon}

    if moved_far:
        st.session_state[sel_key] = None
        ctx["selected_piste_name"] = None

    # Nome pista selezionata
    selected = st.session_state.get(sel_key, ctx.get("selected_piste_name"))

    # Carica piste
    count, polylines, names = _fetch_pistes(base_lat, base_lon)

    # Lista piste con nome
    named = [(c, n) for c, n in zip(polylines, names) if n]
    unique_names = sorted({n for _, n in named})

    # Snap dinamico
    prev = st.session_state.get(map_key)
    radius = _snap_radius(prev)

    # Se c'è un click → snap sulla pista più vicina
    if isinstance(prev, dict) and polylines:
        click = prev.get("last_clicked")
        if click:
            c_lat = float(click["lat"])
            c_lon = float(click["lng"])
            best_d = 1e12
            best_nm: Optional[str] = None
            best_lat = c_lat
            best_lon = c_lon

            for coords, nm in zip(polylines, names):
                for lat, lon in coords:
                    d = _dist_m(c_lat, c_lon, lat, lon)
                    if d < best_d:
                        best_d = d
                        best_lat = lat
                        best_lon = lon
                        best_nm = nm

            if best_d <= radius:
                marker_lat = best_lat
                marker_lon = best_lon
                if best_nm:
                    selected = best_nm

    # Zoom iniziale
    zoom = 15
    if isinstance(prev, dict) and isinstance(prev.get("zoom"), (int, float)):
        zoom = float(prev["zoom"])

    # Mappa Folium
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer("OpenStreetMap", name="Strade").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
    ).add_to(m)

    # Disegno piste
    added_labels = set()
    for coords, nm in zip(polylines, names):
        is_sel = (nm is not None) and (nm == selected)

        folium.PolyLine(
            locations=coords,
            color="red" if is_sel else "blue",
            weight=6 if is_sel else 3,
            opacity=1 if is_sel else 0.6,
        ).add_to(m)

        # Nome pista una sola volta (solo se ha nome)
        if nm and nm not in added_labels:
            mid = coords[len(coords) // 2]
            folium.Marker(
                location=[mid[0], mid[1]],
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size:10px;color:white;"
                        "text-shadow:0 0 3px black; background:rgba(0,0,0,.35);"
                        "padding:1px 3px;border-radius:3px;'>"
                        f"{nm}</div>"
                    )
                ),
            ).add_to(m)
            added_labels.add(nm)

    # Marker utente (centro click / snap)
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Render mappa
    st_folium(m, height=450, key=map_key)
    st.caption(f"Piste trovate: {count} — Snap ≈ {int(radius)} m")

    # Selettore da lista piste
    use_list = st.checkbox(
        "Attiva selezione da lista piste",
        value=False,
        key=f"use_list_{map_id}",
    )

    if use_list and unique_names:
        default = unique_names.index(selected) if selected in unique_names else 0
        with st.expander("Seleziona pista dalla lista"):
            chosen = st.selectbox(
                "Pista", unique_names, index=default, key=f"list_{map_id}"
            )
        if chosen != selected:
            selected = chosen
            for coords, nm in named:
                if nm == selected:
                    mid = coords[len(coords) // 2]
                    marker_lat, marker_lon = mid
                    break

    # Salvo in ctx e sessione
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected
    st.session_state[sel_key] = selected

    st.markdown(f"**Pista selezionata:** {selected or 'Nessuna'}")

    # ------------------------------------------------------------------
    # ESPORTAZIONE PER POV 2D/3D
    # ------------------------------------------------------------------
    pov_points = None
    if selected:
        for coords, nm in zip(polylines, names):
            if nm == selected:
                simp = _simplify_coords(coords, MAX_POV_POINTS)
                pov_points = [{"lat": lat, "lon": lon, "elev": 0.0} for lat, lon in simp]
                break

    ctx["pov_piste_name"] = selected
    ctx["pov_piste_points"] = pov_points

    return ctx
