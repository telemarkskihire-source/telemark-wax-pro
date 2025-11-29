# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Base OSM + satellite (Esri World Imagery)
# - Checkbox "Mostra piste sci alpino sulla mappa"
# - Piste da Overpass: piste:type=downhill
# - Puntatore che:
#     · segue selezione gara/località (ctx["lat"]/["lon"])
#     · al click viene “agganciato” alla pista downhill più vicina
# - Etichette con il nome della pista (se disponibile)
# - Stato puntatore separato per ogni map_context (pagina)

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


def _safe_rerun() -> None:
    """Forza un rerun senza crashare se il metodo non esiste."""
    try:
        st.rerun()
        return
    except Exception:
        pass
    try:
        st.experimental_rerun()  # type: ignore[attr-defined]
    except Exception:
        pass


# ------------------------------------------------------------------
# DOWNLOAD PISTE
# ------------------------------------------------------------------


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(
    lat: float,
    lon: float,
    radius_km: float = 10.0,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Scarica le piste di discesa (piste:type=downhill) via Overpass attorno
    a (lat, lon) con raggio in km.

    Ritorna:
      - numero di piste
      - lista di dict:
          {
            "coords": [(lat, lon), ...],
            "name":  "Pista Whatever" | None
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

    def _extract_name(tags: Dict[str, str]) -> Optional[str]:
        for key in ("piste:name", "name", "ref"):
            val = tags.get(key)
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
            name = _extract_name(tags)
            pistes.append({"coords": coords, "name": name})
            piste_count += 1

    return piste_count, pistes


# ------------------------------------------------------------------
# GEOMETRIA: SNAP DEL CLICK ALLA PISTA PIÙ VICINA
# ------------------------------------------------------------------


def _closest_point_on_pistes(
    click_lat: float,
    click_lon: float,
    pistes: List[Dict[str, Any]],
) -> Tuple[float, float, Optional[str]]:
    """
    Trova il punto della rete piste più vicino al click (click_lat, click_lon).
    Ritorna:
      - lat "snappata"
      - lon "snappata"
      - nome della pista più vicina (se conosciuto)
    Se non ci sono piste, ritorna il click originale.
    """
    if not pistes:
        return click_lat, click_lon, None

    best_d2 = float("inf")
    best_lat = click_lat
    best_lon = click_lon
    best_name: Optional[str] = None

    for piste in pistes:
        coords = piste.get("coords") or []
        pname = piste.get("name")
        for (lat, lon) in coords:
            dlat = lat - click_lat
            dlon = lon - click_lon
            d2 = dlat * dlat + dlon * dlon
            if d2 < best_d2:
                best_d2 = d2
                best_lat = lat
                best_lon = lon
                best_name = pname

    return best_lat, best_lon, best_name


# ------------------------------------------------------------------
# RENDER MAPPA
# ------------------------------------------------------------------


def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro iniziale
      - puntatore per pagina (map_context) in session_state:
          marker_lat_{map_context}, marker_lon_{map_context}

    Gestione click:
      - al click su mappa, il puntatore viene snappato alla pista downhill
        più vicina e salvato in ctx + st.session_state
      - viene forzato un rerun per vedere subito il movimento al primo click.
    """
    map_context = str(ctx.get("map_context", "default"))

    # centro di base
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    # puntatore per questa pagina
    marker_lat = float(
        st.session_state.get(f"marker_lat_{map_context}", ctx.get("marker_lat", base_lat))
    )
    marker_lon = float(
        st.session_state.get(f"marker_lon_{map_context}", ctx.get("marker_lon", base_lon))
    )

    # aggiorno ctx con il puntatore effettivo
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon

    # Checkbox piste
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

    # Puntatore attuale
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Piste + nomi
    piste_count = 0
    pistes: List[Dict[str, Any]] = []
    if show_pistes:
        piste_count, pistes = _fetch_downhill_pistes(
            marker_lat, marker_lon, radius_km=10.0
        )
        for piste in pistes:
            coords = piste["coords"]
            name = piste.get("name")

            folium.PolyLine(
                locations=coords,
                weight=3,
                opacity=0.9,
            ).add_to(m)

            if name and len(coords) >= 2:
                mid_idx = len(coords) // 2
                lat_mid, lon_mid = coords[mid_idx]
                folium.Marker(
                    location=[lat_mid, lon_mid],
                    icon=folium.DivIcon(
                        html=(
                            f'<div style="font-size:9px; color:white; '
                            f'text-shadow:0 0 3px #000; white-space:nowrap;">'
                            f'{name}</div>'
                        )
                    ),
                ).add_to(m)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # ---------------- RENDER IN STREAMLIT ----------------
    map_key = f"map_{map_context}"
    map_data = st_folium(m, height=450, width=None, key=map_key)

    # ---------------- GESTIONE CLICK ----------------
    if map_data and map_data.get("last_clicked") is not None:
        click_lat = float(map_data["last_clicked"]["lat"])
        click_lon = float(map_data["last_clicked"]["lng"])

        # snap alla pista più vicina (se presente)
        snap_lat, snap_lon, snap_name = _closest_point_on_pistes(
            click_lat, click_lon, pistes
        )

        # aggiorna ctx
        ctx["marker_lat"] = snap_lat
        ctx["marker_lon"] = snap_lon
        ctx["lat"] = snap_lat
        ctx["lon"] = snap_lon
        if snap_name:
            ctx["piste_name"] = snap_name
            st.session_state["piste_name"] = snap_name

        # salva stato per questa pagina
        st.session_state[f"marker_lat_{map_context}"] = snap_lat
        st.session_state[f"marker_lon_{map_context}"] = snap_lon

        _safe_rerun()

    return ctx
