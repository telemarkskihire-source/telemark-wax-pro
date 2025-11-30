# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore:
#     · parte da ctx["lat"], ctx["lon"]
#     · si aggiorna al click (con snap alla pista più vicina)
#     · il click viene gestito UNA volta sola (niente “casino” ai rerun)
# - Evidenzia pista selezionata (linea gialla + label evidenziata)
# - Stato separato per ogni contesto (ctx["map_context"])

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
    Scarica piste di discesa (piste:type=downhill) attorno a (lat, lon).

    Ritorna:
      - numero piste
      - lista polilinee (lista di (lat, lon))
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
                    if not nd:
                        continue
                    coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            names.append(_name_from_tags(tags))
            piste_count += 1

    return piste_count, polylines, names


# ----------------------------------------------------------------------
# Utility distanza & snapping
# ----------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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
    max_snap_m: float = 150.0,
) -> Tuple[float, float, Optional[int], Optional[float]]:
    """
    Se trova un punto di pista entro max_snap_m:
      -> (lat_snapped, lon_snapped, index_pista, distanza_m)
    Altrimenti:
      -> (click_lat, click_lon, None, None)
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
# Funzione principale
# ----------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"] centro
      - ctx["map_context"] separa lo stato fra pagine

    Ritorna ctx aggiornato con eventuale click e pista selezionata.
    """
    # ----- chiave di contesto (local, race, ecc.) -----
    map_context = str(ctx.get("map_context", "default"))

    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    map_key = f"map_{map_context}"
    selected_piste_idx_key = f"selected_piste_idx_{map_context}"
    last_click_lat_key = f"last_click_lat_{map_context}"
    last_click_lon_key = f"last_click_lon_{map_context}"

    # se è la prima volta per questo contesto, resetto eventuali residui
    if map_key not in st.session_state:
        for k in (
            marker_lat_key,
            marker_lon_key,
            selected_piste_idx_key,
            last_click_lat_key,
            last_click_lon_key,
        ):
            if k in st.session_state:
                del st.session_state[k]

    # ----- posizione base -----
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    if marker_lat_key not in st.session_state:
        st.session_state[marker_lat_key] = float(ctx.get("marker_lat", default_lat))
    if marker_lon_key not in st.session_state:
        st.session_state[marker_lon_key] = float(ctx.get("marker_lon", default_lon))

    marker_lat = float(st.session_state[marker_lat_key])
    marker_lon = float(st.session_state[marker_lon_key])

    # stato selezione pista
    selected_idx: Optional[int] = st.session_state.get(selected_piste_idx_key, None)
    selected_dist_m: Optional[float] = ctx.get("selected_piste_distance_m")

    # ------------------------------------------------------------------
    # 1) Leggo l'ultimo click SALVATO e lo gestisco UNA sola volta
    # ------------------------------------------------------------------
    prev_state = st.session_state.get(map_key)
    had_new_click = False
    click_lat: Optional[float] = None
    click_lon: Optional[float] = None

    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked not in (None, {}):
            try:
                raw_lat = float(last_clicked.get("lat"))
                raw_lon = float(last_clicked.get("lng"))
            except Exception:
                raw_lat = raw_lon = None

            if raw_lat is not None and raw_lon is not None:
                # confronto con l'ultimo click già gestito
                prev_lat = st.session_state.get(last_click_lat_key)
                prev_lon = st.session_state.get(last_click_lon_key)

                if prev_lat is None or prev_lon is None:
                    had_new_click = True
                else:
                    # se è praticamente lo stesso punto -> non è un click nuovo
                    if _haversine_m(prev_lat, prev_lon, raw_lat, raw_lon) > 0.5:
                        had_new_click = True

                if had_new_click:
                    click_lat = raw_lat
                    click_lon = raw_lon
                    st.session_state[last_click_lat_key] = raw_lat
                    st.session_state[last_click_lon_key] = raw_lon

    # se ho un click grezzo (prima dello snap) sposto subito il marker lì
    if had_new_click and click_lat is not None and click_lon is not None:
        marker_lat = click_lat
        marker_lon = click_lon

    # aggiorno ctx + marker grezzo
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # ------------------------------------------------------------------
    # 2) Checkbox piste & fetch
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
            marker_lat,
            marker_lon,
            radius_km=10.0,
        )

        # se esiste un NUOVO click e ho piste, faccio lo snap
        if had_new_click and polylines and click_lat is not None and click_lon is not None:
            snapped_lat, snapped_lon, idx, dist_m = _snap_to_nearest_piste_point(
                click_lat,
                click_lon,
                polylines,
                max_snap_m=150.0,
            )

            marker_lat = snapped_lat
            marker_lon = snapped_lon

            ctx["lat"] = marker_lat
            ctx["lon"] = marker_lon
            ctx["marker_lat"] = marker_lat
            ctx["marker_lon"] = marker_lon
            st.session_state[marker_lat_key] = marker_lat
            st.session_state[marker_lon_key] = marker_lon

            if idx is not None:
                selected_idx = idx
                st.session_state[selected_piste_idx_key] = idx
                selected_dist_m = dist_m
                ctx["selected_piste_distance_m"] = dist_m
                ctx["selected_piste_name"] = piste_names[idx] or "pista senza nome"
            else:
                selected_idx = None
                st.session_state[selected_piste_idx_key] = None
                ctx["selected_piste_distance_m"] = None
                ctx["selected_piste_name"] = None

    else:
        # se tolgo le piste, azzero selezione per questo contesto
        selected_idx = None
        st.session_state[selected_piste_idx_key] = None
        ctx["selected_piste_distance_m"] = None
        ctx["selected_piste_name"] = None

    st.caption(f"Piste downhill trovate: {piste_count}")

    # ------------------------------------------------------------------
    # 3) Costruzione mappa Folium (con marker già definitivo)
    # ------------------------------------------------------------------
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

    # piste + label sempre visibile + highlight selezionata
    if show_pistes and polylines:
        for i, (coords, name) in enumerate(zip(polylines, piste_names)):
            tooltip = name if name else None
            is_selected = selected_idx is not None and i == selected_idx

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
                    f'white-space:nowrap; '
                    f'background:rgba(0,0,0,0.35); '
                    f'padding:1px 3px; '
                    f'border-radius:3px;'
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

    # render mappa (aggiorna st.session_state[map_key] per il prossimo click)
    _ = st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # ------------------------------------------------------------------
    # 4) Info pista selezionata
    # ------------------------------------------------------------------
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
