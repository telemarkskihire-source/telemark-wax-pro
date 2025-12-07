# core/pov_video.py
# POV 3D realistico: volo lungo la pista su sfondo Mapbox satellitare
#
# - usa i punti di ctx["pov_piste_points"] (lat, lon, elev)
# - segue la pista con una camera inclinata (pitch) e orientata (bearing)
# - sfondo: immagini statiche Mapbox stile satellite-v9
# - output: GIF 12 s salvata in videos/<safe_name>_pov_12s.gif
#
# Richiede:
#   - MAPBOX_API_KEY in st.secrets["MAPBOX_API_KEY"] oppure in
#     variabile d'ambiente MAPBOX_API_KEY.

from __future__ import annotations

from typing import List, Dict, Any, Optional
import math
import os
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw

WIDTH = 800
HEIGHT = 450
FRAME_RATE = 12          # fps
VIDEO_DURATION = 12      # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION


# -------------------------------------------------------------
# GEO UTILS
# -------------------------------------------------------------
def _haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due coordinate lat/lon."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def build_track(points: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Converte i punti in una traccia continua con distanza cumulata.

    points: [{"lat": ..., "lon": ..., "elev": ...}, ...]
    ritorna: [{"lat", "lon", "elev", "dist"}, ...] dove dist è in metri.
    """
    track: List[Dict[str, float]] = []
    dist = 0.0
    prev: Optional[Dict[str, float]] = None

    for p in points:
        try:
            lat = float(p.get("lat"))
            lon = float(p.get("lon"))
            elev = float(p.get("elev", 0.0))
        except Exception:
            continue

        if prev is not None:
            dist += _haversine_dist(prev["lat"], prev["lon"], lat, lon)

        d = {"lat": lat, "lon": lon, "elev": elev, "dist": dist}
        track.append(d)
        prev = d

    return track


def _resample_track(track: List[Dict[str, float]], n_points: int) -> List[Dict[str, float]]:
    """
    Ridistribuisce la traccia su n_points punti equidistanti lungo la distanza.
    Serve per avere esattamente N_FRAMES frame uniformi.
    """
    if len(track) <= n_points:
        return track

    total = track[-1]["dist"]
    if total <= 0:
        return track

    result: List[Dict[str, float]] = []
    j = 1

    for i in range(n_points):
        td = total * i / (n_points - 1)  # distanza target per questo frame

        while j < len(track) and track[j]["dist"] < td:
            j += 1

        if j <= 0:
            result.append(track[0])
        elif j >= len(track):
            result.append(track[-1])
        else:
            p1 = track[j - 1]
            p2 = track[j]
            span = p2["dist"] - p1["dist"] or 1e-9
            t = (td - p1["dist"]) / span
            lat = p1["lat"] + (p2["lat"] - p1["lat"]) * t
            lon = p1["lon"] + (p2["lon"] - p1["lon"]) * t
            elev = p1["elev"] + (p2["elev"] - p1["elev"]) * t
            result.append({"lat": lat, "lon": lon, "elev": elev, "dist": td})

    return result


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Azimuth (gradi) da punto 1 a punto 2.
    0 = Nord, aumenta in senso orario (convenzione Mapbox).
    """
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (
        math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
        - math.sin(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.cos(math.radians(lon2 - lon1))
    )
    brng = math.degrees(math.atan2(y, x))
    return (brng + 360) % 360


# -------------------------------------------------------------
# MAPBOX TOKEN
# -------------------------------------------------------------
def _get_mapbox_token() -> Optional[str]:
    """
    Token da:
      - variabile d'ambiente MAPBOX_API_KEY
      - oppure st.secrets["MAPBOX_API_KEY"]
    """
    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if token:
        return token

    try:
        import streamlit as st

        if "MAPBOX_API_KEY" in st.secrets:
            t = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if t:
                return t
    except Exception:
        pass

    return None


# -------------------------------------------------------------
# FRAME RENDERING
# -------------------------------------------------------------
def _fetch_satellite_image(
    lat: float,
    lon: float,
    bearing: float,
    zoom: int,
    pitch: int,
    token: str,
) -> Image.Image:
    """
    Scarica una singola immagine statica da Mapbox (stile satellite).
    """
    url = (
        "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{lon:.6f},{lat:.6f},{zoom},{bearing:.1f},{pitch}/{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    img = Image.open(BytesIO(r.content)).convert("RGB")
    img = img.resize((WIDTH, HEIGHT))
    return img


def _winterize(img: Image.Image) -> Image.Image:
    """
    Semplice "filtro neve": schiarisce e tende al bianco/azzurro
    per dare un look invernale anche se la tile è estiva.
    """
    img = img.convert("RGB")
    snow = Image.new("RGB", img.size, (230, 238, 248))
    img = Image.blend(img, snow, 0.35)
    return img


def _draw_hud(
    img: Image.Image,
    piste_name: str,
    elev: float,
    dist_m: float,
    total_m: float,
) -> Image.Image:
    """
    Disegna HUD minimale: barra superiore con nome pista + quota + km,
    e mirino centrale per l'effetto "in prima persona".
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # barra in alto
    draw.rectangle([0, 0, w, 26], fill=(2, 10, 30))

    title = f"{piste_name} POV"
    info = f"Alt {elev:.0f} m  ·  {dist_m/1000:.2f}/{total_m/1000:.2f} km"

    draw.text((8, 6), title, fill=(220, 235, 255))
    tw = draw.textlength(info)
    draw.text((w - tw - 8, 6), info, fill=(200, 220, 240))

    # mirino
    cx, cy = w // 2, int(h * 0.7)
    draw.line([(cx - 12, cy), (cx + 12, cy)], fill=(255, 80, 40), width=2)
    draw.line([(cx, cy - 8), (cx, cy + 8)], fill=(255, 80, 40), width=2)

    return img


# -------------------------------------------------------------
# ENTRYPOINT PRINCIPALE
# -------------------------------------------------------------
def generate_pov_video(points: List[Dict[str, float]], pista_name: str) -> str:
    """
    Genera la GIF POV 3D 12 s per una pista.

    points: ctx["pov_piste_points"] (lista di dict con lat, lon, elev)
    ritorna: path stringa alla GIF salvata in videos/<nome>_pov_12s.gif
    """
    track = build_track(points)
    if len(track) < 5:
        raise RuntimeError("Traccia POV troppo corta per generare il video.")

    # Esattamente N_FRAMES punti lungo la pista
    track = _resample_track(track, N_FRAMES)

    token = _get_mapbox_token()
    if not token:
        raise RuntimeError(
            "MAPBOX_API_KEY non configurata (secrets o variabile d'ambiente)."
        )

    total_len = track[-1]["dist"]

    # Zoom più aperto per piste lunghe
    if total_len > 3500:
        zoom = 13
    elif total_len > 2500:
        zoom = 14
    elif total_len > 1500:
        zoom = 15
    else:
        zoom = 16

    pitch = 60  # inclinazione camera

    frames: List[Image.Image] = []

    for idx, p in enumerate(track):
        if idx < len(track) - 3:
            q = track[idx + 3]
        else:
            q = track[-1]

        bearing = _bearing_deg(p["lat"], p["lon"], q["lat"], q["lon"])

        try:
            img = _fetch_satellite_image(
                p["lat"], p["lon"], bearing, zoom, pitch, token
            )
        except Exception:
            # fallback: sfondo blu notte
            img = Image.new("RGB", (WIDTH, HEIGHT), (10, 30, 60))

        img = _winterize(img)
        img = _draw_hud(img, pista_name, p["elev"], p["dist"], total_len)
        frames.append(img)

    # salvataggio GIF
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.gif"

    duration_ms = int(1000 / FRAME_RATE)

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )

    return str(out_path)
