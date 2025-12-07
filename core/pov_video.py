# core/pov_video.py
# Generatore GIF POV 3D "stilizzata invernale" per piste da sci
#
# Uso previsto:
#   from core.pov_video import generate_pov_video
#   gif_path = generate_pov_video(feature, pista_name)
#   st.image(gif_path)

from __future__ import annotations

from typing import Dict, Any, List
import math
import os
from pathlib import Path
import random

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------

# GIF
FRAME_RATE = 30          # fps
VIDEO_DURATION = 12      # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION

# Risoluzione (16:9)
WIDTH = 1280
HEIGHT = 720

# API elevazione (puoi sostituire con un tuo servizio DEM)
ELEVATION_API_URL = "https://api.open-elevation.com/api/v1/lookup"

# Directory di output per i POV
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------
# UTILS GEOMETRIA & ELEVAZIONE
# ---------------------------------------------------------------------

def _haversine_dist(lat1, lon1, lat2, lon2) -> float:
    """Distanza in metri tra due punti (lat/lon in gradi)."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _fetch_elevation(lat_lon_list: List[tuple[float, float]]) -> List[float]:
    """
    Restituisce una lista di elevazioni per i punti dati (lat, lon).
    Usa una API DEM globale (qui open-elevation).
    Se l'API fallisce, torna una lista di zeri.
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

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]

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


def _resample_track(track: List[Dict[str, float]], n_points: int = 350) -> List[Dict[str, float]]:
    """
    Riduce / uniforma la traccia a n_points equispaziati in distanza.
    Serve per avere un POV fluido e costante.
    """
    if len(track) <= n_points:
        return track

    dists = np.array([p["dist"] for p in track], dtype=float)
    total = float(dists[-1])
    if total <= 0:
        return track

    target = np.linspace(0.0, total, n_points)

    resampled: List[Dict[str, float]] = []
    for td in target:
        idx = int(np.searchsorted(dists, td))
        if idx <= 0:
            resampled.append(track[0])
        elif idx >= len(dists):
            resampled.append(track[-1])
        else:
            # interpolazione lineare tra track[idx-1] e track[idx]
            p1 = track[idx - 1]
            p2 = track[idx]
            den = float(dists[idx] - dists[idx - 1]) or 1e-9
            t = float((td - dists[idx - 1]) / den)

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
# RENDERING POV 2.5D (INVERNALE, PRIMA PERSONA)
# ---------------------------------------------------------------------

def _draw_pov_frame(track: List[Dict[str, float]], t_norm: float, pista_name: str) -> Image.Image:
    """
    Crea un singolo frame POV stile FIS / volo d'uccello:
    - paesaggio invernale (neve, montagne, boschi scuri)
    - pista centrale in prospettiva
    - leggera oscillazione camera
    - HUD con altitudine, distanza e barra progresso
    """
    # Setup immagine base
    img = Image.new("RGB", (WIDTH, HEIGHT), (12, 20, 35))
    draw = ImageDraw.Draw(img)

    # ---------------- SFONDO INVERNALE ----------------
    sky_h = int(HEIGHT * 0.45)

    # gradiente cielo blu freddo
    for y in range(sky_h):
        f = y / max(1, sky_h - 1)
        r = int(10 + 20 * f)
        g = int(40 + 40 * f)
        b = int(80 + 60 * f)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # montagne innevate (due layer per profondità)
    mid_y = sky_h + 40
    mountains = [
        (-240, (190, 200, 210)),
        (80, (170, 180, 190)),
    ]
    for offset, color in mountains:
        draw.polygon(
            [
                (0 + offset, mid_y + 40),
                (WIDTH * 0.25 + offset, sky_h - 50),
                (WIDTH * 0.55 + offset, mid_y),
                (WIDTH * 0.9 + offset, sky_h + 10),
            ],
            fill=color,
        )

    # neve/pendenza (primo piano)
    snow_top = int(HEIGHT * 0.38)
    draw.rectangle([0, snow_top, WIDTH, HEIGHT], fill=(235, 242, 250))

    # accenno di bosco ai bordi
    forest_color = (40, 60, 55)
    for i in range(40):
        x = int((i / 40.0) * WIDTH)
        h = random.randint(20, 60)
        draw.rectangle(
            [x, snow_top - h, x + 12, snow_top],
            fill=forest_color,
        )

    # ---------------- PROSPETTIVA PISTA ----------------
    center_x = WIDTH // 2
    horizon_y = snow_top + 20
    bottom_y = HEIGHT + 40

    # posizione lungo traccia
    idx = int(t_norm * (len(track) - 1))
    idx = max(2, min(len(track) - 3, idx))

    # curvatura basata sui lon/lat reali
    window = track[idx - 2: idx + 3]
    dlon = window[-1]["lon"] - window[0]["lon"]
    curvature = max(-1.0, min(1.0, dlon * 200))  # fattore grezzo per curva

    # leggera oscillazione camera (roll) per dare feeling "volo"
    roll = math.sin(t_norm * 2 * math.pi * 1.2) * 0.08  # ±0.08 rad
    cam_shift = math.sin(t_norm * 2 * math.pi * 0.7) * (WIDTH * 0.04)

    # larghezze pista
    width_bottom = WIDTH * 0.75
    width_top = WIDTH * 0.10

    center_shift = curvature * (WIDTH * 0.18) + cam_shift

    cx_bottom = center_x + center_shift
    cx_top = center_x + center_shift * 0.4

    # applico "roll" sulla pista (leggera rotazione attorno al centro)
    def rot(x, y, cx, cy, angle):
        dx = x - cx
        dy = y - cy
        ca = math.cos(angle)
        sa = math.sin(angle)
        rx = cx + dx * ca - dy * sa
        ry = cy + dx * sa + dy * ca
        return rx, ry

    p1 = (cx_bottom - width_bottom / 2, bottom_y)
    p2 = (cx_bottom + width_bottom / 2, bottom_y)
    p3 = (cx_top + width_top / 2, horizon_y)
    p4 = (cx_top - width_top / 2, horizon_y)

    cx_cam = center_x
    cy_cam = (snow_top + HEIGHT) / 2

    pista_poly = [
        rot(*p1, cx_cam, cy_cam, roll),
        rot(*p2, cx_cam, cy_cam, roll),
        rot(*p3, cx_cam, cy_cam, roll),
        rot(*p4, cx_cam, cy_cam, roll),
    ]

    # neve pista leggermente azzurra
    draw.polygon(pista_poly, fill=(230, 238, 250))

    # bordi pista più compatti
    edge_color = (210, 222, 240)
    draw.line([pista_poly[0], pista_poly[3]], fill=edge_color, width=4)
    draw.line([pista_poly[1], pista_poly[2]], fill=edge_color, width=4)

    # reti laterali (linee rosse)
    net_color = (220, 50, 60)
    steps = 13
    for side_sign in (-1, 1):
        for i in range(steps):
            f = i / steps
            x = cx_bottom + side_sign * (width_bottom / 2) * (1 - f * 0.9)
            y = bottom_y - (bottom_y - horizon_y) * f
            x2, y2 = rot(
                x + side_sign * 18,
                y - 38,
                cx_cam,
                cy_cam,
                roll,
            )
            draw.line(
                [rot(x, y, cx_cam, cy_cam, roll), (x2, y2)],
                fill=net_color,
                width=2,
            )

    # linea centrale (traccia gara)
    line_color = (180, 50, 50)
    for i in range(32):
        f = i / 32.0
        x = cx_bottom + (cx_top - cx_bottom) * f
        y = bottom_y + (horizon_y - bottom_y) * f
        x, y = rot(x, y, cx_cam, cy_cam, roll)
        r = max(1, int(6 - 4 * f))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=line_color)

    # leggero "snow spray" vicino al bordo in basso
    rng = random.Random(int(t_norm * 1000))
    for _ in range(40):
        sx = cx_bottom + rng.uniform(-width_bottom * 0.35, width_bottom * 0.35)
        sy = HEIGHT + rng.uniform(-40, 10)
        r = rng.uniform(1, 3)
        draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(245, 250, 255))

    # -----------------------------------------------------------------
    # HUD / TESTO
    # -----------------------------------------------------------------
    p = track[idx]
    alt = p["elev"]
    dist = p["dist"]
    total_dist = track[-1]["dist"]

    # Font
    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Barra semi-trasparente in alto
    hud_h = 80
    hud = Image.new("RGBA", (WIDTH, hud_h), (0, 0, 0, 150))
    img.paste(hud, (0, 0), hud)

    draw = ImageDraw.Draw(img)
    draw.text(
        (30, 18),
        f"{pista_name} – POV",
        fill=(255, 255, 255),
        font=font_title,
    )

    info_text = (
        f"Alt: {alt:.0f} m   Distanza: {dist/1000:.2f} / {total_dist/1000:.2f} km"
    )
    draw.text(
        (30, 52),
        info_text,
        fill=(230, 240, 255),
        font=font_small,
    )

    # Piccolo indicatore progresso a destra
    bar_w = 16
    bar_x = WIDTH - 60
    bar_y1 = 18
    bar_y2 = hud_h - 18
    if bar_y2 < bar_y1:
        bar_y2 = bar_y1  # sicurezza

    draw.rectangle([bar_x, bar_y1, bar_x + bar_w, bar_y2], outline=(255, 255, 255), width=2)
    prog_y = bar_y2 - (bar_y2 - bar_y1) * max(0.0, min(1.0, t_norm))
    # garantisco y1 <= y2
    fill_y1 = min(prog_y, bar_y2 - 3)
    draw.rectangle(
        [bar_x + 3, fill_y1, bar_x + bar_w - 3, bar_y2 - 3],
        fill=(255, 90, 90),
    )

    return img


# ---------------------------------------------------------------------
# GENERAZIONE GIF POV
# ---------------------------------------------------------------------

def generate_pov_video(feature: Dict[str, Any], pista_name: str) -> str:
    """
    Genera (o recupera da cache) una GIF POV per la pista data.
    feature: Feature OSM con geometry LineString.
    pista_name: nome leggibile pista (usato per filename).

    Ritorna: path del file GIF generato.
    """
    # filename "pulito"
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in pista_name.lower())
    out_path = VIDEO_DIR / f"{safe_name}_pov_12s.gif"

    # Se esiste già, non rigeneriamo
    if out_path.exists():
        return str(out_path)

    # Costruisci traccia con elevazione
    track = build_track_from_feature(feature)
    if len(track) < 5:
        raise ValueError("Traccia insufficiente per POV (meno di 5 punti).")

    track = _resample_track(track, n_points=380)

    # Genera frames (PIL Images)
    frames: List[Image.Image] = []
    for i in range(N_FRAMES):
        t_norm = i / max(1, N_FRAMES - 1)
        frame_img = _draw_pov_frame(track, t_norm, pista_name)
        frames.append(frame_img.convert("P", palette=Image.ADAPTIVE))

    # Salva come GIF animata
    duration_ms = int(1000 / FRAME_RATE)  # durata per frame
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )

    return str(out_path)
