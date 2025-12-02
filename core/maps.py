# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che:
#     · parte dalla località selezionata (ctx["lat"], ctx["lon"])
#     · si aggiorna al click (ogni click elaborato una sola volta)
#     · viene "agganciato" al punto più vicino di una pista downhill
# - Lista piste:
#     · prima voce: nessuna pista selezionata
#     · ordine alfabetico per nome
#     · il semplice aprire il toggle NON sposta la mappa
#     · il marker viene spostato in CIMA alla pista SOLO quando scegli una pista
# - Evidenziazione pista selezionata (linea rossa più spessa)
# - Ritorna ctx aggiornato con marker + info pista

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
# Utility distanza + snapping
# ----------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza approssimata in metri tra due punti (lat/lon in gradi)."""
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
    max_snap_m: float = 400.0,
) -> Tuple[float, float]:
    """Ritorna il punto di pista più vicino al click (se entro max_snap_m)."""
    best_lat = click_lat
    best_lon = click_lon
    best_dist = float("inf")

    for line in polylines:
        for pt_lat, pt_lon in line:
            d = _haversine_m(click_lat, click_lon, pt_lat, pt_lon)
            if d < best_dist:
                best_dist = d
                best_lat = pt_lat
                best_lon = pt_lon

    if best_dist <= max_snap_m:
        return best_lat, best_lon
    return click_lat, click_lon


def _find_nearest_piste_index(
    lat: float,
    lon: float,
    polylines: List[List[Tuple[float, float]]],
    max_dist_m: float = 400.0,
) -> Optional[int]:
    """Indice della pista più vicina al punto dato (se entro max_dist_m)."""
    best_idx: Optional[int] = None
    best_dist = float("inf")

    for idx, line in enumerate(polylines):
        for pt_lat, pt_lon in line:
            d = _haversine_m(lat, lon, pt_lat, pt_lon)
            if d < best_dist:
                best_dist = d
                best_idx = idx

    if best_idx is not None and best_dist <= max_dist_m:
        return best_idx
    return None


# ----------------------------------------------------------------------
# Funzione principale
# ----------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa, gestisce click + lista piste e aggiorna ctx.
    """
    map_context = str(ctx.get("map_context", "default"))

    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    map_key = f"map_{map_context}"
    last_click_key = f"last_click_{map_context}"
    selected_piste_id_key = f"selected_piste_id_{map_context}"

    # --------------- posizione iniziale ---------------
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    marker_lat = float(st.session_state.get(marker_lat_key, ctx.get("marker_lat", default_lat)))
    marker_lon = float(st.session_state.get(marker_lon_key, ctx.get("marker_lon", default_lon)))

    # --------------- click nuovo? (elaboro solo una volta) ---------------
    prev_state = st.session_state.get(map_key)
    new_click = False
    click_lat = None
    click_lon = None

    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked not in (None, {}):
            try:
                click_lat = float(last_clicked.get("lat"))
                click_lon = float(last_clicked.get("lng"))
                click_pair = (round(click_lat, 6), round(click_lon, 6))

                prev_click_pair = st.session_state.get(last_click_key)
                if prev_click_pair != click_pair:
                    # click diverso dal precedente → lo elaboro
                    new_click = True
                    st.session_state[last_click_key] = click_pair
            except Exception:
                new_click = False

    if new_click and click_lat is not None and click_lon is not None:
        marker_lat = click_lat
        marker_lon = click_lon

    # sincronizzo ctx con marker corrente (ancora "grezzo")
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # --------------- checkbox: mostra/nascondi piste ---------------
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
            marker_lat,
            marker_lon,
            radius_km=10.0,
        )

    # --------------- costruisco metadati piste + id stabili ---------------
    piste_meta: List[Dict[str, Any]] = []
    id_to_meta: Dict[str, Dict[str, Any]] = {}

    if show_pistes and polylines:
        for idx, coords in enumerate(polylines):
            if not coords:
                continue
            name = piste_names[idx] or f"Pista {idx + 1}"
            top_lat, top_lon = coords[0]
            label = name
            piste_id = f"{label}|{top_lat:.5f}|{top_lon:.5f}"

            meta = {
                "id": piste_id,
                "index": idx,
                "name": name,
                "label": label,
                "top_lat": top_lat,
                "top_lon": top_lon,
                "coords": coords,
            }
            piste_meta.append(meta)
            id_to_meta[piste_id] = meta

    # --------------- stato attuale: pista selezionata (id) ---------------
    selected_piste_id: Optional[str] = st.session_state.get(
        selected_piste_id_key,
        ctx.get("selected_piste_id"),
    )

    # se new_click + piste → snap + seleziona pista più vicina
    if new_click and show_pistes and piste_meta:
        snapped_lat, snapped_lon = _snap_to_nearest_piste_point(
            marker_lat,
            marker_lon,
            [m["coords"] for m in piste_meta],
            max_snap_m=400.0,
        )
        marker_lat = snapped_lat
        marker_lon = snapped_lon

        nearest_idx = _find_nearest_piste_index(
            marker_lat,
            marker_lon,
            [m["coords"] for m in piste_meta],
            max_dist_m=400.0,
        )
        if nearest_idx is not None:
            # trova meta con index = nearest_idx
            for mdata in piste_meta:
                if mdata["index"] == nearest_idx:
                    selected_piste_id = mdata["id"]
                    break

    # aggiorno ctx + session dopo eventuale snapping
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["selected_piste_id"] = selected_piste_id
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon
    st.session_state[selected_piste_id_key] = selected_piste_id

    st.caption(f"Piste downhill trovate: {piste_count}")

    # --------------- SELECTBOX piste (ordinato, con "nessuna") ---------------
    if show_pistes and piste_meta:
        # opzione "nessuna"
        NONE_VALUE = "__NONE__"

        # ordino alfabeticamente per label
        sorted_meta = sorted(piste_meta, key=lambda m: m["label"].lower())

        option_values: List[str] = [NONE_VALUE] + [m["id"] for m in sorted_meta]
        option_labels: List[str] = ["— Nessuna pista selezionata —"] + [
            m["label"] for m in sorted_meta
        ]

        label_map = {val: lab for val, lab in zip(option_values, option_labels)}

        def _fmt(val: str) -> str:
            return label_map.get(val, val)

        # valore corrente logico
        current_val = selected_piste_id if selected_piste_id in option_values else NONE_VALUE

        if current_val in option_values:
            default_index = option_values.index(current_val)
        else:
            default_index = 0

        prev_val = current_val

        selected_val: str = st.selectbox(
            T.get("piste_select_label", "Pista (opzionale)"),
            options=option_values,
            index=default_index,
            format_func=_fmt,
            key=f"piste_select_{map_context}",
        )

        # se l'utente ha cambiato selezione e ha scelto una pista reale
        if selected_val != prev_val and selected_val != NONE_VALUE:
            selected_piste_id = selected_val
            meta = id_to_meta.get(selected_piste_id)
            if meta:
                marker_lat = meta["top_lat"]
                marker_lon = meta["top_lon"]

    # --------------- sync finale ctx + stato per DEM & co. ---------------
    selected_index: Optional[int] = None
    selected_name: Optional[str] = None
    if selected_piste_id and selected_piste_id in id_to_meta:
        meta = id_to_meta[selected_piste_id]
        selected_index = meta["index"]
        selected_name = meta["name"]

    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["selected_piste_id"] = selected_piste_id
    ctx["selected_piste_index"] = selected_index
    ctx["selected_piste_name"] = selected_name

    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon
    st.session_state[selected_piste_id_key] = selected_piste_id

    # --------------- costruisco mappa Folium ---------------
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

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

    if show_pistes and piste_meta:
        for meta in piste_meta:
            coords = meta["coords"]
            name = meta["name"]
            is_selected = selected_piste_id == meta["id"]

            line_weight = 6 if is_selected else 3
            line_opacity = 1.0 if is_selected else 0.6
            line_color = "red" if is_selected else "blue"

            folium.PolyLine(
                locations=coords,
                weight=line_weight,
                opacity=line_opacity,
                color=line_color,
                tooltip=name,
            ).add_to(m)

            if name and coords:
                mid_idx = len(coords) // 2
                label_lat, label_lon = coords[mid_idx]
                folium.Marker(
                    location=[label_lat, label_lon],
                    icon=folium.DivIcon(
                        html=(
                            f"<div style='"
                            "font-size:10px;"
                            "color:white;"
                            "text-shadow:0 0 3px black;"
                            "white-space:nowrap;"
                            "background:rgba(0,0,0,0.3);"
                            "padding:1px 3px;"
                            "border-radius:3px;"
                            f"'>{name}</div>"
                        )
                    ),
                ).add_to(m)

    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    return ctx
