# core/pov_3d.py
# POV 3D WebGL (MapLibre GL) per Telemark · Pro Wax & Tune
#
# Funzioni principali:
#  - build_pov3d_html(): genera HTML 3D con camera che scende lungo la pista
#  - render_pov3d_view(): interfaccia Streamlit per generare il POV 3D
#
# Pronto per DEM ibrido (ESRI → SRTM).
# Non richiede Mapbox API.

from __future__ import annotations

import json
import math
from typing import List, Tuple, Optional, Dict, Any

import streamlit as st
from core.dem_tools import get_dem_for_polyline


# ----------------------------------------------------------
# Calcoli utili
# ----------------------------------------------------------
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2)**2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(dl / 2)**2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def cumulative_distance(poly):
    d = [0.0]
    tot = 0.0
    for i in range(1, len(poly)):
        seg = hav(poly[i-1][0], poly[i-1][1], poly[i][0], poly[i][1])
        tot += seg
        d.append(tot)
    return d, tot


# ----------------------------------------------------------
# HTML POV 3D WebGL
# ----------------------------------------------------------
def build_pov3d_html(
    piste_points: List[Tuple[float, float]],
    piste_name: Optional[str],
    dem_data: Optional[Tuple[Any, Tuple[float, float, float, float]]],
    duration_sec: int = 12,
) -> str:
    """
    Crea file HTML 3D con MapLibre GL.
    - Camera segue la pista
    - Pitch variabile
    - Bearing automatico
    - Altezza da DEM (se disponibile)
    """
    if not piste_points:
        return "<html><body>NO DATA</body></html>"

    # ------------------------------
    # Coordinate pista in JS
    # ------------------------------
    pts = [
        {"lat": lat, "lon": lon}
        for (lat, lon) in piste_points
    ]
    pts_js = json.dumps(pts)

    name = piste_name or "POV 3D"

    # ------------------------------
    # DEM?
    # ------------------------------
    dem_js = "null"
    bounds_js = "null"

    if dem_data:
        arr, bbox = dem_data
        dem_js = json.dumps(arr.tolist())
        bounds_js = json.dumps(bbox)

    # ------------------------------
    # HTML completo
    # ------------------------------
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{name} – POV 3D</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<script src="https://unpkg.com/maplibre-gl@3.3.1/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@3.3.1/dist/maplibre-gl.css" rel="stylesheet" />

<style>
html, body, #map {{
  margin:0; padding:0; height:100%; width:100%; background:black;
}}
.label {{
  position:absolute; top:10px; left:10px;
  color:white; z-index:9999;
  font-family:sans-serif; font-size:14px;
  text-shadow:0 0 4px black;
}}
</style>
</head>
<body>

<div class="label">{name}</div>
<div id="map"></div>

<script>
var pts = {pts_js};
var demData = {dem_js};
var bounds = {bounds_js};

// Center iniziale
var start = pts[0];
var map = new maplibregl.Map({{
    container: 'map',
    style: {{
        version: 8,
        sources: {{
            "osm": {{
                "type": "raster",
                "tiles": ["https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png"],
                "tileSize": 256
            }}
        }},
        layers: [
            {{
                "id": "osm",
                "type": "raster",
                "source": "osm"
            }}
        ]
    }},
    zoom: 15,
    center: [start.lon, start.lat],
    pitch: 60,
    bearing: 0,
    interactive: false,
    attributionControl: true
}});

// ----------------------------
// DEM fallback (hillshade)
// ----------------------------
if (demData !== null) {{
    // Qui potremmo aggiungere hillshade WebGL in futuro.
}}

map.on('load', function() {{
    // ----------------------------
    // Markers invisibili → camera path
    // ----------------------------

    var idx = 0;
    var max = pts.length - 1;
    var totalSteps = {duration_sec} * 30; // ~30fps
    var step = Math.ceil(max / totalSteps);

    function move() {{
        idx += step;
        if (idx >= max) idx = max;

        var p = pts[idx];

        // bearing dinamico verso il punto successivo
        var b = 0;
        if (idx < max) {{
            var p2 = pts[idx+1];
            b = Math.atan2(
                (p2.lon - p.lon),
                (p2.lat - p.lat)
            ) * 180 / Math.PI;
        }}

        // pitch dinamico (più ripido = più inclinato)
        var pitch = 60;

        map.easeTo({{
            center: [p.lon, p.lat],
            bearing: b,
            pitch: pitch,
            zoom: 15.5,
            duration: 60
        }});

        if (idx < max) {{
            requestAnimationFrame(move);
        }}
    }}

    // Inizializzazione
    map.easeTo({{
        pitch: 60,
        zoom: 15.5,
        duration: 1000
    }});

    setTimeout(move, 800);
});
</script>

</body>
</html>
"""


# ----------------------------------------------------------
# STREAMLIT WRAPPER
# ----------------------------------------------------------
def render_pov3d_view(
    ctx: Dict[str, Any],
    piste_points: List[Tuple[float, float]],
    piste_name: Optional[str],
):
    st.markdown("## 🏔️ POV 3D (WebGL)")

    if not piste_points or len(piste_points) < 2:
        st.warning("Pista non valida per il POV 3D.")
        return

    duration = st.slider(
        "Durata animazione (secondi)",
        min_value=5, max_value=30, value=12,
    )

    # DEM
    with st.spinner("Carico DEM per la pista…"):
        dem_data = get_dem_for_polyline(piste_points)

    html = build_pov3d_html(
        piste_points=piste_points,
        piste_name=piste_name,
        dem_data=dem_data,
        duration_sec=duration,
    )

    st.download_button(
        "⬇️ Scarica POV 3D (HTML)",
        data=html,
        file_name="telemark_pov3d.html",
        mime="text/html",
    )

    st.info("Apri il file nel browser e registra lo schermo per ottenere il video POV 3D.")
