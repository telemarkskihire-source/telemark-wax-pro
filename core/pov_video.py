# core/pov_video.py
# Generatore POV video 3D con Mapbox Static Images
#
# - Input: lista di punti pista [{lat, lon, elev}, ...]
# - Pulizia salti folli, scelta segmento principale
# - Resample in ~180 frame (12 s a 15 fps)
# - Per ogni frame:
#     * chiama Mapbox Static API (satellite, pitch alto, zoom "basso")
#     * centra la camera sul punto corrente
#     * bearing allineato alla direzione della pista
#     * path rosso della pista intera
#     * applica filtro "inverno"
# - Output: MP4 in videos/<safe_name>_pov_12s.mp4

from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import math
from pathlib import Path
from urllib.parse import quote

import requests
import numpy as np
from PIL import Image, ImageEnhance
import streamlit as st  # per leggere st.secrets
from moviepy.editor import ImageSequenceClip

UA = {"User-Agent": "telemark-wax-pro/2.0"}


# ---------------------------------------------------------------------
# MAPBOX TOKEN
# ---------------------------------------------------------------------
def _get_mapbox_token() -> Optional[str]:
    """
    Cerca la MAPBOX_API_KEY in:
      - st.secrets["MAPBOX_API_KEY"]
      - variabile d'ambiente MAPBOX_API_KEY
    """
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            token = str(st.secrets["MAPBOX_API_KEY"]).strip()
            if token:
                return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    return token or None


# ---------------------------------------------------------------------
# GEO UTILS
# ---------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due punti lat/lon (haversine semplificata)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing (gradi) da (lat1,lon1) a (lat2,lon2)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlambda
    )
    brng = math.degrees(math.atan2(y, x))
    return (brng + 360.0) % 360.0


def _pick_main_segment(points: List[Dict[str, float]], max_jump_m: float = 2000.0) -> List[Dict[str, float]]:
    """
    Tiene solo il segmento continuo più lungo,
    eliminando salti assurdi (> max_jump_m).
    """
    if len(points) < 2:
        return points

    segments: List[List[Dict[str, float]]] = []
    current: List[Dict[str, float]] = [points[0]]

    for i in range(1, len(points)):
        p_prev = points[i - 1]
        p = points[i]
        d = _dist_m(
            float(p_prev.get("lat", 0.0)),
            float(p_prev.get("lon", 0.0)),
            float(p.get("lat", 0.0)),
            float(p.get("lon", 0.0)),
        )
        if d <= max_jump_m:
            current.append(p)
        else:
            if len(current) >= 2:
                segments.append(current)
            current = [p]

    if len(current) >= 2:
        segments.append(current)

    if not segments:
        return points

    def seg_length(seg: List[Dict[str, float]]) -> float:
        tot = 0.0
        for i in range(1, len(seg)):
            a = seg[i - 1]
            b = seg[i]
            tot += _dist_m(
                float(a.get("lat", 0.0)),
                float(a.get("lon", 0.0)),
                float(b.get("lat", 0.0)),
                float(b.get("lon", 0.0)),
            )
        return tot

    return max(segments, key=seg_length)


def _resample_by_distance(points: List[Dict[str, float]], n_samples: int) -> List[Dict[str, float]]:
    """
    Resample della pista su distanza cumulativa (step costante).
    """
    if len(points) <= n_samples:
        return points

    # distanza cumulativa
    dists = [0.0]
    for i in range(1, len(points)):
        p_prev = points[i - 1]
        p = points[i]
        dists.append(
            dists[-1]
            + _dist_m(
                float(p_prev["lat"]),
                float(p_prev["lon"]),
                float(p["lat"]),
                float(p["lon"]),
            )
        )

    total = dists[-1]
    if total <= 0:
        return points

    step = total / (n_samples - 1)
    targets = [i * step for i in range(n_samples)]

    resampled: List[Dict[str, float]] = []
    j = 0
    for t in targets:
        while j < len(dists) - 2 and dists[j + 1] < t:
            j += 1
        d0, d1 = dists[j], dists[j + 1]
        if d1 == d0:
            alpha = 0.0
        else:
            alpha = (t - d0) / (d1 - d0)
        p0, p1 = points[j], points[j + 1]
        lat = float(p0["lat"]) + alpha * (float(p1["lat"]) - float(p0["lat"]))
        lon = float(p0["lon"]) + alpha * (float(p1["lon"]) - float(p0["lon"]))
        elev = float(p0.get("elev", 0.0)) + alpha * (
            float(p1.get("elev", 0.0)) - float(p0.get("elev", 0.0))
        )
        resampled.append({"lat": lat, "lon": lon, "elev": elev})
    return resampled


# ---------------------------------------------------------------------
# MAPBOX STATIC FRAME
# ---------------------------------------------------------------------
def _build_path_overlay(points: List[Dict[str, float]]) -> str:
    """
    Costruisce la stringa 'path-5+ff4422-1(lon,lat;lon,lat;...)'
    downsamplando per non esagerare con la lunghezza dell'URL.
    """
    if len(points) > 80:
        # downsample per path overlay
        step = max(1, len(points) // 80)
        pts = points[::step]
    else:
        pts = points

    coords = ";".join(f"{p['lon']},{p['lat']}" for p in pts)
    return f"path-5+ff4422-1({coords})"


def _fetch_mapbox_frame(
    token: str,
    path_overlay: str,
    center_lat: float,
    center_lon: float,
    bearing: float,
    zoom: float = 16.8,
    pitch: float = 60.0,
    size: str = "800x450",
) -> Image.Image:
    """
    Scarica un frame dal Mapbox Static Images API (satellite, 3D-like).
    """
    style = "mapbox/satellite-v9"

    overlay_encoded = quote(path_overlay, safe="():,;+-")
    # center: lon,lat,zoom,bearing,pitch
    center = f"{center_lon},{center_lat},{zoom},{bearing},{pitch}"

    url = (
        f"https://api.mapbox.com/styles/v1/{style}/static/"
        f"{overlay_encoded}/{center}/{size}"
        f"?access_token={token}"
    )

    resp = requests.get(url, headers=UA, timeout=15)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")  # type: ignore[name-defined]
    return img


# ---------------------------------------------------------------------
# WINTER FILTER
# ---------------------------------------------------------------------
def _apply_winter_filter(img: Image.Image) -> Image.Image:
    """
    Semplice look "invernale":
    - leggermente desaturato
    - più freddo (canale blu)
    - velo bianco semi-trasparente
    """
    # desatura leggermente
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(0.85)

    # piccolo boost di blu
    r, g, b = img.split()
    b = ImageEnhance.Brightness(b).enhance(1.1)
    img = Image.merge("RGB", (r, g, b))

    # velo neve
    overlay = Image.new("RGBA", img.size, (230, 240, 255, 70))
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, overlay)

    return img_rgba.convert("RGB")


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------
def generate_pov_video(points: List[Dict[str, Any]], pista_name: str) -> str:
    """
    Genera un video POV 3D (12 s) con Mapbox e ritorna il path del file MP4.
    """
    if not points or len(points) < 4:
        raise ValueError("Traccia pista insufficiente per creare un POV video.")

    token = _get_mapbox_token()
    if not token:
        raise RuntimeError("MAPBOX_API_KEY non configurata per il POV video.")

    # 1) normalizza e pulisce i punti
    clean_pts: List[Dict[str, float]] = []
    for p in points:
        try:
            lat = float(p.get("lat"))
            lon = float(p.get("lon"))
            elev = float(p.get("elev", 0.0))
        except Exception:
            continue
        clean_pts.append({"lat": lat, "lon": lon, "elev": elev})

    if len(clean_pts) < 4:
        raise ValueError("Traccia pista troppo corta dopo la pulizia.")

    main_seg = _pick_main_segment(clean_pts, max_jump_m=2000.0)
    if len(main_seg) < 4:
        raise ValueError("Segmento principale pista troppo corto per POV video.")

    # 2) resample per avere più frame (12 s @ 15 fps ≈ 180 frame)
    duration_s = 12
    fps = 15
    n_frames = duration_s * fps  # 180

    frames_pts = _resample_by_distance(main_seg, n_frames)

    # 3) path overlay per l'intera pista
    path_overlay = _build_path_overlay(main_seg)

    # 4) scarica frame con camera bassa e pitch alto
    frames: List[np.ndarray] = []

    # altezza "percepita": aggiustiamo slightly con zoom (16.8 ≈ 20–30 m)
    zoom = 16.8
    pitch = 60.0

    # import qui per non creare dipendenza globale di io se non serve
    import io  # noqa: E402

    for i in range(len(frames_pts)):
        p = frames_pts[i]
        lat = float(p["lat"])
        lon = float(p["lon"])

        # direzione lungo pista (usa punto successivo o precedente)
        if i < len(frames_pts) - 1:
            p2 = frames_pts[i + 1]
        else:
            p2 = frames_pts[i - 1]
        brg = _bearing_deg(lat, lon, float(p2["lat"]), float(p2["lon"]))

        try:
            img = _fetch_mapbox_frame(
                token=token,
                path_overlay=path_overlay,
                center_lat=lat,
                center_lon=lon,
                bearing=brg,
                zoom=zoom,
                pitch=pitch,
                size="800x450",
            )
            img = _apply_winter_filter(img)
        except Exception:
            # in caso di errore, ripeti l'ultimo frame valido oppure salta
            if frames:
                frames.append(frames[-1].copy())
                continue
            else:
                raise

        frames.append(np.array(img))

    if not frames:
        raise RuntimeError("Impossibile generare frame POV video.")

    # 5) output path
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(pista_name).lower()
    )
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_name}_pov_12s.mp4"

    # 6) crea video MP4
    clip = ImageSequenceClip(frames, fps=fps)
    clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio=False,
        verbose=False,
        logger=None,
    )

    return str(out_path)
