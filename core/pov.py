# core/pov.py
# POV pista · Telemark Pro Wax & Tune
#
# Nuova versione:
# - Filtra piste con coordinate reali (Italia-Alpi)
# - Mai più fallback (0,0)
# - DEM integrato tramite get_dem_for_polyline()
# - POV stabile con slider
# - Generatore HTML animato (fly-through)
# - Nessuna interferenza con la mappa principale

from __future__ import annotations

import json
import math
from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st
import pandas as pd
import altair as alt
import folium
from streamlit_folium import st_folium

from core.dem_tools import get_dem_for_polyline

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ---------------------------------------------------------
# 1) Overpass — fetch piste
# ---------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_downhill_pistes(lat: float, lon: float, radius_km: float = 10.0):
    """Scarica piste downhill via Overpass. Ritorna liste pulite."""
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
            timeout=25,
            headers=UA,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return [], []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    polylines = []
    names = []

    def _name(tags):
        if not tags:
            return None
        for k in ("piste:name", "name", "ref"):
            if k in tags and str(tags[k]).strip():
                return str(tags[k]).strip()
        return None

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        pts = []

        if el["type"] == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if nd:
                    pts.append((nd["lat"], nd["lon"]))

        elif el["type"] == "relation":
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (w for w in elements if w.get("type") == "way" and w.get("id") == wid),
                    None,
                )
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if nd:
                        pts.append((nd["lat"], nd["lon"]))

        # Filtra piste senza coordinate reali (piste mondiali random)
        if len(pts) >= 2 and _valid_polyline(pts):
            polylines.append(pts)
            names.append(_name(tags))

    return polylines, names


def _valid_polyline(poly: List[Tuple[float, float]]) -> bool:
    """Accetta solo piste reali Italia/Alpi (evita coordinate globali)."""
    for lat, lon in poly:
        if not (35 < lat < 47.7 and 5 < lon < 13.7):
            return False
    return True


# ---------------------------------------------------------
# 2) Utility distanza
# ---------------------------------------------------------
def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2)**2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlambda / 2)**2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _distance_profile(polyline):
    dists = [0.0]
    tot = 0.0
    for i in range(1, len(polyline)):
        lat1, lon1 = polyline[i - 1]
        lat2, lon2 = polyline[i]
        seg = _haversine_m(lat1, lon1, lat2, lon2)
        tot += seg
        dists.append(tot)
    return dists, tot


def _nearest_piste_to_point(lat: float, lon: float, polylines):
    best_idx = None
    best_d = float("inf")
    for i, ln in enumerate(polylines):
        for la, lo in ln:
            d = _haversine_m(lat, lon, la, lo)
            if d < best_d:
                best_d = d
                best_idx = i
    return best_idx, best_d


# ---------------------------------------------------------
# 3) Costruzione HTML POV
# ---------------------------------------------------------
def _build_pov_html(piste_points, piste_name, duration_seconds=8):
    if not piste_points:
        return "<html><body>NO DATA</body></html>"

    points_js = json.dumps(piste_points)
    start_lat, start_lon = piste_points[0]

    name_label = piste_name or "POV"

    N = max(2, len(piste_points))
    total_ms = max(1200, duration_seconds * 1000)
    step_ms = max(20, int(total_ms / N))

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{name_label} – POV Telemark</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
html,body,#map {{ height:100%; margin:0; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var pts = {points_js};
var map = L.map('map').setView([{start_lat},{start_lon}], 15);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

var line = L.polyline(pts, {{color:'#38bdf8',weight:4}}).addTo(map);
map.fitBounds(line.getBounds());

var marker = L.marker(pts[0]).addTo(map);

var i=0;
var maxI = pts.length-1;
var step = {step_ms};

function animate(){{
    i++;
    if(i>maxI) return;
    marker.setLatLng(pts[i]);
    map.panTo(pts[i], {{animate:true,duration:step/1000}});
    if(i<maxI) setTimeout(animate, step);
}}
setTimeout(animate, 500);
</script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------
# 4) STREAMLIT POV VIEW
# ---------------------------------------------------------
def render_pov_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    st.markdown("## 🎥 POV pista (beta)")

    base_lat = float(ctx.get("marker_lat", ctx.get("lat", 45.833)))
    base_lon = float(ctx.get("marker_lon", ctx.get("lon", 7.733)))

    enable = st.checkbox(
        "Attiva POV sulla pista più vicina",
        value=True,
        key=f"pov_enable_{ctx.get('map_context','default')}",
    )
    if not enable:
        return ctx

    with st.spinner("Cerco piste downhill vicine…"):
        polylines, names = _fetch_downhill_pistes(base_lat, base_lon)

    if not polylines:
        st.warning("Nessuna pista downhill valida trovata.")
        return ctx

    idx, distm = _nearest_piste_to_point(base_lat, base_lon, polylines)
    if idx is None:
        st.warning("Impossibile trovare la pista più vicina.")
        return ctx

    piste = polylines[idx]
    pname = names[idx]

    dists, total_m = _distance_profile(piste)
    if total_m <= 0:
        st.warning("Pista non valida per POV.")
        return ctx

    # Slider POV
    col_sl, col_info = st.columns([2, 1])
    with col_sl:
        pct = st.slider(
            "Posizione lungo la pista (POV)",
            0, 100, 0, 1,
            key=f"pov_pct_{ctx.get('map_context','default')}",
        )
    with col_info:
        st.markdown(f"**Lunghezza stimata:** {total_m/1000:.2f} km")

    target = total_m * pct / 100
    i = 0
    while i < len(dists) - 1 and dists[i] < target:
        i += 1

    lat, lon = piste[i]

    # DEM
    dem, bbox = get_dem_for_polyline(piste)
    if dem is None:
        st.info("DEM non disponibile ora (ESRI/SRTM).")

    # Salvo contesto
    ctx["pov_lat"] = lat
    ctx["pov_lon"] = lon
    ctx["pov_piste_name"] = pname
    ctx["pov_piste_length_m"] = total_m

    # Mappa POV
    m = folium.Map(location=[lat, lon], zoom_start=14, control_scale=True)
    folium.TileLayer("OpenStreetMap").add_to(m)

    folium.PolyLine(piste, color="blue", weight=4).add_to(m)
    folium.Marker([lat, lon], icon=folium.Icon(color="red", icon="play")).add_to(m)

    if pname:
        mi = len(piste) // 2
        folium.Marker(
            piste[mi],
            icon=folium.DivIcon(html=f"<div style='color:white;font-size:11px;text-shadow:0 0 3px black'>{pname}</div>")
        ).add_to(m)

    st_folium(m, height=420, key=f"pov_map_{ctx.get('map_context','default')}")

    # Profilo distanza (placeholder per altimetria futura col DEM)
    df = pd.DataFrame({"dist_m": dists})
    df["dist_km"] = df["dist_m"] / 1000
    df["idx"] = df.index

    chart = alt.Chart(df).mark_line().encode(
        x=alt.X("dist_km", title="Distanza (km)"),
        y=alt.Y("idx", title="Indice punto"),
    ).properties(height=150)
    st.altair_chart(chart, use_container_width=True)

    # Download POV HTML
    html = _build_pov_html(piste, pname)
    st.download_button(
        "⬇️ Scarica POV (HTML animato)",
        data=html,
        file_name="telemark_pov.html",
        mime="text/html",
    )

    return ctx
