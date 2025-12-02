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

    # contenitori per layout (mappa sopra, controlli sotto)
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base per Overpass (fissa)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker corrente (fallback: località base)
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # selezione corrente pista (ID string tipo "0", "1", ...)
    old_selected_id = ctx.get("selected_piste_id")
    if not isinstance(old_selected_id, str):
        old_selected_id = None

    # -----------------------------
    # 2) PISTE (attorno alla località base)
    # -----------------------------
    piste_count, polylines, raw_names = load_pistes_for_location(base_lat, base_lon)

    meta: List[Dict[str, Any]] = []
    for idx, coords in enumerate(polylines):
        if not coords:
            continue
        name = (raw_names[idx] or "").strip() or f"Pista {idx+1}"
        piste_id = str(idx)
        meta.append(
            {
                "id": piste_id,
                "index": idx,
                "name": name,
                "coords": coords,
            }
        )
    id_map = {m["id"]: m for m in meta}

    # -----------------------------
    # 3) Checkbox mostra piste
    # -----------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # -----------------------------
    # 4) DISEGNO MAPPA con stato attuale (marker + old_selected_id)
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

        if show_pistes and meta:
            for m_p in meta:
                coords = m_p["coords"]
                name = m_p["name"]
                is_sel = (old_selected_id == m_p["id"])

                folium.PolyLine(
                    coords,
                    color="red" if is_sel else "blue",
                    weight=6 if is_sel else 3,
                    opacity=1.0 if is_sel else 0.6,
                ).add_to(m)

                # etichetta al centro pista
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

        folium.Marker(
            [marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        # output di questo run: conterrà il click per il PROSSIMO stato
        map_data = st_folium(m, height=450, key=map_key)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # -----------------------------
    # 5) TOGGLE PISTE (selectbox dentro expander)
    # -----------------------------
    NONE_ID = "__NONE__"
    chosen_id = old_selected_id  # default: nessun cambio

    if meta:
        sorted_meta = sorted(meta, key=lambda m_p: m_p["name"].lower())
        option_values = [NONE_ID] + [m_p["id"] for m_p in sorted_meta]
        label_map = {NONE_ID: "— Nessuna —"}
        label_map.update({m_p["id"]: m_p["name"] for m_p in sorted_meta})

        def _fmt(val: str) -> str:
            return label_map.get(val, val)

        current_val = old_selected_id if old_selected_id in option_values else NONE_ID
        default_index = option_values.index(current_val)

        with controls_container:
            with st.expander(
                T.get("piste_select_label", "Seleziona pista dalla lista"),
                expanded=False,
            ):
                chosen_id = st.selectbox(
                    "Pista",
                    options=option_values,
                    index=default_index,
                    format_func=_fmt,
                    key=f"piste_select_{map_context}",
                )

    # -----------------------------
    # 6) CALCOLO NUOVO STATO (click + toggle)
    # -----------------------------
    new_marker_lat = marker_lat
    new_marker_lon = marker_lon
    new_selected_id = old_selected_id

    # 6a) Click sulla mappa (di QUESTO run)
    if isinstance(map_data, dict):
        last_clicked = map_data.get("last_clicked")
        if last_clicked:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])
                new_marker_lat, new_marker_lon = c_lat, c_lon

                if show_pistes and meta:
                    polylines_only = [m_p["coords"] for m_p in meta]
                    (snap_lat, snap_lon), dist, idx = snap_to_piste(
                        new_marker_lat, new_marker_lon, polylines_only
                    )
                    if dist <= 400 and idx is not None:
                        new_marker_lat, new_marker_lon = snap_lat, snap_lon
                        # idx qui è l'indice in meta, NON l'id string → mappo
                        if 0 <= idx < len(meta):
                            new_selected_id = meta[idx]["id"]
            except Exception:
                pass

    # 6b) Se ho scelto dal toggle, questo PREVALE sul click
    if chosen_id and chosen_id != NONE_ID and chosen_id in id_map:
        m_sel = id_map[chosen_id]
        coords = m_sel["coords"]
        if coords:
            new_marker_lat, new_marker_lon = coords[0]
            new_selected_id = chosen_id

    # -----------------------------
    # 7) Salvo stato finale in ctx
    # -----------------------------
    ctx["marker_lat"] = new_marker_lat
    ctx["marker_lon"] = new_marker_lon
    ctx["lat"] = new_marker_lat
    ctx["lon"] = new_marker_lon
    ctx["selected_piste_id"] = new_selected_id

    # -----------------------------
    # 8) Testo esplicito pista selezionata
    # -----------------------------
    if new_selected_id and new_selected_id in id_map:
        st.markdown(f"**Pista selezionata:** {id_map[new_selected_id]['name']}")
    else:
        st.markdown("**Pista selezionata:** nessuna")

    return ctx
