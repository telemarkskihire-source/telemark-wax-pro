# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che segue:
#     · selezione gara (ctx["lat"]/["lon"])
#     · click sulla mappa (snap alla pista più vicina, se vicina)
# - Nomi piste in piccolo
# - Stato separato per ogni contesto mappa (local / race / ecc.)

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional
import math

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# -------------------------------------------------------------------
# OVERPASS: scarica piste downhill
# -------------------------------------------------------------------
def _great_circle_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distanza approssimata in metri tra due punti lat/lon."""
    # approssimazione veloce, basta per pochi km
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        dlmb / 2
    ) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float, lon: float, radius_km: float = 10.0
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.

    Ritorna:
      - numero di piste
      - lista di dict:
          {
            "coords": [(lat, lon), ...],
            "label": "nome pista" (se disponibile)
          }
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
        return 0, []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    pistes: List[Dict[str, Any]] = []
    piste_count = 0

    # indicizzazione veloce delle way (per le relation)
    ways_by_id = {
        el["id"]: el for el in elements if el.get("type") == "way"
    }

    for el in elements:
        etype = el.get("type")
        if etype not in ("way", "relation"):
            continue

        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        # nome pista (se esiste)
        label = (
            tags.get("piste:name")
            or tags.get("name")
            or tags.get("ref")
            or f"Pista {piste_count + 1}"
        )

        coords: List[Tuple[float, float]] = []

        if etype == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if not nd:
                    continue
                coords.append((nd["lat"], nd["lon"]))

        elif etype == "relation":
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = ways_by_id.get(wid)
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if not nd:
                        continue
                    coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            pistes.append({"coords": coords, "label": label})
            piste_count += 1

    return piste_count, pistes


def _snap_to_nearest_piste(
    click_lat: float,
    click_lon: float,
    pistes: List[Dict[str, Any]],
    max_distance_m: float = 250.0,
) -> Tuple[float, float, Optional[float]]:
    """
    Trova il punto sulla pista più vicino al click.
    Se nessuna pista è entro max_distance_m, ritorna il click originale.
    """
    best_lat = click_lat
    best_lon = click_lon
    best_d = None

    for piste in pistes:
        coords = piste.get("coords") or []
        for plat, plon in coords:
            d = _great_circle_distance_m(click_lat, click_lon, plat, plon)
            if best_d is None or d < best_d:
                best_d = d
                best_lat = plat
                best_lon = plon

    if best_d is None:
        return click_lat, click_lon, None

    if best_d > max_distance_m:
        # troppo lontano dalla pista: usa il click "nudo"
        return click_lat, click_lon, best_d

    return best_lat, best_lon, best_d


# -------------------------------------------------------------------
# RENDER MAPPA
# -------------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro
      - stato del marker per contesto: marker_lat_<ctx>, marker_lon_<ctx>
      - ctx["map_context"] → chiave logica, es. "local" / "race_..."

    Ritorna ctx aggiornato con eventuale click sulla mappa.
    """
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    map_context = str(ctx.get("map_context", "default"))

    # chiavi per questo contesto (local / race / ecc.)
    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"

    # valori iniziali: prima session_state di questo contesto, poi ctx, poi default
    marker_lat = float(
        st.session_state.get(marker_lat_key, ctx.get("marker_lat", default_lat))
    )
    marker_lon = float(
        st.session_state.get(marker_lon_key, ctx.get("marker_lon", default_lon))
    )

    # aggiorna ctx base
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon

    # ---------------- UI: toggle piste ----------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # ---------------- costruzione mappa Folium ----------------
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
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m)

    pistes: List[Dict[str, Any]] = []
    piste_count = 0

    if show_pistes:
        piste_count, pistes = _fetch_downhill_pistes(
            marker_lat, marker_lon, radius_km=10.0
        )

        for piste in pistes:
            coords = piste["coords"]
            label = piste.get("label") or ""

            # polilinea pista
            folium.PolyLine(
                locations=coords,
                weight=3,
                opacity=0.9,
            ).add_to(m)

            # nome pista in piccolo, posizionato circa a metà
            mid_idx = len(coords) // 2
            name_lat, name_lon = coords[mid_idx]
            folium.map.Marker(
                location=[name_lat, name_lon],
                icon=folium.DivIcon(
                    html=(
                        f"<div style='font-size:10px; "
                        f"color:white; text-shadow:0 0 3px black;'>{label}</div>"
                    )
                ),
            ).add_to(m)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # Marker principale (puntatore località / gara)
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # ---------------- render in Streamlit ----------------
    map_key = f"map_{map_context}"
    map_data = st_folium(m, height=450, width=None, key=map_key)

    # ---------------- gestione click (subito al primo click) ----------------
    last_clicked = None
    if map_data is not None:
        last_clicked = map_data.get("last_clicked")

    if last_clicked is not None:
        try:
            click_lat = float(last_clicked["lat"])
            click_lon = float(last_clicked["lng"])
        except Exception:
            click_lat = marker_lat
            click_lon = marker_lon

        # snap alla pista più vicina (se disponibile)
        snapped_lat, snapped_lon, d_m = _snap_to_nearest_piste(
            click_lat, click_lon, pistes
        )

        new_lat = snapped_lat
        new_lon = snapped_lon

        # aggiorna ctx + session solo se effettivamente cambia qualcosa
        if (new_lat != marker_lat) or (new_lon != marker_lon):
            marker_lat = new_lat
            marker_lon = new_lon

            ctx["lat"] = new_lat
            ctx["lon"] = new_lon
            ctx["marker_lat"] = new_lat
            ctx["marker_lon"] = new_lon

            st.session_state[marker_lat_key] = new_lat
            st.session_state[marker_lon_key] = new_lon

    return ctx
