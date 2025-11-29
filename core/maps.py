# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore visibile che segue:
#     · selezione gara/località (ctx["lat"]/["lon"])
#     · click sulla mappa (SUBITO al primo click)
# - Ritorna ctx aggiornato (lat/lon + marker_lat/lon)

from __future__ import annotations

from typing import Dict, Any, List, Tuple

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


def _safe_rerun() -> None:
    """Forza un rerun senza generare errori se il metodo non esiste."""
    try:
        # Streamlit nuovo
        st.rerun()
        return
    except Exception:
        pass

    try:
        # Streamlit più vecchio
        st.experimental_rerun()  # type: ignore[attr-defined]
    except Exception:
        # Se proprio non esiste, lasciamo perdere
        pass


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float = 10.0,
) -> Tuple[int, List[List[Tuple[float, float]]]]:
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
                way = next(
                    (
                        e
                        for e in elements
                        if e.get("type") == "way" and e.get("id") == wid
                    ),
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
            piste_count += 1

    return piste_count, polylines


def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro iniziale
      - ctx["marker_lat"], ["marker_lon"] → puntatore (fallback = lat/lon)
      - ctx["map_context"] → usato per key widget + stato click per pagina
    Gestisce il click dell'utente:
      - aggiorna ctx + st.session_state
      - forza un rerun immediato per vedere il puntatore MUOVERSI al primo click.
    """
    map_context = str(ctx.get("map_context", "default"))

    # Centro di base
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))

    # Puntatore: se esiste marker_* li uso, altrimenti lat/lon
    marker_lat = float(ctx.get("marker_lat", lat))
    marker_lon = float(ctx.get("marker_lon", lon))

    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon

    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # ---------------- CREA MAPPA FOLIUM ----------------
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

    # Puntatore gara/località attuale
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Piste (Overpass)
    piste_count = 0
    if show_pistes:
        piste_count, polylines = _fetch_downhill_pistes(
            marker_lat, marker_lon, radius_km=10.0
        )
        for coords in polylines:
            folium.PolyLine(
                locations=coords,
                weight=3,
                opacity=0.9,
            ).add_to(m)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # ---------------- RENDER IN STREAMLIT ----------------
    map_key = f"map_{map_context}"
    map_data = st_folium(m, height=450, width=None, key=map_key)

    # ---------------- GESTIONE CLICK ----------------
    # Salviamo ultimo click per questo contesto
    click_state_key = f"last_click_{map_context}"
    prev_click = st.session_state.get(click_state_key)

    if map_data and map_data.get("last_clicked") is not None:
        click_lat = float(map_data["last_clicked"]["lat"])
        click_lon = float(map_data["last_clicked"]["lng"])
        new_click = (click_lat, click_lon)

        # Solo se il click è NUOVO aggiorniamo e forziamo il rerun
        if new_click != prev_click:
            ctx["marker_lat"] = click_lat
            ctx["marker_lon"] = click_lon
            ctx["lat"] = click_lat
            ctx["lon"] = click_lon

            st.session_state["marker_lat"] = click_lat
            st.session_state["marker_lon"] = click_lon
            st.session_state["lat"] = click_lat
            st.session_state["lon"] = click_lon
            st.session_state[click_state_key] = new_click

            _safe_rerun()

    return ctx
