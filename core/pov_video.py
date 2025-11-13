# core/pov_video.py
# Generatore video POV 3D "stilizzato" per piste da sci
#
# Uso previsto:
#   from core.pov_video import generate_pov_video
#   video_path = generate_pov_video(feature, pista_name)
#   st.video(video_path)

import math
import os
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mpy

# ---------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------

# Video
FRAME_RATE = 30          # fps
VIDEO_DURATION = 12      # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION

# Risoluzione video (16:9)
WIDTH = 1920
HEIGHT = 1080

# API elevazione (puoi sostituire con un tuo servizio DEM)
ELEVATION_API_URL = "https://api.open-elevation.com/api/v1/lookup"

# Directory di output per i video
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------
# UTILS GEOMETRIA & ELEVAZIONE
# ---------------------------------------------------------------------

def _haversine_dist(lat1, lon1, lat2, lon2):
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


def _fetch_elevation(lat_lon_list):
    """
    Restituisce una lista di elevazioni per i punti dati (lat, lon).
    Usa una API DEM globale (qui open-elevation).
    """
    if not lat_lon_list:
        return []

    elevations = []
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
        # padding in caso di errore
        last = elevations[-1] if elevations else 0.0
        elevations.extend([last] * (len(lat_lon_list) - len(elevations)))

    return elevations[: len(lat_lon_list)]


def build_track_from_feature(feature):
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


def _resample_track(track, n_points=300):
    """
    Riduce / uniforma la traccia a n_points equispaziati in distanza.
    Serve per avere un POV fluido e costante.
    """
    if len(track) <= n_points:
        return track

    dists = np.array([p["dist"] for p in track])
    total = dists[-1]
    target = np.linspace(0, total, n_points)

    resampled = []
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
                    "lat": lat,
                    "lon": lon,
                    "elev": elev,
                    "dist": td,
                }
            )

    return resampled


# ---------------------------------------------------------------------
# RENDERING POV 2.5D (STILE FIS)
# ---------------------------------------------------------------------

def _draw_pov_frame(track, t_norm, pista_name):
    """
    Crea un singolo frame POV stile FIS:
    - neve in primo piano
    - pista centrale in prospettiva
    - montagne + cielo
    - HUD con altitudine e distanza
    """
    # Setup immagine
    img = Image.new("RGB", (WIDTH, HEIGHT), (180, 210, 240))
    draw = ImageDraw.Draw(img)

    # Fondo cielo
    sky_h = int(HEIGHT * 0.45)
    draw.rectangle([0, 0, WIDTH, sky_h], fill=(135, 176, 220))

    # Montagne stilizzate (sfondo)
    mid_y = sky_h + 80
    for offset, color in [(-200, (190, 210, 230)), (150, (170, 190, 210))]:
        draw.polygon(
            [
                (0 + offset, mid_y),
                (WIDTH * 0.3 + offset, sky_h - 80),
                (WIDTH * 0.6 + offset, mid_y),
            ],
            fill=color,
        )

    # Neve/pendenza (primo piano)
    snow_top = int(HEIGHT * 0.35)
    draw.rectangle([0, snow_top, WIDTH, HEIGHT], fill=(240, 245, 250))

    # Parametri prospettiva
    center_x = WIDTH // 2
    horizon_y = snow_top + 40
    bottom_y = HEIGHT + 40

    # "Curva" della pista in base alla curva reale (lat/lon)
    # Per semplicità prendiamo finestra di qualche punto attorno alla posizione
    idx = int(t_norm * (len(track) - 1))
    idx = max(2, min(len(track) - 3, idx))

    # direzioni per simulare curvatura
    # uso differenze lon/lat per avere tendenza dx/sx
    pre = track[idx - 2: idx + 3]
    dlon = pre[-1]["lon"] - pre[0]["lon"]
    curvature = max(-1.0, min(1.0, dlon * 200))  # fattore grezzo per curva

    # larghezze pista in basso e in alto
    width_bottom = WIDTH * 0.7
    width_top = WIDTH * 0.05

    # centro pista spostato lateralmente leggermente in base alla curva
    center_shift = curvature * (WIDTH * 0.12)

    cx_bottom = center_x + center_shift
    cx_top = center_x + center_shift * 0.4

    # Poligono pista (trapezio prospettico)
    pista_poly = [
        (cx_bottom - width_bottom / 2, bottom_y),
        (cx_bottom + width_bottom / 2, bottom_y),
        (cx_top + width_top / 2, horizon_y),
        (cx_top - width_top / 2, horizon_y),
    ]

    # Ombra ai bordi pista
    draw.polygon(pista_poly, fill=(225, 235, 245))

    # Reti laterali (linee rosse)
    net_color = (220, 40, 40)
    steps = 12
    for side in (-1, 1):
        for i in range(steps):
            f = i / steps
            x1 = cx_bottom + side * (width_bottom / 2) * (1 - f)
            y1 = bottom_y - (bottom_y - horizon_y) * f
            x2 = x1 + side * 20
            y2 = y1 - 30
            draw.line([(x1, y1), (x2, y2)], fill=net_color, width=2)

    # Linea centrale leggermente più scura (traccia gara)
    line_color = (160, 180, 200)
    for i in range(30):
        f = i / 30.0
        x = cx_bottom + (cx_top - cx_bottom) * f
        y = bottom_y + (horizon_y - bottom_y) * f
        r = max(1, int(6 - 4 * f))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=line_color)

    # -----------------------------------------------------------------
    # HUD / TESTO
    # -----------------------------------------------------------------
    # Info altitudine, dist ecc.
    p = track[idx]
    alt = p["elev"]
    dist = p["dist"]
    total_dist = track[-1]["dist"]

    # Carica font di default (se vuoi puoi usare un TTF)
    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Barra semi-trasparente in alto
    hud_h = 80
    hud_color = (0, 0, 0, 130)
    hud = Image.new("RGBA", (WIDTH, hud_h), hud_color)
    img.paste(hud, (0, 0), hud)

    # Testi
    draw = ImageDraw.Draw(img)
    draw.text(
        (30, 20),
        f"{pista_name} – POV",
        fill=(255, 255, 255),
        font=font_title,
    )

    info_text = f"Alt: {alt:.0f} m   Distanza: {dist/1000:.2f} km / {total_dist/1000:.2f} km"
    draw.text(
        (30, 50),
        info_text,
        fill=(255, 255, 255),
        font=font_small,
    )

    # Piccolo indicatore progresso a destra
    bar_w = 16
    bar_x = WIDTH - 60
    bar_y1 = 20
    bar_y2 = hud_h - 20
    draw.rectangle([bar_x, bar_y1, bar_x + bar_w, bar_y2], outline=(255, 255, 255), width=2)
    prog_y = bar_y2 - (bar_y2 - bar_y1) * t_norm
    draw.rectangle(
        [bar_x + 3, prog_y, bar_x + bar_w - 3, bar_y2 - 3],
        fill=(255, 80, 80),
    )

    return np.array(img)


# ---------------------------------------------------------------------
# GENERAZIONE VIDEO POV
# ---------------------------------------------------------------------

def generate_pov_video(feature, pista_name: str) -> str:
    """
    Genera (o recupera da cache) un video POV per la pista data.
    feature: Feature OSM con geometry LineString.
    pista_name: nome leggibile pista (usato per filename).

    Ritorna: path del file MP4 generato.
    """
    # filename "pulito"
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in pista_name.lower())
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
    frames = []
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
