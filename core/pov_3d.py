# core/pov_3d.py
# POV 3D (viewer HTML) per Telemark · Pro Wax & Tune
#
# Assunzioni:
# - ctx["pov_piste_points"] contiene una lista di punti della pista
#   in uno di questi formati:
#       [(lat, lon), (lat, lon), ...]
#       [{"lat": ..., "lon": ...}, ...]
# - ctx["pov_piste_name"] opzionale (nome pista)
#
# La funzione principale è:
#     render_pov3d_view(T, ctx) -> ctx
#
# Mostra un viewer "tipo 3D" (animazione in mappa) dentro Streamlit
# usando un componente HTML standalone.

from __future__ import annotations

from typing import Dict, Any, List, Sequence
import json

import streamlit as st
from streamlit.components.v1 import html as st_html


def _normalize_points(raw_points: Sequence[Any]) -> List[List[float]]:
    """
    Converte la lista generica di punti in [[lat, lon], ...] float.
    Accetta:
      - (lat, lon)
      - (lat, lon, ele)
      - {"lat": .., "lon": ..} o chiavi simili
    """
    norm: List[List[float]] = []

    for p in raw_points:
        lat = None
        lon = None

        # dizionario
        if isinstance(p, dict):
            for k in ("lat", "latitude", "y"):
                if k in p:
                    lat = p[k]
                    break
            for k in ("lon", "lng", "longitude", "x"):
                if k in p:
                    lon = p[k]
                    break

        # tupla / lista
        elif isinstance(p, (tuple, list)) and len(p) >= 2:
            lat, lon = p[0], p[1]

        if lat is None or lon is None:
            continue

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            continue

        norm.append([lat_f, lon_f])

    return norm


def _build_pov3d_html(points: List[List[float]], name: str) -> str:
    """
    Costruisce una pagina HTML standalone con Leaflet:
    - polyline della pista
    - marker che scorre automaticamente lungo la pista (animazione)
    - la mappa segue il marker (panTo)
    """
    if not points:
        points = [[0.0, 0.0]]

    start_lat, start_lon = points[0]
    points_js = json.dumps(points)

    # durata animazione ~8s
    n_points = max(2, len(points))
    total_ms = 8000
    step_ms = max(30, int(total_ms / n_points))

    safe_name = name.replace('"', "'")

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8" />
  <title>{safe_name} – POV 3D</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  />
  <style>
    html, body, #map {{
      height: 100%;
      margin: 0;
      padding: 0;
      background: #000;
    }}
    .pov-label {{
      color: #f9fafb;
      font-size: 11px;
      text-shadow: 0 0 3px #000, 0 0 5px #000;
      font-family: system-ui, -apple-system, BlinkMacSystemFont,
                   "Segoe UI", sans-serif;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin="">
  </script>
  <script>
    var points = {points_js};

    var map = L.map('map', {{
      zoomControl: true
    }}).setView([{start_lat}, {start_lon}], 15);

    // Satellite + strade per effetto "3D"
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
      {{
        maxZoom: 19,
        attribution: "Esri World Imagery"
      }}
    ).addTo(map);

    // Polyline pista
    var line = L.polyline(points, {{
      color: "#38bdf8",
      weight: 4,
      opacity: 0.95
    }}).addTo(map);

    map.fitBounds(line.getBounds());

    // Label centrale
    var midIdx = Math.floor(points.length / 2);
    var midLatLng = L.latLng(points[midIdx][0], points[midIdx][1]);
    var name = "{safe_name}";
    if (name.length > 0) {{
      L.marker(midLatLng, {{
        icon: L.divIcon({{
          className: "pov-label",
          html: name
        }})
      }}).addTo(map);
    }}

    // Marker POV (play)
    var marker = L.marker(points[0], {{
      icon: L.icon({{
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        iconAnchor: [12, 41],
        popupAnchor: [0, -28]
      }})
    }}).addTo(map);

    var idx = 0;
    var maxIdx = points.length - 1;
    var stepMs = {step_ms};

    function step() {{
      idx += 1;
      if (idx > maxIdx) {{
        return;
      }}
      var latlng = L.latLng(points[idx][0], points[idx][1]);
      marker.setLatLng(latlng);
      map.panTo(latlng, {{ animate: true, duration: stepMs / 1000 }});
      if (idx < maxIdx) {{
        setTimeout(step, stepMs);
      }}
    }}

    // piccola pausa iniziale, poi parte il "volo"
    setTimeout(step, 600);
  </script>
</body>
</html>
"""
    return html


def render_pov3d_view(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Viewer POV 3D:
      - usa ctx["pov_piste_points"] come lista di punti
      - opzionalmente ctx["pov_piste_name"]
      - embeddizza un HTML con animazione del marker lungo la pista
    """
    raw_points = ctx.get("pov_piste_points")
    if not raw_points:
        # niente pista → niente POV 3D
        st.info("Nessuna pista disponibile per il POV 3D in questa località.")
        return ctx

    points = _normalize_points(raw_points)
    if not points:
        st.info("Formato punti pista non valido per il POV 3D.")
        return ctx

    piste_name = ctx.get("pov_piste_name") or "Pista POV"

    html_data = _build_pov3d_html(points, piste_name)

    # Mostra il viewer dentro la pagina
    st_html(html_data, height=420, scrolling=False)

    return ctx
