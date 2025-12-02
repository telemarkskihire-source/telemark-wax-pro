from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ------------------------------------------------------------
# Overpass – carica piste UNA VOLTA per località di partenza
# ------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_pistes_for_location(
    base_lat: float,
    base_lon: float,
    radius_km: float = 10.0,
) -> Tuple[int, List[List[Tuple[float, float]]], List[str]]:
    """Scarica le piste downhill attorno alla località di partenza."""
    radius_m = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way["piste:type"="downhill"](around:{radius_m},{base_lat},{base_lon});
      relation["piste:type"="downhill"](around:{radius_m},{base_lat},{base_lon});
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

    pistes: List[List[Tuple[float, float]]] = []
    names: List[str] = []

    def get_name(tags: Dict[str, Any]) -> Optional[str]:
        if not tags:
            return None
        for k in ("name", "piste:name", "ref"):
            if k in tags:
                val = str(tags[k]).strip()
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
            pistes.append(coords)
            names.append(get_name(tags) or "Senza nome")

    return len(pistes), pistes, names


# ------------------------------------------------------------
# Utility distanza + snapping
# ------------------------------------------------------------
def dist_m(a: float, b: float, c: float, d: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dl = math.radians(d - b)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def snap_to_piste(
    lat: float,
    lon: float,
    pistes: List[List[Tuple[float, float]]],
) -> Tuple[Tuple[float, float], float, Optional[int]]:
    """Ritorna il punto pista più vicino + distanza in metri + indice pista."""
    best: Optional[Tuple[float, float]] = None
    best_d = float("inf")
    best_idx: Optional[int] = None
    for idx, line in enumerate(pistes):
        for y, x in line:
            d = dist_m(lat, lon, y, x)
            if d < best_d:
                best_d = d
                best = (y, x)
                best_idx = idx
    return (best if best else (lat, lon)), best_d, best_idx


# ------------------------------------------------------------
# RENDER MAP – entry point usato dalla app
# ------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"

    # --- layout: mappa sopra, controlli sotto ---
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base per Overpass (NON si muove col marker)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker corrente (se non c'è → località base)
    marker_lat = float(ctx.get("marker_lat", ctx.get("lat", base_lat)))
    marker_lon = float(ctx.get("marker_lon", ctx.get("lon", base_lon)))

    # pista selezionata (indice in polylines)
    selected_idx: Optional[int] = ctx.get("selected_piste_index")
    if not isinstance(selected_idx, int):
        selected_idx = None

    # -----------------------------
    # 2) Carico piste intorno alla località base
    # -----------------------------
    piste_count, polylines, raw_names = load_pistes_for_location(base_lat, base_lon)

    # preparo nomi e meta
    names: List[str] = []
    for i, n in enumerate(raw_names):
        n = (n or "").strip()
        if not n:
            n = f"Pista {i+1}"
        names.append(n)

    meta: List[Dict[str, Any]] = []
    for idx, coords in enumerate(polylines):
        if not coords:
            continue
        meta.append(
            {
                "idx": idx,
                "name": names[idx],
                "coords": coords,
            }
        )
    index_map = {m["idx"]: m for m in meta}

    # se selected_idx fuori range, reset
    if selected_idx is not None and selected_idx not in index_map:
        selected_idx = None

    # -----------------------------
    # 3) Checkbox mostra piste
    # -----------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # -----------------------------
    # 4) TOGGLE PISTE (selectbox dentro expander)
    #    - calcolato PRIMA di disegnare la mappa
    # -----------------------------
    if meta:
        NONE_VALUE = -1
        sorted_meta = sorted(meta, key=lambda m: m["name"].lower())
        option_values: List[int] = [NONE_VALUE] + [m["idx"] for m in sorted_meta]

        def _fmt(val: int) -> str:
            if val == NONE_VALUE:
                return "— Nessuna —"
            return index_map[val]["name"]

        current_val = selected_idx if selected_idx in index_map else NONE_VALUE
        default_index = option_values.index(current_val)

        with controls_container:
            with st.expander(
                T.get("piste_select_label", "Seleziona pista dalla lista"),
                expanded=False,
            ):
                choice: int = st.selectbox(
                    "Pista",
                    options=option_values,
                    index=default_index,
                    format_func=_fmt,
                    key=f"piste_select_{map_context}",
                )

        # Se l'utente ha scelto una pista dal toggle
        if choice != NONE_VALUE and choice in index_map:
            selected_idx = choice
            coords = index_map[choice]["coords"]
            if coords:
                # marker in cima alla pista
                marker_lat, marker_lon = coords[0]

    # -----------------------------
    # 5) DISEGNO MAPPA con stato (marker + selected_idx)
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

        # piste + etichette
        if show_pistes and meta:
            for m_p in meta:
                coords = m_p["coords"]
                name = m_p["name"]
                is_sel = (m_p["idx"] == selected_idx)

                folium.PolyLine(
                    coords,
                    color="red" if is_sel else "blue",
                    weight=6 if is_sel else 3,
                    opacity=1.0 if is_sel else 0.6,
                ).add_to(m)

                if coords:
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

        # marker corrente
        folium.Marker(
            [marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        # OUTPUT click per questo run
        map_data = st_folium(m, height=450, key=map_key)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # -----------------------------
    # 6) CLICK SULLA MAPPA (aggiorna per il PROSSIMO refresh)
    # -----------------------------
    if isinstance(map_data, dict):
        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])
                marker_lat = c_lat
                marker_lon = c_lon

                if show_pistes and meta:
                    all_coords = [m_p["coords"] for m_p in meta]
                    (snap_lat, snap_lon), dist, idx = snap_to_piste(
                        marker_lat, marker_lon, all_coords
                    )
                    if dist <= 400 and idx is not None and 0 <= idx < len(meta):
                        marker_lat = snap_lat
                        marker_lon = snap_lon
                        selected_idx = meta[idx]["idx"]
            except Exception:
                pass

    # -----------------------------
    # 7) Salvo stato in ctx
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_index"] = selected_idx

    # -----------------------------
    # 8) Testo esplicito pista selezionata
    # -----------------------------
    if selected_idx is not None and selected_idx in index_map:
        st.markdown(f"**Pista selezionata:** {index_map[selected_idx]['name']}")
    else:
        st.markdown("**Pista selezionata:** nessuna")

    return ctx
