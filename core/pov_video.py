# core/pov_video.py
# VERSIONE 5 — NON CACHEABILE — PATH ULTRACORTO
# Generatore POV affidabile con Mapbox Static API

from __future__ import annotations
VERSION = "5.0"  # forza Streamlit a ricaricare il modulo

from typing import Any, Dict, List, Sequence, Union
import io
import math
import os
from pathlib import Path

import numpy as np
import requests
from PIL import Image
import imageio.v2 as imageio
import streamlit as st


WIDTH = 1280
HEIGHT = 720
DURATION_S = 12.0
FPS = 25

STYLE_ID = "mapbox/satellite-v9"
LINE_COLOR = "ff4422"
LINE_WIDTH = 4
LINE_OPACITY = 0.9


def _get_token() -> str:
    try:
        t = st.secrets["MAPBOX_API_KEY"]
        if t:
            return t
    except Exception:
        pass
    t = os.environ.get("MAPBOX_API_KEY", "")
    if not t:
        raise RuntimeError("MAPBOX_API_KEY mancante.")
    return t


def _as_points(track):
    pts = []
    for p in track:
        pts.append({"lat": float(p["lat"]), "lon": float(p["lon"])})
    return pts


def _bearing(a, b):
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
    br = math.degrees(math.atan2(x, y))
    return (br + 360) % 360


def _short_path(points: List[Dict[str, float]]) -> str:
    """
    Costruisce sempre un path *ultra corto*:
    - prima 4 punti
    - se errore, verrà ridotto a 3 → 2
    """
    def build(pts):
        s = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
        return f"path-{LINE_WIDTH}+{LINE_COLOR}-{LINE_OPACITY}({s})"

    pts = points.copy()

    # 4 punti equidistanti
    if len(pts) > 4:
        idx = np.linspace(0, len(pts)-1, 4).astype(int)
        pts = [pts[i] for i in idx]

    return build(pts)


def _fetch_frame(token, c, bearing, path_param):
    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{c['lon']:.5f},{c['lat']:.5f},16.3,{bearing:.1f},72/"
        f"{WIDTH}x{HEIGHT}?"
        f"access_token={token}"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def generate_pov_video(track, pista_name, duration_s=DURATION_S, fps=FPS):
    token = _get_token()
    pts = _as_points(track)

    if len(pts) < 2:
        raise ValueError("Pista troppo corta.")

    # Prepara path corto
    path_param = _short_path(pts)

    # Timeline
    n_frames = int(duration_s * fps)
    idx_float = np.linspace(0, len(pts)-2, n_frames)

    centers = []
    bearings = []
    for t in idx_float:
        i = int(t)
        frac = t - i
        a, b = pts[i], pts[i+1]
        centers.append({
            "lat": a["lat"] + (b["lat"] - a["lat"])*frac,
            "lon": a["lon"] + (b["lon"] - a["lon"])*frac,
        })
        bearings.append(_bearing(a, b))

    frames = []
    for c, brr in zip(centers, bearings):
        img = _fetch_frame(token, c, brr, path_param)
        frames.append(np.asarray(img))

    # Salvataggio MP4
    out_dir = Path("videos")
    out_dir.mkdir(exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in pista_name.lower())
    mp4 = out_dir / f"{safe}_pov.mp4"

    try:
        w = imageio.get_writer(str(mp4), fps=fps, codec="libx264")
        for f in frames:
            w.append_data(f)
        w.close()
        return str(mp4)
    except Exception:
        gif = out_dir / f"{safe}_pov.gif"
        imageio.mimsave(str(gif), frames, fps=fps)
        return str(gif)
