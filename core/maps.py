# core/maps.py
# Mappa & piste per Telemark · Pro Wax & Tune
#
# - Carica le piste da Overpass (piste:type=downhill) in raggio 5 km
#   intorno alla località (ctx["lat"], ctx["lon"]) iniziale.
# - La località base (centro ricerca piste) resta FISSA: i click sulla mappa
#   muovono solo il marker, non il centro della query → le piste non spariscono.
# - Selezione pista:
#     · CLICK su mappa: snap alla pista più vicina, con raggio DINAMICO
#       in base allo zoom (lontano = raggio grande, vicino = preciso).
#     · Lista piste opzionale (switch + selectbox sotto la mappa).
# - La pista selezionata rimane evidenziata in ROSSO finché non ne scegli
#   un’altra. Il nome è salvato anche in st.session_state.
# - Le piste SENZA nome non hanno label (niente "pista senza nome").
# - La chiamata a st_folium usa la FIRMA che sul progetto funzionava:
#   st_folium(m, height=..., width=None, key=...).

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# raggio di snap "base" usato sugli zoom alti (mappa molto vicina)
BASE_MAX_SNAP_M: float = 300.0


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
# Distanza approssimata in metri
# ----------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# ----------------------------------------------------------------------
# Calcolo raggio snap dinamico in base allo zoom
# ----------------------------------------------------------------------
def _dynamic_snap_radius(prev_state: Optional[Dict[str, Any]]) -> float:
    """
    Restituisce il raggio in metri per lo snap alla pista più vicina,
    in base al livello di zoom salvato da st_folium.

    Idee:
      - zoom molto lontano (<= 9–10)  -> raggio molto grande (2.5 km)
      - zoom medio (11–12)            -> raggio 1.5 km
      - zoom "normale" (13–14)        -> raggio 600 m
      - zoom vicino (>= 15)           -> raggio base 300 m
    """
    zoom = None
    if isinstance(prev_state, dict):
        z = prev_state.get("zoom")
        if isinstance(z, (int, float)):
            zoom = float(z)

    if zoom is None:
        return BASE_MAX_SNAP_M  # fallback

    if zoom <= 10:
        return 2500.0
    if zoom <= 12:
        return 1500.0
    if zoom <= 14:
        return 600.0
    return BASE_MAX_SNAP_M


# ----------------------------------------------------------------------
# Funzione principale chiamata dalla app
# ----------------------------------------------------------------------
def render_map(T, ctx):
    """
    Mappa Telemark:
      - click mappa → snap a pista più vicina (raggio dinamico)
      - lista piste opzionale (non rompe la selezione da click)
    """
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"
    sel_key = f"selected_piste_{map_context}"

    # -----------------------------
    # 1) Località base (centro fisso per Overpass)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))

    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker attuale
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # stato selezione pista: prima da session_state, poi da ctx
    selected_name = st.session_state.get(sel_key)
    if not isinstance(selected_name, str):
        v = ctx.get("selected_piste_name")
        selected_name = v if isinstance(v, str) else None

    # -----------------------------
    # 2) Carico piste grezze
    # -----------------------------
    segment_count, polylines, names = _fetch_downhill_pistes(
        base_lat,
        base_lon,
        radius_km=5.0,
    )

    # per la lista piste: solo quelle con nome
    named_pairs = [(coords, nm) for coords, nm in zip(polylines, names) if nm]
    unique_names = sorted({nm for _, nm in named_pairs})

    # -----------------------------
    # 3) Se c'è un click memorizzato, applico lo snap PRIMA di ridisegnare.
    #    Uso un raggio dinamico in base allo zoom.
    # -----------------------------
    prev_state = st.session_state.get(map_key)
    snap_radius = _dynamic_snap_radius(prev_state)

    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked and polylines:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])

                best_nm: Optional[str] = None
                best_lat = c_lat
                best_lon = c_lon
                best_d = float("inf")

                for coords, nm in zip(polylines, names):
                    for lat, lon in coords:
                        d = _dist_m(c_lat, c_lon, lat, lon)
                        if d < best_d:
                            best_d = d
                            best_nm = nm
                            best_lat = lat
                            best_lon = lon

                if best_d <= snap_radius:
                    marker_lat = best_lat
                    marker_lon = best_lon
                    if best_nm:
                        selected_name = best_nm
            except Exception:
                pass

    # -----------------------------
    # 4) Determino lo zoom iniziale
    #    - se c'è già uno zoom salvato, lo riuso
    #    - altrimenti parto bello vicino (zoom 15)
    # -----------------------------
    zoom_start = 15.0  # zoom di partenza "vicino"
    if isinstance(prev_state, dict):
        z = prev_state.get("zoom")
        if isinstance(z, (int, float)):
            zoom_start = float(z)

    # -----------------------------
    # 5) Disegno mappa
    # -----------------------------
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=zoom_start,
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

    # piste (tutte blu, rossa quella selezionata)
    label_done = set()
    for coords, nm in zip(polylines, names):
        is_selected = (nm is not None and nm == selected_name)

        folium.PolyLine(
            locations=coords,
            color="red" if is_selected else "blue",
            weight=6 if is_selected else 3,
            opacity=1.0 if is_selected else 0.6,
        ).add_to(m)

        # etichetta SOLO se c'è un nome e non l'abbiamo già disegnata
        if nm and nm not in label_done and coords:
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
                        f"'>{nm}</div>"
                    )
                ),
            ).add_to(m)
            label_done.add(nm)

    # marker
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # firma "sicura" di st_folium
    _ = st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    st.caption(
        f"Segmenti piste downhill trovati: {segment_count} — raggio snap attuale ≈ {int(snap_radius)} m"
    )

    # -----------------------------
    # 6) Switch + lista piste (OPZIONALE, sotto la mappa)
    # -----------------------------
    use_list = st.checkbox(
        "Attiva selezione da lista piste",
        value=False,
        key=f"use_piste_list_{map_context}",
    )

    if use_list and unique_names:
        # default: se ho già una pista selezionata, la uso; altrimenti la prima
        if selected_name in unique_names:
            default_index = unique_names.index(selected_name)
        else:
            default_index = 0

        with st.expander(
            T.get("piste_select_label", "Seleziona pista dalla lista"),
            expanded=False,
        ):
            chosen_name: str = st.selectbox(
                "Pista",
                options=unique_names,
                index=default_index,
                key=f"piste_select_{map_context}",
            )

        # se l'utente cambia pista dalla lista, aggiorno selezione + marker
        if chosen_name != selected_name:
            selected_name = chosen_name
            for coords, nm in named_pairs:
                if nm == selected_name and coords:
                    mid_idx = len(coords) // 2
                    marker_lat, marker_lon = coords[mid_idx]
                    break

    # -----------------------------
    # 7) Salvo stato in ctx + session_state
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected_name
    st.session_state[sel_key] = selected_name
# ----------------------------------------------------
# 8) SALVA I PUNTI DELLA PISTA SELEZIONATA PER MODULO POV
# ----------------------------------------------------
selected_points = None

if selected_name:
    for coords, nm in zip(polylines, names):
        if nm == selected_name:
            # coords è una lista di (lat, lon)
            selected_points = [{"lat": lat, "lon": lon, "elev": 0.0} for (lat, lon) in coords]
            break

# salva per modulo POV 2D + 3D
ctx["selected_piste_points"] = selected_points
ctx["pov_piste_points"] = selected_points
    # info utente
    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
    else:
        st.markdown("**Pista selezionata:** nessuna (clicca sulla mappa o usa la lista)")

    return ctx
