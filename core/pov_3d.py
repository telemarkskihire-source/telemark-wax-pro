# core/pov_3d.py
# Telemark · Pro Wax & Tune — POV 3D V7
#
# Genera:
#   - HTML 3D con camera che segue la pista
#   - iframe viewer integrato in Streamlit
#
# La pista deve essere in ctx["pov_piste_points"]:
#   [{"lat":..., "lon":..., "ele":...}, ...]

from __future__ import annotations

import json
import uuid
from typing import List, Dict, Any

import streamlit as st


# -----------------------------------------------------------
# UTILITY: convert lat/lon/ele → x,y,z con proiezione semplice
# -----------------------------------------------------------
def _to_xyz(points: List[Dict[str, float]]) -> List[List[float]]:
    """
    Trasforma lat/lon in coordinate locali (metri)
    mantenendo ele come z.
    """
    if not points:
        return []

    lat0 = points[0]["lat"]
    lon0 = points[0]["lon"]

    out = []
    for p in points:
        lat = p["lat"]
        lon = p["lon"]
        ele = p.get("ele", 0.0)

        x = (lon - lon0) * 40075000 * (3.1415926535 / 180) * (
            abs(lat0) / 90 if abs(lat0) < 89 else 1
        ) / 360
        y = (lat - lat0) * (40075000 / 360)
        z = ele

        out.append([x, y, z])

    return out


# -----------------------------------------------------------
# GENERA HTML 3D STANDALONE
# -----------------------------------------------------------
def build_pov3d_html(xyz: List[List[float]], track_name: str) -> str:
    if not xyz:
        return "<html><body><h3>No POV 3D data</h3></body></html>"

    pts_js = json.dumps(xyz)
    name = track_name or "Pista"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>POV 3D – {name}</title>
<style>
html,body {{ margin:0; padding:0; background:#000; overflow:hidden; }}
#c {{ width:100vw; height:100vh; display:block; }}
</style>
</head>
<body>
<canvas id="c"></canvas>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>

<script>
const pts = {pts_js};

let scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

let camera = new THREE.PerspectiveCamera(70, window.innerWidth/window.innerHeight, 0.1, 50000);
camera.position.set(0, -50, 20);

let renderer = new THREE.WebGLRenderer({{canvas: document.getElementById("c"), antialias:true}});
renderer.setSize(window.innerWidth, window.innerHeight);

const light = new THREE.DirectionalLight(0xffffff, 1.2);
light.position.set(50, -50, 200);
scene.add(light);

const amb = new THREE.AmbientLight(0x888888);
scene.add(amb);

// Convert piste → curve
const geom = new THREE.BufferGeometry();
const flat = pts.flat();
geom.setAttribute('position', new THREE.Float32BufferAttribute(flat, 3));

const mat = new THREE.LineBasicMaterial({{color:0x66ccff, linewidth:4}});
const line = new THREE.Line(geom, mat);
scene.add(line);

// Camera animation
let i = 0;
function animate() {{
    requestAnimationFrame(animate);

    if(i < pts.length) {{
        let p = pts[i];
        camera.position.set(p[0], p[1]-20, p[2]+8);
        camera.lookAt(p[0], p[1], p[2]);
        i++;
    }}

    renderer.render(scene, camera);
}}

animate();

window.addEventListener('resize', ()=>{
    camera.aspect = window.innerWidth/window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});
</script>

</body>
</html>
"""


# -----------------------------------------------------------
# STREAMLIT RENDERER (iframe + download)
# -----------------------------------------------------------
def render_pov3d_view(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Richiede:
        ctx["pov_piste_points"] = [{"lat":..., "lon":..., "ele":...}, ...]
        ctx["pov_piste_name"]
    """
    st.markdown("### 🎥 POV 3D (beta)")

    pts = ctx.get("pov_piste_points")
    name = ctx.get("pov_piste_name", "Pista")

    if not pts:
        st.info("Nessuna pista disponibile per il POV 3D.")
        return ctx

    # Convert lat/lon/ele → XYZ
    xyz = _to_xyz(pts)

    # Generate HTML
    html = build_pov3d_html(xyz, name)

    # Unique iframe id
    frame_id = f"pov3d_{uuid.uuid4().hex}"

    # Iframe viewer
    st.components.v1.html(
        html,
        height=450,
        scrolling=False,
    )

    # Download button
    st.download_button(
        "⬇️ Scarica POV 3D (HTML)",
        data=html,
        file_name="pov3d_telemark.html",
        mime="text/html",
    )

    return ctx
