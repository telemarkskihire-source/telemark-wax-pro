# core/pov_video.py
# Generatore video POV 3D "realistico invernale" per piste da sci
#
# Uso previsto:
#   from core.pov_video import generate_pov_video
#   video_path = generate_pov_video(feature, pista_name)
#   st.video(video_path)
#
# NOTE:
# - Usa una vista "prima persona" semplificata, con neve, alberi e montagne innevate.
# - Non usa texture esterne: tutto è disegnato a mano con Pillow.
# - Risoluzione 1280x720, 30fps, 12 secondi (360 frame).

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import moviepy.editor as mpy

# ---------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------

# Video
FRAME_RATE = 30          # fps
VIDEO_DURATION = 12      # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION

# Risoluzione video (16:9)
WIDTH = 1280
HEIGHT = 720

# API elevazione (puoi sostituire con un tuo servizio DEM)
ELEVATION_API_URL = "https://api.open-elevation.com/api/v1/lookup"

# Directory di output per i video
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------
# UTILS GEOMETRIA & ELEVAZIONE
# ---------------------------------------------------------------------

def _haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Distanza in metri tra due punti (lat/lon in gradi).
    """
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _fetch_elevation(lat_lon_list: List[tuple]) -> List[float]:
    """
    Restituisce una lista di elevazioni per i punti dati (lat, lon).
    Usa una API DEM globale (qui open-elevation).
    """
    if not lat_lon_list:
        return []

    elevations: List[float] = []
    chunk_size = 80

    for i in range(0, len(lat_lon_list), chunk_size):
        chunk = lat_lon_list[i:i + chunk_size]
        locations = "|".join(f"{lat},{lon}" for lat, lon in chunk)
        try:
            r = requests.get(
                ELEVATION_API_URL,
                params={"locations": locations},
                timeout=10,
            )
            r.raise_for_status()
            j = r.json() or {}
            results = j.get("results", []) or []
            for item in results:
                elevations.append(float(item.get("elevation", 0.0)))
        except Exception:
            elevations.extend([0.0] * len(chunk))

    if len(elevations) < len(lat_lon_list):
        last = elevations[-1] if elevations else 0.0
        elevations.extend([last] * (len(lat_lon_list) - len(elevations)))

    return elevations[: len(lat_lon_list)]


def build_track_from_feature(feature: Dict[str, Any]) -> List[Dict[str, float]]:
    """
    Converte una Feature GeoJSON OSM (LineString) in una traccia
    con lat, lon, elev, dist (distanza cumulativa in m).

    feature: dict con geometry.type = "LineString",
             geometry.coordinates = [[lon, lat], ...]
    """
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []  # [lon, lat]

    if not coords:
        return []

    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]

    lat_lon_list = list(zip(lats, lons))
    elevs = _fetch_elevation(lat_lon_list)

    # distanza cumulativa
    dists = [0.0]
    for i in range(1, len(lats)):
        d = _haversine_dist(lats[i - 1], lons[i - 1], lats[i], lons[i])
        dists.append(dists[-1] + d)

    track = [
        {
            "lat": float(lats[i]),
            "lon": float(lons[i]),
            "elev": float(elevs[i]),
            "dist": float(dists[i]),
        }
        for i in range(len(lats))
    ]

    return track


def _resample_track(track: List[Dict[str, float]], n_points: int = 400) -> List[Dict[str, float]]:
    """
    Riduce / uniforma la traccia a n_points equispaziati in distanza.
    Serve per avere un POV fluido e costante.
    """
    if len(track) <= n_points:
        return track

    dists = np.array([p["dist"] for p in track])
    total = dists[-1]
    target = np.linspace(0, total, n_points)

    resampled: List[Dict[str, float]] = []
    for td in target:
        idx = np.searchsorted(dists, td)
        if idx == 0:
            resampled.append(track[0])
        elif idx >= len(dists):
            resampled.append(track[-1])
        else:
            # interpolazione lineare tra track[idx-1] e track[idx]
            p1 = track[idx - 1]
            p2 = track[idx]
            t = (td - dists[idx - 1]) / (dists[idx] - dists[idx - 1] + 1e-9)

            lat = p1["lat"] + (p2["lat"] - p1["lat"]) * t
            lon = p1["lon"] + (p2["lon"] - p1["lon"]) * t
            elev = p1["elev"] + (p2["elev"] - p1["elev"]) * t

            resampled.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "elev": float(elev),
                    "dist": float(td),
                }
            )

    return resampled


# ---------------------------------------------------------------------
# RENDERING POV "REALISTICO INVERNALE"
# ---------------------------------------------------------------------

def _draw_winter_background() -> Image.Image:
    """
    Crea un background invernale con cielo blu/azzurro e montagne innevate.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Cielo: gradiente dall'azzurro scuro in alto al chiaro verso l'orizzonte
    for y in range(int(HEIGHT * 0.55)):
        t = y / max(1, int(HEIGHT * 0.55) - 1)
        r = int(15 + 30 * t)
        g = int(60 + 80 * t)
        b = int(110 + 120 * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # Montagne lontane (grigio + bianco)
    horizon = int(HEIGHT * 0.45)
    m1 = [
        (-200, horizon + 80),
        (WIDTH * 0.2, horizon - 70),
        (WIDTH * 0.5, horizon + 40),
    ]
    m2 = [
        (WIDTH * 0.3, horizon + 60),
        (WIDTH * 0.7, horizon - 90),
        (WIDTH * 1.1, horizon + 50),
    ]
    draw.polygon(m1, fill=(190, 195, 205))
    draw.polygon(m2, fill=(200, 205, 215))

    # Nevicate sulle cime (bordi superiori più chiari)
    for poly in (m1, m2):
        ridge = []
        for i in range(1, len(poly) - 1):
            ridge.append(poly[i])
        for x, y in ridge:
            draw.ellipse([x - 6, y - 6, x + 6, y + 2], fill=(245, 250, 252))

    # Neve in primo piano (pendenza pista)
    snow_top = int(HEIGHT * 0.37)
    draw.rectangle([0, snow_top, WIDTH, HEIGHT], fill=(240, 244, 248))

    # Rumore molto leggero sulla neve per evitare "bianco piatto"
    noise = Image.effect_noise((WIDTH, HEIGHT - snow_top), 10)
    noise = noise.convert("L").point(lambda v: 220 + (v - 128) * 0.1)
    snow_layer = Image.merge("RGB", (noise, noise, noise))
    img.paste(snow_layer, (0, snow_top), snow_layer.convert("L").point(lambda v: 40))

    return img


def _draw_trees(draw: ImageDraw.ImageDraw, snow_top: int) -> None:
    """
    Disegna "macchie" di alberi ai lati pista.
    """
    tree_color = (32, 68, 58)
    for i in range(40):
        # lato sinistro
        x = np.random.uniform(0, WIDTH * 0.18)
        y = np.random.uniform(snow_top + 40, HEIGHT + 40)
        h = np.random.uniform(25, 55)
        draw.polygon(
            [
                (x, y - h),
                (x - h * 0.4, y),
                (x + h * 0.4, y),
            ],
            fill=tree_color,
        )

    for i in range(40):
        # lato destro
        x = np.random.uniform(WIDTH * 0.82, WIDTH)
        y = np.random.uniform(snow_top + 40, HEIGHT + 40)
        h = np.random.uniform(25, 55)
        draw.polygon(
            [
                (x, y - h),
                (x - h * 0.4, y),
                (x + h * 0.4, y),
            ],
            fill=tree_color,
        )


def _draw_pov_frame(track: List[Dict[str, float]], t_norm: float, pista_name: str) -> np.ndarray:
    """
    Crea un singolo frame POV stile "prima persona invernale":
    - neve in primo piano
    - pista centrale in prospettiva
    - alberi e montagne innevate
    - HUD con altitudine e distanza
    """
    base_img = _draw_winter_background()
    draw = ImageDraw.Draw(base_img)

    snow_top = int(HEIGHT * 0.37)

    # Aggiungo alberi ai lati
    _draw_trees(draw, snow_top)

    # Parametri prospettiva
    center_x = WIDTH // 2
    horizon_y = snow_top + 30
    bottom_y = HEIGHT + 80

    # Posizione lungo la traccia
    idx = int(t_norm * (len(track) - 1))
    idx = max(2, min(len(track) - 3, idx))

    # Valuto curvatura in base all'andamento orizzontale
    window = track[idx - 2: idx + 3]
    dlon = window[-1]["lon"] - window[0]["lon"]
    curvature = max(-1.0, min(1.0, dlon * 200))  # fattore grezzo per curva

    # Larghezze pista
    width_bottom = WIDTH * 0.7
    width_top = WIDTH * 0.06

    center_shift = curvature * (WIDTH * 0.18)

    cx_bottom = center_x + center_shift
    cx_top = center_x + center_shift * 0.4

    pista_poly = [
        (cx_bottom - width_bottom / 2, bottom_y),
        (cx_bottom + width_bottom / 2, bottom_y),
        (cx_top + width_top / 2, horizon_y),
        (cx_top - width_top / 2, horizon_y),
    ]

    # Ombreggio leggermente i bordi pista (neve smossa)
    draw.polygon(pista_poly, fill=(234, 240, 246))

    # Textura sulla pista con leggere strisce
    lane_color = (220, 228, 240)
    for i in range(18):
        f = i / 18.0
        x1 = cx_bottom - width_bottom * 0.45 * (1 - f)
        x2 = cx_bottom + width_bottom * 0.45 * (1 - f)
        y = bottom_y + (horizon_y - bottom_y) * f
        draw.line([(x1, y), (x2, y)], fill=lane_color, width=1)

    # Reti laterali rosse
    net_color = (215, 40, 40)
    steps = 12
    for side in (-1, 1):
        for i in range(steps):
            f = i / steps
            x1 = cx_bottom + side * (width_bottom / 2) * (1 - f)
            y1 = bottom_y - (bottom_y - horizon_y) * f
            x2 = x1 + side * 14
            y2 = y1 - 26
            draw.line([(x1, y1), (x2, y2)], fill=net_color, width=2)

    # Traccia centrale (linea gara)
    line_color = (170, 180, 210)
    for i in range(32):
        f = i / 32.0
        x = cx_bottom + (cx_top - cx_bottom) * f
        y = bottom_y + (horizon_y - bottom_y) * f
        r = max(1, int(5 - 3 * f))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=line_color)

    # Leggera sfocatura lontano per effetto profondità
    blur_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    bm_draw = ImageDraw.Draw(blur_mask)
    bm_draw.rectangle([0, 0, WIDTH, horizon_y + 10], fill=220)
    blurred = base_img.filter(ImageFilter.GaussianBlur(radius=2.0))
    base_img = Image.composite(blurred, base_img, blur_mask)

    # -----------------------------------------------------------------
    # HUD / TESTO
    # -----------------------------------------------------------------
    p = track[idx]
    alt = p["elev"]
    dist = p["dist"]
    total_dist = track[-1]["dist"]

    try:
        font_title = ImageFont.truetype("arial.ttf", 34)
        font_small = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()

    hud_h = 70
    hud = Image.new("RGBA", (WIDTH, hud_h), (0, 0, 0, 140))
    base_img.paste(hud, (0, 0), hud)

    draw = ImageDraw.Draw(base_img)
    draw.text(
        (24, 14),
        f"{pista_name} – POV",
        fill=(255, 255, 255),
        font=font_title,
    )

    info_text = f"Alt: {alt:.0f} m   Distanza: {dist/1000:.2f} km / {total_dist/1000:.2f} km"
    draw.text(
        (24, 44),
        info_text,
        fill=(220, 235, 255),
        font=font_small,
    )

    # Indicatore progressione a destra
    bar_w = 14
    bar_x = WIDTH - 50
    bar_y1 = 16
    bar_y2 = hud_h - 12
    draw.rectangle([bar_x, bar_y1, bar_x + bar_w, bar_y2], outline=(255, 255, 255), width=2)
    prog_y = bar_y2 - (bar_y2 - bar_y1) * t_norm
    draw.rectangle(
        [bar_x + 3, prog_y, bar_x + bar_w - 3, bar_y2 - 3],
        fill=(255, 80, 80),
    )

    return np.array(base_img)


# ---------------------------------------------------------------------
# GENERAZIONE VIDEO POV
# ---------------------------------------------------------------------

def generate_pov_video(feature: Dict[str, Any], pista_name: str) -> str:
    """
    Genera (o recupera da cache) un video POV per la pista data.
    feature: Feature OSM con geometry LineString.
    pista_name: nome leggibile pista (usato per filename).

    Ritorna: path del file MP4 generato.
    """
    # filename "pulito"
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(pista_name).lower()
    )
    out_path = VIDEO_DIR / f"{safe_name}_pov_12s.mp4"

    # Se esiste già, non rigeneriamo
    if out_path.exists():
        return str(out_path)

    # Costruisci traccia con elevazione
    track = build_track_from_feature(feature)
    if len(track) < 5:
        raise ValueError("Traccia insufficiente per POV (meno di 5 punti).")

    track = _resample_track(track, n_points=400)

    # Genera frames
    frames: List[np.ndarray] = []
    for i in range(N_FRAMES):
        t_norm = i / max(1, (N_FRAMES - 1))
        frame = _draw_pov_frame(track, t_norm, pista_name)
        frames.append(frame)

    # Crea clip video
    clip = mpy.ImageSequenceClip(frames, fps=FRAME_RATE)
    clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio=False,
        verbose=False,
        logger=None,
    )

    return str(out_path)
