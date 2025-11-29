# core/pov_3d.py
# POV 3D WebGL generator (V7)
# Telemark · Pro Wax & Tune

from __future__ import annotations
import json
import base64
from typing import List, Dict, Any, Optional


# ---------------------------------------------------------------------
# Small helper: convert (lat,lon,ele) list → JSON for JS
# ---------------------------------------------------------------------
def _encode_points(points: List[Dict[str, float]]) -> str:
    """
    Converte una lista:
    [{"lat":..., "lon":..., "ele":...}, ...]
    in una stringa JSON sicura per essere inserita nel JS.
    """
    return json.dumps(points, separators=(",", ":"))


# ---------------------------------------------------------------------
# Generate pure HTML (download) for POV 3D
# ---------------------------------------------------------------------
def generate_pov3d_html(points: List[Dict[str, float]]) -> str:
    """
    Ritorna una pagina HTML completa, autosufficiente,
    che mostra il POV 3D animato con MapLibre + deck.gl.

    points deve essere una lista di:
    {"lat": float, "lon": float, "ele": float}
    """
    if not points or len(points) < 2:
        return "<html><body><h3>Nessun punto per POV 3D</h3></body></html>"

    pts_json = _encode_points(points)

    # HTML completo, con MapLibre GL + deck.gl + animazione camera
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>POV 3D – Telemark</title>
<style>
  html, body {{
    margin:0; padding:0; overflow:hidden;
    background:#000;
    width:100%; height:100%;
  }}
  #map {{
    position:absolute;
    top:0; left:0; width:100%; height:100%;
  }}
</style>

<!-- MapLibre GL -->
<link
  href="https://cdn.jsdelivr.net/npm/maplibre-gl@3.3.1/dist/maplibre-gl.css"
  rel="stylesheet"
/>
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@3.3.1/dist/maplibre-gl.js"></script>

<!-- deck.gl -->
<script src="https://cdn.jsdelivr.net/npm/deck.gl@latest/dist.min.js"></script>

</head>
<body>

<div id="map"></div>

<script>
const points = {pts_json};

// Center map on first point
const center = [points[0].lon, points[0].lat];

const map = new maplibregl.Map({{
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: center,
    zoom: 13,
    pitch: 75,
    bearing: 0,
    antialias: true
}});

// Create deck.gl layer for the path
const lineCoords = points.map(p => [p.lon, p.lat, p.ele || 0]);

const deckLayer = new deck.LineLayer({{
    id: 'pov-path',
    data: lineCoords,
    getSourcePosition: d => d,
    getTargetPosition: (d,i) => lineCoords[i+1] || d,
    getColor: [0, 150, 255, 255],
    getWidth: 6,
}});

const deckgl = new deck.DeckGL({{
    map: map,
    layers: [deckLayer]
}});

// Simple camera animation along the path
let idx = 0;
function animate() {{
    idx = (idx + 1) % lineCoords.length;
    const p = points[idx];
    const next = points[(idx+1)%points.length];

    const bearing = turf.bearing(
        [p.lon, p.lat],
        [next.lon, next.lat]
    );

    map.easeTo({{
        center: [p.lon, p.lat],
        bearing: bearing,
        zoom: 14.5,
        pitch: 75,
        duration: 500
    }});

    requestAnimationFrame(animate);
}}

// Include Turf.js just before animate()
</script>
<script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"
 onload="animate()"></script>

</body>
</html>
"""
    return html


# ---------------------------------------------------------------------
# Create an iframe snippet to embed POV 3D inside Streamlit
# ---------------------------------------------------------------------
def generate_pov3d_iframe_html(points: List[Dict[str, float]], height: int = 420) -> str:
    """
    Genera un iframe HTML che Streamlit può mostrare con st.components.v1.html(...)
    """
    html = generate_pov3d_html(points)
    # Base64 → data URL
    b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f"""
<iframe src="data:text/html;base64,{b64}"
        width="100%" height="{height}px"
        style="border:0; border-radius:12px; overflow:hidden;">
</iframe>
"""


# ---------------------------------------------------------------------
# Public API used by streamlit_app.py
# ---------------------------------------------------------------------
def render_pov3d_block(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Blocca UI POV 3D. Dipende da ctx["pov_piste_points"],
    che deve essere popolato dal modulo core.pov (estrazione pista).
    """
    import streamlit as st
    from streamlit.components.v1 import html as st_html

    st.markdown("### 🎥 POV 3D – Anteprima")

    points = ctx.get("pov_piste_points")
    if not points:
        st.info("Nessun tracciato sufficiente per POV 3D.")
        return ctx

    iframe = generate_pov3d_iframe_html(points, height=420)
    st_html(iframe, height=440)

    # Download button (POV 3D)
    html3d = generate_pov3d_html(points)
    st.download_button(
        "⬇️ Scarica POV 3D (HTML)",
        data=html3d,
        file_name="pov3d_telemark.html",
        mime="text/html"
    )

    return ctx
