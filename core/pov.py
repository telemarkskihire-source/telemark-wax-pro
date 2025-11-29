# core/pov.py
# POV pista per Telemark · Pro Wax & Tune
#
# - Usa Overpass per trovare la pista downhill più vicina al marker attuale
# - Calcola un profilo distanza lungo la pista
# - Mostra una mappa Folium separata con:
#     · tutta la pista in evidenza
#     · un marker che si muove lungo la pista in base a uno slider 0–100%
# - Mostra lunghezza totale stimata e posizione attuale
#
# NOTE:
# - Non tocca core/maps.py
# - Si appoggia solo a ctx["lat"]/["lon"] o ctx["marker_lat"]/["marker_lon"]

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ----------------------------------------------------------------------
# Overpass: fetch piste downhill
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float = 10.0,
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
            # seguiamo tutte le way membri
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
# Utility: distanza lungo pista
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


def _distance_profile(polyline: List[Tuple[float, float]]) -> Tuple[List[float], float]:
    """
    Calcola le distanze cumulative lungo la pista.
    Ritorna:
      - lista distanze cumulative (m) per ogni punto
      - lunghezza totale (m)
    """
    if not polyline:
        return [], 0.0

    dists = [0.0]
    total = 0.0
    for i in range(1, len(polyline)):
        lat1, lon1 = polyline[i - 1]
        lat2, lon2 = polyline[i]
        seg = _haversine_m(lat1, lon1, lat2, lon2)
        total += seg
        dists.append(total)
    return dists, total


def _nearest_piste_to_point(
    lat: float,
    lon: float,
    polylines: List[List[Tuple[float, float]]],
) -> Tuple[Optional[int], Optional[float]]:
    """
    Trova la pista il cui punto è più vicino a (lat, lon).

    Ritorna:
      - indice pista nella lista polylines (o None)
      - distanza minima in metri (o None)
    """
    best_idx: Optional[int] = None
    best_dist = float("inf")

    for i, line in enumerate(polylines):
        for pt_lat, pt_lon in line:
            d = _haversine_m(lat, lon, pt_lat, pt_lon)
            if d < best_dist:
                best_dist = d
                best_idx = i

    if best_idx is None:
        return None, None
    return best_idx, best_dist


# ----------------------------------------------------------------------
# POV VIEW
# ----------------------------------------------------------------------
def render_pov_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    POV semplificato:
      - prende ctx["marker_lat"] / ctx["marker_lon"] (o ctx["lat"]/["lon"])
      - trova la pista downhill più vicina
      - mostra slider 0–100% per muovere un marker lungo la pista
      - mostra lunghezza totale stimata
    """
    st.markdown("### 🎥 POV pista (beta)")

    # posizione di riferimento (marker, altrimenti centro)
    base_lat = float(ctx.get("marker_lat", ctx.get("lat", 45.83333)))
    base_lon = float(ctx.get("marker_lon", ctx.get("lon", 7.73333)))

    enable_pov = st.checkbox(
        "Attiva POV sulla pista più vicina",
        value=True,
        key="pov_enable",
    )
    if not enable_pov:
        return ctx

    with st.spinner("Cerco la pista downhill più vicina per il POV…"):
        piste_count, polylines, names = _fetch_downhill_pistes(
            base_lat,
            base_lon,
            radius_km=10.0,
        )

    if piste_count == 0 or not polylines:
        st.info("Nessuna pista downhill trovata nei dintorni per il POV.")
        return ctx

    # pista più vicina al marker
    piste_idx, dist_m = _nearest_piste_to_point(base_lat, base_lon, polylines)
    if piste_idx is None:
        st.info("Non sono riuscito a trovare una pista vicina per il POV.")
        return ctx

    piste_points = polylines[piste_idx]
    piste_name = names[piste_idx] if piste_idx < len(names) else None

    dists, total_len_m = _distance_profile(piste_points)
    if not dists or total_len_m <= 0:
        st.info("Profilo distanza pista non disponibile per il POV.")
        return ctx

    # slider posizione lungo la pista (0–100%)
    col_slider, col_info = st.columns([2, 1])
    with col_slider:
        progress_pct = st.slider(
            "Posizione lungo la pista",
            min_value=0,
            max_value=100,
            value=0,
            step=1,
            key="pov_progress_pct",
        )
    with col_info:
        st.write(" ")
        st.write(" ")
        st.markdown(
            f"**Lunghezza pista stimata:** ~{total_len_m/1000:.2f} km"
        )

    # converte percentuale in indice punto
    target_dist = (progress_pct / 100.0) * total_len_m
    idx = 0
    while idx < len(dists) - 1 and dists[idx] < target_dist:
        idx += 1
    idx = max(0, min(idx, len(piste_points) - 1))
    cur_lat, cur_lon = piste_points[idx]

    # salva contesto POV
    ctx["pov_piste_name"] = piste_name
    ctx["pov_piste_length_m"] = total_len_m
    ctx["pov_progress_pct"] = progress_pct
    ctx["pov_lat"] = cur_lat
    ctx["pov_lon"] = cur_lon

    # costruisci mappa dedicata POV
    pov_map_key = f"pov_map_{ctx.get('map_context', 'default')}"

    m = folium.Map(
        location=[cur_lat, cur_lon],
        zoom_start=14,
        tiles=None,
        control_scale=True,
    )

    # tile layer
    folium.TileLayer(
        "OpenStreetMap",
        name="Strade",
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m)

    # tutta la pista (linea blu)
    folium.PolyLine(
        locations=piste_points,
        weight=4,
        opacity=0.9,
        color="blue",
    ).add_to(m)

    # marker POV (pallino + icona play)
    folium.Marker(
        location=[cur_lat, cur_lon],
        icon=folium.Icon(color="red", icon="play"),
    ).add_to(m)

    # piccolo label con nome pista al centro
    mid_idx = len(piste_points) // 2
    mid_lat, mid_lon = piste_points[mid_idx]
    if piste_name:
        html = (
            '<div style="font-size:10px; color:#e5e7eb; '
            'text-shadow:0 0 3px #000,0 0 5px #000;">'
            f"{piste_name}"
            "</div>"
        )
        folium.Marker(
            location=[mid_lat, mid_lon],
            icon=folium.DivIcon(html=html),
        ).add_to(m)

    st_folium(
        m,
        height=450,
        width=None,
        key=pov_map_key,
    )

    # info sintetica sotto la mappa
    pos_m = dists[idx]
    st.markdown(
        f"**Pista POV:** {piste_name or 'pista senza nome'}  ·  "
        f"Posizione attuale ~{pos_m:.0f} m / {total_len_m:.0f} m "
        f"({progress_pct}%)"
    )

    return ctx
