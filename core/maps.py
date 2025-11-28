# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore visibile che segue:
#     · selezione gara (via ctx["lat"]/["lon"])
#     · click sulla mappa
# - Puntatore indipendente per contesto (local vs race) usando map_context

from __future__ import annotations

from typing import Dict, Any, List, Tuple

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(lat: float, lon: float, radius_km: float = 10.0) -> Tuple[int, List[List[Tuple[float, float]]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.
    Ritorna:
      - numero di piste
      - lista di polilinee, ciascuna come lista di (lat, lon)
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

    polylines: List[List[Tuple[float, float]]] = []
    piste_count = 0

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
                way = next((e for e in elements if e.get("type") == "way" and e.get("id") == wid), None)
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if not nd:
                        continue
                    coords.append((nd["lat"], nd["lon"]))

        if len(coords) >= 2:
            polylines.append(coords)
            piste_count += 1

    return piste_count, polylines


def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro di default
      - ctx["map_context"]      → nome contesto (es. "local", "race_2025-01-10_Pila")
      - puntatore per-contesto, salvato in sessione con chiavi diverse

    Ritorna ctx aggiornato con eventuale click sulla mappa:
      - ctx["marker_lat"], ctx["marker_lon"], ctx["lat"], ctx["lon"]
    """
    # --- contesto mappa ---
    map_context = str(ctx.get("map_context", "default"))
    session_lat_key = f"marker_lat_{map_context}"
    session_lon_key = f"marker_lon_{map_context}"

    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    # Se ho già un puntatore salvato per questo contesto, lo riuso
    if session_lat_key in st.session_state and session_lon_key in st.session_state:
        marker_lat = float(st.session_state[session_lat_key])
        marker_lon = float(st.session_state[session_lon_key])
    else:
        marker_lat = float(ctx.get("marker_lat", base_lat))
        marker_lon = float(ctx.get("marker_lon", base_lon))

    # Aggiorno ctx con il puntatore effettivo per questo contesto
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon

    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # --- crea mappa Folium ---
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

    # Puntatore visibile
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    piste_count = 0
    if show_pistes:
        piste_count, polylines = _fetch_downhill_pistes(marker_lat, marker_lon, radius_km=10.0)
        for coords in polylines:
            folium.PolyLine(
                locations=coords,
                weight=3,
                opacity=0.9,
            ).add_to(m)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # Render mappa in Streamlit
    map_key = f"map_{map_context}"
    map_data = st_folium(m, height=450, width=None, key=map_key)

    # --- Gestione click: aggiorna SOLO le chiavi per questo contesto ---
    if map_data and map_data.get("last_clicked") is not None:
        click_lat = float(map_data["last_clicked"]["lat"])
        click_lon = float(map_data["last_clicked"]["lng"])

        ctx["marker_lat"] = click_lat
        ctx["marker_lon"] = click_lon
        ctx["lat"] = click_lat
        ctx["lon"] = click_lon

        st.session_state[session_lat_key] = click_lat
        st.session_state[session_lon_key] = click_lon

    return ctx
