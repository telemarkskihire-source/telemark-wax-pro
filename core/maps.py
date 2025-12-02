from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ------------------------------------------------------------
# Overpass – chiamata UNA SOLA VOLTA per località
# ------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_pistes_for_location(base_lat: float, base_lon: float) -> Tuple[
    int,
    List[List[Tuple[float, float]]],
    List[str]
]:
    radius_m = 10000
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
        r = requests.post("https://overpass-api.de/api/interpreter",
                          data=query.encode("utf-8"), headers=UA, timeout=25)
        r.raise_for_status()
        js = r.json()
    except Exception:
        return 0, [], []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    pistes = []
    names = []

    def get_name(tags):
        if not tags:
            return None
        for k in ("name", "piste:name", "ref"):
            if k in tags:
                return str(tags[k])
        return None

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        coords = []
        if el["type"] == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if nd:
                    coords.append((nd["lat"], nd["lon"]))
        else:
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next((e for e in elements if e.get("type") == "way" and e.get("id") == wid), None)
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
# Utility
# ------------------------------------------------------------
def dist_m(a, b, c, d):
    R = 6371000
    phi1, phi2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dl = math.radians(d - b)
    h = (math.sin(dphi/2)**2
         + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2)
    return R * 2 * math.atan2(math.sqrt(h), math.sqrt(1-h))


def snap_to_piste(lat, lon, pistes):
    best = None
    best_d = 9999999
    for line in pistes:
        for y, x in line:
            d = dist_m(lat, lon, y, x)
            if d < best_d:
                best_d = d
                best = (y, x)
    return best if best else (lat, lon), best_d


# ------------------------------------------------------------
# RENDER MAP
# ------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:

    # -------------------------------------------------
    # 1. Posizione iniziale locale (NO Overpass qui!)
    # -------------------------------------------------
    base_lat = float(ctx.get("lat", 45.83333))
    base_lon = float(ctx.get("lon", 7.73333))

    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # -------------------------------------------------
    # 2. PISTE CARICATE UNA SOLA VOLTA
    # -------------------------------------------------
    piste_count, pistes, piste_names = load_pistes_for_location(base_lat, base_lon)

    # costruisco metadata con ID STABILE
    meta = []
    for i, coords in enumerate(pistes):
        name = piste_names[i]
        top = coords[0]
        pid = f"{name}|{top[0]:.5f}|{top[1]:.5f}"
        meta.append({
            "id": pid,
            "name": name,
            "coords": coords,
            "top_lat": top[0],
            "top_lon": top[1],
            "index": i,
        })
    idmap = {m["id"]: m for m in meta}

    # -------------------------------------------------
    # 3. CLICK SULLA MAPPA (una volta sola)
    # -------------------------------------------------
    map_key = f"map_{ctx.get('map_context','def')}"
    prev_state = st.session_state.get(map_key)

    new_click = False
    if isinstance(prev_state, dict) and "last_clicked" in prev_state:
        c = prev_state["last_clicked"]
        if c:
            lat = float(c["lat"])
            lon = float(c["lng"])
            pair = (round(lat, 5), round(lon, 5))
            if st.session_state.get("last_click_pair") != pair:
                st.session_state["last_click_pair"] = pair
                new_click = True
                marker_lat = lat
                marker_lon = lon

    # snapping SOLO se click e piste esistono
    selected_id = ctx.get("selected_piste_id")
    if new_click and meta:
        (s_lat, s_lon), dist = snap_to_piste(marker_lat, marker_lon, pistes)
        if dist <= 400:
            marker_lat, marker_lon = s_lat, s_lon
            # trova la pista corrispondente
            best = None
            best_d = 9999999
            for m in meta:
                for y, x in m["coords"]:
                    d = dist_m(marker_lat, marker_lon, y, x)
                    if d < best_d:
                        best_d = d
                        best = m
            if best:
                selected_id = best["id"]

    # -------------------------------------------------
    # 4. TOGGLE PISTE (sempre visibile, ordinato ABC)
    # -------------------------------------------------
    NONE = "__NONE__"
    options = [NONE] + [m["id"] for m in sorted(meta, key=lambda x: x["name"].lower())]
    labels = ["— Nessuna —"] + [m["name"] for m in sorted(meta, key=lambda x: x["name"].lower())]
    label_map = {v: l for v, l in zip(options, labels)}

    def fmt(v): return label_map[v]

    current_val = selected_id if selected_id in options else NONE
    idx_default = options.index(current_val)

    chosen = st.selectbox("Pista", options, idx_default, format_func=fmt)

    # SOLO quando scegli una pista reale → spostiamo il marker
    if chosen != NONE and chosen != current_val:
        m = idmap[chosen]
        marker_lat = m["top_lat"]
        marker_lon = m["top_lon"]
        selected_id = chosen

    # -------------------------------------------------
    # 5. Salvataggio in ctx
    # -------------------------------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["selected_piste_id"] = selected_id

    # -------------------------------------------------
    # 6. Mappa
    # -------------------------------------------------
    m = folium.Map(location=[marker_lat, marker_lon], zoom_start=13, tiles=None)
    folium.TileLayer("OpenStreetMap").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery"
    ).add_to(m)

    # piste sempre mostrate (mai scompaiono!)
    for p in meta:
        is_sel = p["id"] == selected_id
        folium.PolyLine(
            p["coords"],
            color="red" if is_sel else "blue",
            weight=6 if is_sel else 3,
            opacity=1 if is_sel else 0.6,
        ).add_to(m)

    # marker
    folium.Marker([marker_lat, marker_lon], icon=folium.Icon(color="red")).add_to(m)

    st_folium(m, height=450, key=map_key)

    return ctx
