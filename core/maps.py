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
) -> Tuple[Tuple[float, float], float]:
    """Ritorna il punto pista più vicino + distanza in metri."""
    best: Optional[Tuple[float, float]] = None
    best_d = float("inf")
    for line in pistes:
        for y, x in line:
            d = dist_m(lat, lon, y, x)
            if d < best_d:
                best_d = d
                best = (y, x)
    return (best if best else (lat, lon)), best_d


# ------------------------------------------------------------
# RENDER MAP – entry point usato dalla app
# ------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"
    last_click_key = f"last_click_pair_{map_context}"

    # container: prima mappa, poi controlli (ma li riempiamo al contrario)
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base per le piste
    # -----------------------------
    base_lat = float(ctx.get("base_lat", ctx.get("lat", 45.83333)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", 7.73333)))
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker corrente (ultima posizione nota o località base)
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # -----------------------------
    # 2) PISTE (attorno alla località base)
    # -----------------------------
    piste_count, pistes, piste_names = load_pistes_for_location(base_lat, base_lon)

    # metadata piste con ID stabile
    meta: List[Dict[str, Any]] = []
    for i, coords in enumerate(pistes):
        if not coords:
            continue
        name = piste_names[i]
        top_lat, top_lon = coords[0]
        pid = f"{name}|{top_lat:.5f}|{top_lon:.5f}"
        meta.append(
            {
                "id": pid,
                "name": name,
                "coords": coords,
                "top_lat": top_lat,
                "top_lon": top_lon,
                "index": i,
            }
        )
    idmap = {m["id"]: m for m in meta}

    # stato corrente pista selezionata
    selected_piste_id: Optional[str] = ctx.get("selected_piste_id")

    # -----------------------------
    # 3) Checkbox mostra piste
    # -----------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # -----------------------------
    # 4) GESTIONE CLICK (prima di disegnare la mappa)
    #    - leggo last_clicked dallo stato del componente di PRIMA
    # -----------------------------
    prev_state = st.session_state.get(map_key)
    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])
                pair = (round(c_lat, 6), round(c_lon, 6))

                prev_pair = st.session_state.get(last_click_key)
                # elaboro solo se è un click NUOVO
                if prev_pair != pair:
                    st.session_state[last_click_key] = pair
                    marker_lat, marker_lon = c_lat, c_lon

                    if show_pistes and meta:
                        (s_lat, s_lon), dist = snap_to_piste(marker_lat, marker_lon, pistes)
                        if dist <= 400:
                            marker_lat, marker_lon = s_lat, s_lon

                            # trova la pista più vicina al punto snappato
                            best_meta = None
                            best_d = float("inf")
                            for p in meta:
                                for y, x in p["coords"]:
                                    d = dist_m(marker_lat, marker_lon, y, x)
                                    if d < best_d:
                                        best_d = d
                                        best_meta = p
                            if best_meta:
                                selected_piste_id = best_meta["id"]
            except Exception:
                pass

    # -----------------------------
    # 5) TOGGLE PISTE (controlli SOTTO, ma calcolati PRIMA)
    # -----------------------------
    NONE_VALUE = "__NONE__"
    sorted_meta = sorted(meta, key=lambda m: m["name"].lower()) if meta else []

    option_values: List[str] = [NONE_VALUE] + [m["id"] for m in sorted_meta]
    option_labels: List[str] = ["— Nessuna —"] + [m["name"] for m in sorted_meta]
    label_map = {v: l for v, l in zip(option_values, option_labels)}

    def _fmt(val: str) -> str:
        return label_map.get(val, val)

    current_val = selected_piste_id if selected_piste_id in option_values else NONE_VALUE
    default_index = option_values.index(current_val)

    with controls_container:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        chosen_val: str = st.selectbox(
            T.get("piste_select_label", "Pista"),
            options=option_values,
            index=default_index,
            format_func=_fmt,
            key=f"piste_select_{map_context}",
        )

    # cambio pista dal toggle → marker in CIMA a quella pista
    if chosen_val != current_val and chosen_val != NONE_VALUE:
        chosen_meta = idmap.get(chosen_val)
        if chosen_meta:
            marker_lat = chosen_meta["top_lat"]
            marker_lon = chosen_meta["top_lon"]
            selected_piste_id = chosen_meta["id"]
            # annullo l'ultimo click, così non rientra al prossimo run
            st.session_state[last_click_key] = None

    # -----------------------------
    # 6) Aggiorno ctx con la posizione finale (click + toggle)
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_id"] = selected_piste_id

    # -----------------------------
    # 7) DISEGNO LA MAPPA CON LO STATO FINALE
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

        # piste (se visibili) + NOMI FISSI
        if show_pistes and meta:
            for p in meta:
                coords = p["coords"]
                name = p["name"]
                is_sel = (selected_piste_id == p["id"])

                folium.PolyLine(
                    coords,
                    color="red" if is_sel else "blue",
                    weight=6 if is_sel else 3,
                    opacity=1.0 if is_sel else 0.6,
                ).add_to(m)

                # etichetta fissa al centro pista
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
                    ).add_to(m)

        # marker corrente
        folium.Marker(
            [marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        # questo aggiornerà last_clicked in session_state per il prossimo run
        st_folium(m, height=450, key=map_key)

    st.caption(f"Piste downhill trovate: {piste_count}")

    # -----------------------------
    # 8) Testo esplicito pista selezionata
    # -----------------------------
    if selected_piste_id and selected_piste_id in idmap:
        name = idmap[selected_piste_id]["name"]
        st.markdown(f"**Pista selezionata:** {name}")
    else:
        st.markdown("**Pista selezionata:** nessuna")

    return ctx
