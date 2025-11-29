# core/pov.py
# POV 2D (solo export) + estrazione pista per POV 3D
# V7 – Telemark · Pro Wax & Tune
#
# Questo modulo NON mostra mappe in pagina.
# Serve solo per:
#   - trovare la pista downhill più vicina via Overpass
#   - calcolare profilo distanza
#   - esportare POV 2D HTML
#   - preparare ctx["pov_piste_points"] per POV 3D

from __future__ import annotations

import json
import math
from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st


UA = {"User-Agent": "telemark-wax-pro/3.1"}


# ------------------------------------------------------------------
# 1) Overpass → downhill pistes
# ------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_pistes(lat: float, lon: float, radius_km: float = 10) -> Tuple[List, List]:
    """Ritorna (polylines, names)."""
    radius_m = int(radius_km * 1000)

    q = f"""
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
            data=q.encode("utf-8"),
            headers=UA,
            timeout=25,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return [], []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    polylines = []
    names = []

    def _nm(tags):
        if not tags:
            return None
        for key in ("piste:name", "name", "ref"):
            val = tags.get(key)
            if val and str(val).strip():
                return str(val).strip()
        return None

    def valid(pt):
        lat, lon = pt
        return (35 < lat < 48) and (5 < lon < 14)

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
                    pt = (nd["lat"], nd["lon"])
                    if valid(pt):
                        pts.append(pt)

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
                        pt = (nd["lat"], nd["lon"])
                        if valid(pt):
                            pts.append(pt)

        if len(pts) >= 2:
            polylines.append(pts)
            names.append(_nm(tags))

    return polylines, names


# ------------------------------------------------------------------
# 2) Distanze e pista più vicina
# ------------------------------------------------------------------
def haversine_m(a, b, c, d):
    R = 6371000.0
    dphi = math.radians(c - a)
    dl = math.radians(d - b)
    aa = (
        math.sin(dphi / 2) ** 2
        + math.cos(math.radians(a))
        * math.cos(math.radians(c))
        * math.sin(dl / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(aa), math.sqrt(1 - aa))


def distance_profile(pts: List[Tuple[float, float]]):
    d = [0.0]
    tot = 0.0
    for i in range(1, len(pts)):
        lat1, lon1 = pts[i - 1]
        lat2, lon2 = pts[i]
        seg = haversine_m(lat1, lon1, lat2, lon2)
        tot += seg
        d.append(tot)
    return d, tot


def nearest_piste(lat, lon, polylines):
    best = None
    best_d = float("inf")
    for i, line in enumerate(polylines):
        for la, lo in line:
            d = haversine_m(lat, lon, la, lo)
            if d < best_d:
                best_d = d
                best = i
    return best, best_d


# ------------------------------------------------------------------
# 3) POV 2D flythrough HTML
# ------------------------------------------------------------------
def build_pov2d_html(points: List[Tuple[float, float]], name: Optional[str]) -> str:
    if not points:
        return "<html><body><h3>Nessun dato POV</h3></body></html>"

    pts_js = json.dumps(points)
    start_lat, start_lon = points[0]

    N = max(2, len(points))
    step_ms = max(20, int(8000 / N))

    label = name or "Pista"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>POV 2D – {label}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
html,body,#map {{ margin:0; padding:0; height:100%; background:#000; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var pts = {pts_js};
var map = L.map('map').setView([{start_lat},{start_lon}], 15);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
var line = L.polyline(pts, {{color:'#38bdf8',weight:4}}).addTo(map);
map.fitBounds(line.getBounds());
var m = L.marker(pts[0]).addTo(map);

let i = 0;
const maxI = pts.length - 1;
const step = {step_ms};

function move(){{
    i++;
    if(i>maxI) i=maxI;
    var p = pts[i];
    m.setLatLng(p);
    map.panTo(p, {{animate:true, duration: step/1000}});
    if(i<maxI) requestAnimationFrame(move);
}}
setTimeout(move, 400);
</script>
</body>
</html>
"""


# ------------------------------------------------------------------
# 4) Public entry: extract piste + attach to ctx + export POV 2D
# ------------------------------------------------------------------
def render_pov_extract(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    ESCLUSIVAMENTE:
    - trova pista più vicina
    - popola ctx["pov_piste_points"] in formato:
         [{"lat":..., "lon":..., "ele":0.0}, ...]
    - offre pulsante "Scarica POV 2D"
    (Il POV 3D è gestito da core/pov_3d.py)
    """
    import streamlit as st

    st.markdown("### 🎥 POV – estrazione pista")

    base_lat = float(ctx.get("marker_lat", ctx.get("lat", 45.833)))
    base_lon = float(ctx.get("marker_lon", ctx.get("lon", 7.733)))

    with st.spinner("Cerco piste downhill vicine…"):
        polylines, names = fetch_pistes(base_lat, base_lon)

    if not polylines:
        st.info("Nessuna pista downhill trovata.")
        return ctx

    idx, dist = nearest_piste(base_lat, base_lon, polylines)
    if idx is None:
        st.info("Nessuna pista valida trovata.")
        return ctx

    pts = polylines[idx]
    name = names[idx] or "Pista"

    # Convert to 3D format expected by POV 3D (ele=0 for now)
    pts3d = [{"lat": la, "lon": lo, "ele": 0.0} for (la, lo) in pts]
    ctx["pov_piste_points"] = pts3d
    ctx["pov_piste_name"] = name

    # POV 2D download
    html2d = build_pov2d_html(pts, name)
    st.download_button(
        "⬇️ Scarica POV 2D (HTML)",
        data=html2d,
        file_name="pov2d_telemark.html",
        mime="text/html"
    )

    st.success(f"Pista trovata: {name} · {len(pts)} punti")

    return ctx
