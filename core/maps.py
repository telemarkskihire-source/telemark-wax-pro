# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che:
#     · parte dalla località selezionata (ctx["lat"], ctx["lon"])
#     · si aggiorna SUBITO al click (usando session_state del folium key)
#     · viene "agganciato" al punto più vicino di una pista downhill
# - Evidenzia la pista selezionata (colore diverso / più spessa)
# - Nomi piste SEMPRE visibili in mappa (testo piccolo al centro)
#   e nome della pista selezionata evidenziato
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

    if best_dist <= max_snap_m and best_idx is not None:
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
    # --- contesto per separare il marker fra varie pagine (local/race/altro) ---
    map_context = str(ctx.get("map_context", "default"))
    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    map_key = f"map_{map_context}"  # stesso key passato a st_folium
    selected_piste_idx_key = f"selected_piste_idx_{map_context}"

    # --- posizione base ---
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    marker_lat = float(st.session_state.get(marker_lat_key, ctx.get("marker_lat", default_lat)))
    marker_lon = float(st.session_state.get(marker_lon_key, ctx.get("marker_lon", default_lon)))

    # --- eventuale click precedente salvato nello stato della mappa ---
    prev_state = st.session_state.get(map_key)
    click_lat: Optional[float] = None
    click_lon: Optional[float] = None
    had_click = False

    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked not in (None, {}):
            try:
                click_lat = float(last_clicked.get("lat"))
                click_lon = float(last_clicked.get("lng"))
                had_click = True
            except Exception:
                had_click = False

    # Se c'è un click, spostiamo SUBITO il marker su quel punto (grezzo)
    if had_click and click_lat is not None and click_lon is not None:
        marker_lat = click_lat
        marker_lon = click_lon

    # aggiorna ctx + session con questa posizione "grezza"
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # ------------------------------------------------------------------
    # Checkbox per piste & fetch piste
    # ------------------------------------------------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    piste_count = 0
    polylines: List[List[Tuple[float, float]]] = []
    piste_names: List[Optional[str]] = []
    selected_idx: Optional[int] = st.session_state.get(selected_piste_idx_key, None)
    selected_dist_m: Optional[float] = ctx.get("selected_piste_distance_m")

    if show_pistes:
        piste_count, polylines, piste_names = _fetch_downhill_pistes(
            marker_lat,
            marker_lon,
            radius_km=10.0,
        )

        # se abbiamo piste e l'utente ha cliccato, agganciamo alla pista più vicina
        if had_click and polylines and click_lat is not None and click_lon is not None:
            snapped_lat, snapped_lon, idx, dist_m = _snap_to_nearest_piste_point(
                click_lat,
                click_lon,
                polylines,
                max_snap_m=400.0,
            )
            marker_lat = snapped_lat
            marker_lon = snapped_lon

            # aggiorna ctx + session con posizione "snappata"
            ctx["lat"] = marker_lat
            ctx["lon"] = marker_lon
            ctx["marker_lat"] = marker_lat
            ctx["marker_lon"] = marker_lon
            st.session_state[marker_lat_key] = marker_lat
            st.session_state[marker_lon_key] = marker_lon

            # salva la pista selezionata (se c'è)
            if idx is not None:
                selected_idx = idx
                st.session_state[selected_piste_idx_key] = idx
                selected_dist_m = dist_m
                ctx["selected_piste_distance_m"] = dist_m
            else:
                selected_idx = None
                st.session_state[selected_piste_idx_key] = None
                ctx["selected_piste_distance_m"] = None

    st.caption(f"Piste downhill trovate: {piste_count}")

    # ------------------------------------------------------------------
    # Costruisco la mappa Folium con il marker già aggiornato
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

    # piste con tooltip nome + LABEL SEMPRE VISIBILE + highlight pista selezionata
    if show_pistes and polylines:
        for i, (coords, name) in enumerate(zip(polylines, piste_names)):
            tooltip = name if name else None
            is_selected = selected_idx is not None and i == selected_idx

            # stile linea
            line_kwargs = {
                "locations": coords,
                "weight": 5 if is_selected else 3,
                "opacity": 1.0 if is_selected else 0.9,
            }
            if is_selected:
                line_kwargs["color"] = "yellow"

            folium.PolyLine(
                tooltip=tooltip,
                **line_kwargs,
            ).add_to(m)

            # LABEL fissa al centro pista
            if name:
                mid_idx = len(coords) // 2
                label_lat, label_lon = coords[mid_idx]

                # colore e stile diverso se è la pista selezionata
                text_color = "#fde047" if is_selected else "#e5e7eb"  # giallo vs grigio chiaro
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
    # Render Folium -> aggiorna st.session_state[map_key] con eventuale nuovo click
    #    Il nuovo click verrà letto all'inizio del prossimo rerun.
    # ------------------------------------------------------------------
    _ = st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # ------------------------------------------------------------------
    # Info pista selezionata sotto la mappa
    # ------------------------------------------------------------------
    selected_name: Optional[str] = None
    if (
        show_pistes
        and polylines
        and selected_idx is not None
        and 0 <= selected_idx < len(piste_names)
    ):
        selected_name = piste_names[selected_idx] or "pista senza nome"
        ctx["selected_piste_name"] = selected_name

        if selected_dist_m is not None:
            st.markdown(
                f"**Pista selezionata:** {selected_name} "
                f"(~{selected_dist_m:.0f} m dal punto cliccato)"
            )
        else:
            st.markdown(f"**Pista selezionata:** {selected_name}")

    return ctx
