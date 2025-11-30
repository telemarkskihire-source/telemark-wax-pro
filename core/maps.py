# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che:
#     · parte dalla località selezionata (ctx["lat"], ctx["lon"])
#     · si aggiorna al click (ma ogni click viene elaborato UNA volta sola)
#     · viene "agganciato" al punto più vicino di una pista downhill
# - Marker separato per ogni contesto (ctx["map_context"])
# - Etichetta con nome pista (sempre visibile) al centro della linea
# - Evidenzia la pista selezionata (via click o via lista)
# - Ritorna ctx aggiornato (lat/lon + marker_lat/lon + selected_piste_index)

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

    # helper per estrarre nome sensato
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
    max_snap_m: float = 400.0,
) -> Tuple[float, float]:
    """
    Trova il punto più vicino tra tutte le piste downhill.
    Se la distanza minima è <= max_snap_m, ritorna quel punto.
    Altrimenti ritorna le coordinate di click originali.
    """
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
    """
    Restituisce l'indice della pista (polyline) più vicina al punto dato.
    Se distanza minima > max_dist_m → None.
    """
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
    # --- contesto per separare il marker fra varie pagine (local/race/altro) ---
    map_context = str(ctx.get("map_context", "default"))
    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    selected_piste_state_key = f"selected_piste_idx_{map_context}"
    last_click_key = f"last_click_{map_context}"
    map_key = f"map_{map_context}"  # key passato a st_folium

    # --- posizione base dalla ctx (località selezionata) ---
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    # marker corrente da session_state (se esiste) o da ctx
    marker_lat = float(st.session_state.get(marker_lat_key, ctx.get("marker_lat", default_lat)))
    marker_lon = float(st.session_state.get(marker_lon_key, ctx.get("marker_lon", default_lon)))

    # ------------------------------------------------------------------
    # 1) Costruisco la mappa Folium (con posizione marker corrente)
    # ------------------------------------------------------------------
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

    # marker puntatore (posizione attuale)
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # ------------------------------------------------------------------
    # 2) Render Folium -> ottengo eventuale click utente
    # ------------------------------------------------------------------
    map_data = st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # ------------------------------------------------------------------
    # 3) Gestisco l'ultimo click (una sola volta per click)
    # ------------------------------------------------------------------
    new_click = False
    last_clicked = None

    if isinstance(map_data, dict):
        last_clicked = map_data.get("last_clicked")

    if last_clicked not in (None, {}):
        try:
            click_lat = float(last_clicked.get("lat"))
            click_lon = float(last_clicked.get("lng"))

            prev_click = st.session_state.get(last_click_key)
            prev_lat = prev_click.get("lat") if isinstance(prev_click, dict) else None
            prev_lon = prev_click.get("lon") if isinstance(prev_click, dict) else None

            # Elabora solo se il click è nuovo
            if prev_lat != click_lat or prev_lon != click_lon:
                new_click = True
                st.session_state[last_click_key] = {"lat": click_lat, "lon": click_lon}
                marker_lat = click_lat
                marker_lon = click_lon
        except Exception:
            pass

    # aggiorna ctx + session con la posizione post-click (ancora "grezza")
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # ------------------------------------------------------------------
    # 4) Checkbox piste + download piste da Overpass
    # ------------------------------------------------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    piste_count = 0
    polylines: List[List[Tuple[float, float]]] = []
    piste_names: List[Optional[str]] = []
    selected_piste_idx: Optional[int] = None
    selected_for_highlight: Optional[int] = None

    if show_pistes:
        piste_count, polylines, piste_names = _fetch_downhill_pistes(
            marker_lat,
            marker_lon,
            radius_km=10.0,
        )

        # Se abbiamo un NUOVO click, aggancio il marker alla pista più vicina
        if new_click and polylines:
            snapped_lat, snapped_lon = _snap_to_nearest_piste_point(
                marker_lat,
                marker_lon,
                polylines,
                max_snap_m=400.0,
            )
            marker_lat = snapped_lat
            marker_lon = snapped_lon
            ctx["lat"] = marker_lat
            ctx["lon"] = marker_lon
            ctx["marker_lat"] = marker_lat
            ctx["marker_lon"] = marker_lon
            st.session_state[marker_lat_key] = marker_lat
            st.session_state[marker_lon_key] = marker_lon

        # indice pista più vicina al marker (utile per evidenziare dopo un click)
        click_piste_idx: Optional[int] = None
        if polylines:
            click_piste_idx = _find_nearest_piste_index(
                marker_lat,
                marker_lon,
                polylines,
                max_dist_m=400.0,
            )

        # --------------------------------------------------------------
        # 5) Lista piste selezionabile (selectbox)
        #    - non sposta la mappa al primo load
        #    - sposta il marker SOLO quando l'utente cambia selezione
        # --------------------------------------------------------------
        if polylines:
            options = list(range(len(polylines)))

            def _fmt(i: int) -> str:
                return piste_names[i] or f"Pista {i + 1}"

            # valore precedente scelto (run precedente)
            prev_selected_idx = st.session_state.get(selected_piste_state_key, None)

            # indice di default per la select al primo giro
            if prev_selected_idx is not None and 0 <= prev_selected_idx < len(options):
                default_index = prev_selected_idx
            elif click_piste_idx is not None:
                default_index = click_piste_idx
            else:
                default_index = 0

            selected_piste_idx = st.selectbox(
                T.get("piste_select_label", "Seleziona pista"),
                options=options,
                index=default_index,
                format_func=_fmt,
                key=selected_piste_state_key,
            )

            # se l'utente ha CAMBIATO la pista dalla lista → aggiorno marker
            if prev_selected_idx is not None and selected_piste_idx != prev_selected_idx:
                coords_sel = polylines[selected_piste_idx]
                if coords_sel:
                    mid_idx_sel = len(coords_sel) // 2
                    marker_lat, marker_lon = coords_sel[mid_idx_sel]
                    ctx["lat"] = marker_lat
                    ctx["lon"] = marker_lon
                    ctx["marker_lat"] = marker_lat
                    ctx["marker_lon"] = marker_lon
                    st.session_state[marker_lat_key] = marker_lat
                    st.session_state[marker_lon_key] = marker_lon

            # per l'evidenziazione, la pista "attiva" è quella della lista
            selected_for_highlight = selected_piste_idx

        # se nessuna pista è selezionata dalla lista ma abbiamo un click,
        # evidenzio comunque la pista più vicina al marker
        if selected_for_highlight is None and click_piste_idx is not None:
            selected_for_highlight = click_piste_idx

    # salvo nel contesto quale pista è selezionata / evidenziata
    ctx["selected_piste_index"] = selected_for_highlight
    st.caption(f"Piste downhill trovate: {piste_count}")

    # ------------------------------------------------------------------
    # 6) Ridisegno la mappa con le piste (sovrapposte)
    # ------------------------------------------------------------------
    m2 = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer(
        "OpenStreetMap",
        name="Strade",
        control=True,
    ).add_to(m2)

    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m2)

    if show_pistes and polylines:
        for idx, (coords, name) in enumerate(zip(polylines, piste_names)):
            tooltip = name if name else None
            is_selected = selected_for_highlight is not None and idx == selected_for_highlight

            line_weight = 6 if is_selected else 3
            line_opacity = 1.0 if is_selected else 0.6
            line_color = "red" if is_selected else "blue"

            folium.PolyLine(
                locations=coords,
                weight=line_weight,
                opacity=line_opacity,
                color=line_color,
                tooltip=tooltip,
            ).add_to(m2)

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
                ).add_to(m2)

    # marker finale
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m2)

    # render finale (non ci interessa l'output, solo il disegno)
    st_folium(
        m2,
        height=450,
        width=None,
        key=f"{map_key}_final",
    )

    return ctx
