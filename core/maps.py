# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill (raggio 5 km dalla località)
# - Piste raggruppate per nome (niente duplicati nel toogle)
# - Selezione pista:
#     · da click su mappa (snap alla pista più vicina entro MAX_SNAP_M)
#     · da selectbox in un expander opzionale (on/off)
# - Nessuna opzione "nessuna pista" nel toogle: se usi la lista scegli SEMPRE
#   una pista; se vuoi usare solo la mappa, spegni la lista con lo switch.

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# distanza massima per agganciare il click alla pista più vicina (metri)
MAX_SNAP_M: float = 200.0


# ----------------------------------------------------------------------
# Overpass: fetch piste downhill (segmenti grezzi)
# ----------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
) -> Tuple[int, List[List[Tuple[float, float]]], List[Optional[str]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.

    Ritorna:
      - numero di segmenti (ways/relations)
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
    segment_count = 0

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
                if nd:
                    coords.append((nd["lat"], nd["lon"]))
        else:  # relation
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
                    if nd:
                        coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_name_from_tags(tags))
            segment_count += 1

    return segment_count, polylines, names


# ----------------------------------------------------------------------
# Raggruppo segmenti per nome pista
# ----------------------------------------------------------------------
def load_pistes_grouped_by_name(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Usa _fetch_downhill_pistes e raggruppa i segmenti con lo stesso nome.

    Ritorna:
      - numero di segmenti grezzi trovati
      - lista di piste raggruppate:
        [
          {
            "name": str,
            "segments": [ [ (lat,lon), ... ], [ ... ], ... ],
            "any_lat": float,
            "any_lon": float,
          },
          ...
        ]
    """
    segment_count, polylines, names = _fetch_downhill_pistes(lat, lon, radius_km)

    grouped: Dict[str, Dict[str, Any]] = {}
    unnamed_counter = 1

    for coords, nm in zip(polylines, names):
        if not coords:
            continue
        if nm is None or not str(nm).strip():
            key = f"Pista senza nome {unnamed_counter}"
            unnamed_counter += 1
        else:
            key = str(nm).strip()

        if key not in grouped:
            grouped[key] = {
                "name": key,
                "segments": [],
                "any_lat": coords[0][0],
                "any_lon": coords[0][1],
            }
        grouped[key]["segments"].append(coords)

    pistes = list(grouped.values())
    return segment_count, pistes


# ----------------------------------------------------------------------
# Distanza approssimata in metri
# ----------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import sin, cos, sqrt, atan2, radians

    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


# ----------------------------------------------------------------------
# Funzione principale chiamata dalla app
# ----------------------------------------------------------------------
def render_map(T, ctx):
    """
    Mappa Telemark:
      - base_lat/base_lon = centro fisso per le piste (non cambia coi click)
      - marker_lat/marker_lon = posizione attuale (click o toogle)
      - Selezione pista da:
          · click mappa (snap alla pista più vicina entro MAX_SNAP_M)
          · lista piste (se lo switch è attivo)
    """
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"

    # contenitori per layout
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base (centro fisso per Overpass)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))

    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker (si muove coi click / lista)
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # stato selezione
    selected_name: Optional[str] = ctx.get("selected_piste_name")
    if not isinstance(selected_name, str):
        selected_name = None

    # -----------------------------
    # 2) Carico piste raggruppate per nome
    # -----------------------------
    segment_count, pistes = load_pistes_grouped_by_name(base_lat, base_lon, radius_km=5.0)
    pistes_sorted = sorted(pistes, key=lambda p: p["name"].lower()) if pistes else []
    all_names = [p["name"] for p in pistes_sorted]

    # -----------------------------
    # 3) Gestisco un eventuale click sulla mappa (run precedente)
    # -----------------------------
    prev_state = st.session_state.get(map_key)
    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked and pistes_sorted:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])

                best_name = None
                best_lat = c_lat
                best_lon = c_lon
                best_d = float("inf")

                for piste in pistes_sorted:
                    for seg in piste["segments"]:
                        for lat, lon in seg:
                            d = _dist_m(c_lat, c_lon, lat, lon)
                            if d < best_d:
                                best_d = d
                                best_name = piste["name"]
                                best_lat = lat
                                best_lon = lon

                if best_name is not None and best_d <= MAX_SNAP_M:
                    selected_name = best_name
                    marker_lat = best_lat
                    marker_lon = best_lon
            except Exception:
                pass

    # -----------------------------
    # 4) Checkbox mostra piste
    # -----------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # -----------------------------
    # 5) Disegno mappa
    # -----------------------------
    with map_container:
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
            attr="Esri World Imagery",
            name="Satellite",
            control=True,
        ).add_to(m)

        # piste
        if show_pistes and pistes_sorted:
            for piste in pistes_sorted:
                name = piste["name"]
                is_selected = (selected_name == name)

                for seg in piste["segments"]:
                    folium.PolyLine(
                        locations=seg,
                        color="red" if is_selected else "blue",
                        weight=6 if is_selected else 3,
                        opacity=1.0 if is_selected else 0.6,
                    ).add_to(m)

                # etichetta con nome (cliccabile come la pista: se clicchi sul nome,
                # il click è su quel punto e il nostro snap lo prende)
                if piste["segments"]:
                    seg0 = piste["segments"][0]
                    mid_idx = len(seg0) // 2
                    label_lat, label_lon = seg0[mid_idx]
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

        # marker
        folium.Marker(
            location=[marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        st_folium(
            m,
            height=450,
            key=map_key,
        )

    st.caption(f"Segmenti piste downhill trovati: {segment_count}")

    # -----------------------------
    # 6) Switch: attiva/disattiva selezione da lista
    # -----------------------------
    use_list = st.checkbox(
        "Attiva selezione da lista piste",
        value=False,
        key=f"use_piste_list_{map_context}",
    )

    if use_list and pistes_sorted:
        # default: se c'è già una pista selezionata, la mostro; altrimenti la prima
        if selected_name and selected_name in all_names:
            default_index = all_names.index(selected_name)
        else:
            default_index = 0

        with controls_container:
            with st.expander(
                T.get("piste_select_label", "Seleziona pista dalla lista"),
                expanded=False,
            ):
                chosen_name: str = st.selectbox(
                    "Pista",
                    options=all_names,
                    index=default_index,
                    key=f"piste_select_{map_context}",
                )

        if chosen_name != selected_name:
            selected_name = chosen_name
            chosen_piste = next(
                (p for p in pistes_sorted if p["name"] == selected_name),
                None,
            )
            if chosen_piste:
                marker_lat = chosen_piste["any_lat"]
                marker_lon = chosen_piste["any_lon"]

    # -----------------------------
    # 7) Salvo stato in ctx
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected_name

    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
    else:
        st.markdown("**Pista selezionata:** nessuna (solo mappa)")

    return ctx
