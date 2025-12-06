# core/pov_video.py
# Video POV 3D realistico (satellite stile invernale) per piste da sci
#
# Uso previsto:
#   from core.pov_video import generate_pov_video
#   video_path = generate_pov_video(feature, pista_name)
#   st.video(video_path)
#
# - Prende una Feature GeoJSON (LineString) della pista
# - Costruisce una traccia con lat/lon/elev/distanza
# - Scarica UNA immagine satellitare grande da Mapbox
# - La "imbianca" per un look invernale
# - Disegna la pista sopra il satellite
# - Genera un video POV in cui la camera segue la pista dall'alto
#
# NOTE:
# - Richiede: moviepy, imageio[ffmpeg], requests, pillow, numpy
# - Richiede una MAPBOX_API_KEY in st.secrets o in variabile d'ambiente

from __future__ import annotations

from typing import List, Dict, Any, Optional
from pathlib import Path
import math
import os

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import streamlit as st

try:
    import moviepy.editor as mpy  # type: ignore[import]
except Exception:
    mpy = None  # type: ignore[assignment]

# ---------------------------------------------------------------------
# CONFIGURAZIONE GENERALE
# ---------------------------------------------------------------------

# Cartella di output per i video
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)

# Video
FRAME_RATE = 25          # fps (25 è un buon compromesso)
VIDEO_DURATION = 12      # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION

# Risoluzione video (16:9, compatibile con limiti Streamlit)
OUT_WIDTH = 1280
OUT_HEIGHT = 720

# Dimensione dell'immagine satellitare base (Mapbox Static max 1280)
MAPBOX_IMG_SIZE = 1280

# API elevazione (per completare la traccia con la quota)
ELEVATION_API_URL = "https://api.open-elevation.com/api/v1/lookup"


# ---------------------------------------------------------------------
# UTILS GEO
# ---------------------------------------------------------------------
def _haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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
    Usa una API DEM globale (open-elevation).
    """
    if not lat_lon_list:
        return []

    elevations: List[float] = []
    chunk_size = 80

    for i in range(0, len(lat_lon_list), chunk_size):
        chunk = lat_lon_list[i : i + chunk_size]
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

    dists = [0.0]
    for i in range(1, len(lats)):
        d = _haversine_dist(lats[i - 1], lons[i - 1], lats[i], lons[i])
        dists.append(dists[-1] + d)

    track: List[Dict[str, float]] = []
    for i in range(len(lats)):
        track.append(
            {
                "lat": lats[i],
                "lon": lons[i],
                "elev": elevs[i] if i < len(elevs) else 0.0,
                "dist": dists[i],
            }
        )

    return track


def _resample_track(track: List[Dict[str, float]], n_points: int = 400) -> List[Dict[str, float]]:
    """
    Riduce / uniforma la traccia a n_points equispaziati in distanza.
    Serve per avere un POV fluido e costante.
    """
    if len(track) <= n_points:
        return track

    dists = np.array([p["dist"] for p in track], dtype=float)
    total = float(dists[-1])
    target = np.linspace(0.0, total, n_points)

    resampled: List[Dict[str, float]] = []
    for td in target:
        idx = int(np.searchsorted(dists, td))
        if idx <= 0:
            resampled.append(track[0])
        elif idx >= len(dists):
            resampled.append(track[-1])
        else:
            p1 = track[idx - 1]
            p2 = track[idx]
            denom = float(dists[idx] - dists[idx - 1]) + 1e-9
            t = float(td - dists[idx - 1]) / denom

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
# MAPBOX & IMMAGINE SATELLITARE
# ---------------------------------------------------------------------
def _get_mapbox_token() -> Optional[str]:
    """
    Ritorna la Mapbox API key se configurata in:
      - st.secrets["MAPBOX_API_KEY"]
      - variabile d'ambiente MAPBOX_API_KEY
    Altrimenti None.
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


def _download_satellite_image(track: List[Dict[str, float]], token: Optional[str]) -> Image.Image:
    """
    Scarica una immagine satellitare quadrata da Mapbox che copre
    tutta la pista. Se il token non è disponibile o la richiesta fallisce,
    restituisce un semplice gradient di fallback.
    """
    if not token:
        return _fallback_background()

    if not track:
        return _fallback_background()

    # centro pista
    mean_lat = float(sum(p["lat"] for p in track) / len(track))
    mean_lon = float(sum(p["lon"] for p in track) / len(track))

    # Zoom fisso "sicuro": 14 copre tipicamente diverse km per 1280x1280
    zoom = 14
    bearing = 0   # top-down
    pitch = 0

    url = (
        "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{mean_lon},{mean_lat},{zoom},{bearing},{pitch}/"
        f"{MAPBOX_IMG_SIZE}x{MAPBOX_IMG_SIZE}"
        f"?access_token={token}"
    )

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        img = Image.open(r.raw).convert("RGB")
        return img
    except Exception:
        return _fallback_background()


def _fallback_background() -> Image.Image:
    """
    Sfondo di emergenza (niente Mapbox): un semplice gradiente azzurro/grigio
    che simula un paesaggio invernale visto dall'alto.
    """
    img = Image.new("RGB", (MAPBOX_IMG_SIZE, MAPBOX_IMG_SIZE), (190, 200, 210))
    draw = ImageDraw.Draw(img)
    for y in range(MAPBOX_IMG_SIZE):
        t = y / max(1, MAPBOX_IMG_SIZE - 1)
        col = int(220 - 40 * t)
        draw.line([(0, y), (MAPBOX_IMG_SIZE, y)], fill=(col, col, col))
    return img


def _winterize_image(img: Image.Image) -> Image.Image:
    """
    Applica un look "invernale" all'immagine:
      - leggero aumento luminosità
      - riduzione saturazione
      - overlay bianco-azzurro per simulare la neve
    """
    arr = np.asarray(img).astype(np.float32)

    # Schiarisco un po'
    arr = arr * 1.05 + 10.0

    # Leggero "snow tint"
    snow_tint = np.array([230.0, 236.0, 244.0], dtype=np.float32)
    alpha = 0.45
    arr = arr * (1.0 - alpha) + snow_tint * alpha

    # Clipping
    arr = np.clip(arr, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _track_to_pixels(
    track: List[Dict[str, float]],
    img_size: int,
    margin: int = 60,
) -> List[tuple[float, float]]:
    """
    Proietta lat/lon su coordinate pixel dell'immagine (approssimazione lineare
    valida per piccoli estensioni).
    """
    if not track:
        return []

    lats = [p["lat"] for p in track]
    lons = [p["lon"] for p in track]

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # evito divisioni per zero
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_span = max(max_lon - min_lon, 1e-6)

    usable = img_size - 2 * margin
    px_coords: List[tuple[float, float]] = []

    for p in track:
        x_norm = (p["lon"] - min_lon) / lon_span
        y_norm = (p["lat"] - min_lat) / lat_span

        x = margin + x_norm * usable
        # invertito perché y aumenta verso il basso
        y = img_size - (margin + y_norm * usable)

        px_coords.append((float(x), float(y)))

    return px_coords


def _draw_track_on_base(
    base: Image.Image,
    px_track: List[tuple[float, float]],
) -> Image.Image:
    """
    Disegna la pista sull'immagine base (linea chiara + bordo leggero).
    """
    img = base.copy()
    draw = ImageDraw.Draw(img)

    if len(px_track) >= 2:
        # bordo scuro
        draw.line(px_track, fill=(180, 40, 40), width=7)
        # centro più chiaro (neve battuta)
        draw.line(px_track, fill=(255, 120, 80), width=4)

    return img


# ---------------------------------------------------------------------
# GENERAZIONE FRAME POV
# ---------------------------------------------------------------------
def _make_frames_for_track(
    bg_with_track: Image.Image,
    px_track: List[tuple[float, float]],
) -> List[np.ndarray]:
    """
    Genera tutti i frame del video POV:
      - la camera segue il tracciato
      - viene ritagliata una finestra attorno al punto attuale
      - la finestra viene scalata alla risoluzione finale
    """
    frames: List[np.ndarray] = []

    if len(px_track) < 5:
        # fallback: frame statico
        frame = bg_with_track.resize((OUT_WIDTH, OUT_HEIGHT), Image.LANCZOS)
        frames = [np.asarray(frame)] * N_FRAMES
        return frames

    W, H = bg_with_track.size
    crop_w = int(W * 0.5)
    crop_h = int(H * 0.3)

    # evito crop troppo piccoli
    crop_w = max(crop_w, OUT_WIDTH // 2)
    crop_h = max(crop_h, OUT_HEIGHT // 2)

    # per l'HUD
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font = ImageFont.load_default()

    for i in range(N_FRAMES):
        t = i / max(1, N_FRAMES - 1)
        idx = int(t * (len(px_track) - 1))
        cx, cy = px_track[idx]

        left = int(cx - crop_w / 2)
        top = int(cy - crop_h / 2)

        # clamp ai bordi
        left = max(0, min(left, W - crop_w))
        top = max(0, min(top, H - crop_h))
        right = left + crop_w
        bottom = top + crop_h

        frame_img = bg_with_track.crop((left, top, right, bottom))
        frame_img = frame_img.resize((OUT_WIDTH, OUT_HEIGHT), Image.LANCZOS)

        # piccolo marker al centro (direzione di marcia)
        draw = ImageDraw.Draw(frame_img)
        cx_f = OUT_WIDTH // 2
        cy_f = int(OUT_HEIGHT * 0.6)
        r = 6
        draw.ellipse(
            [cx_f - r, cy_f - r, cx_f + r, cy_f + r],
            fill=(255, 140, 0),
            outline=(20, 20, 20),
            width=2,
        )

        # barra progresso semplice
        bar_margin = 40
        bar_y = OUT_HEIGHT - 30
        draw.line(
            [(bar_margin, bar_y), (OUT_WIDTH - bar_margin, bar_y)],
            fill=(240, 240, 240),
            width=3,
        )
        prog_x = bar_margin + t * (OUT_WIDTH - 2 * bar_margin)
        draw.line(
            [(bar_margin, bar_y), (prog_x, bar_y)],
            fill=(255, 120, 80),
            width=5,
        )

        frames.append(np.asarray(frame_img))

    return frames


# ---------------------------------------------------------------------
# FUNZIONE PUBBLICA: GENERAZIONE VIDEO POV
# ---------------------------------------------------------------------
def generate_pov_video(feature: Dict[str, Any], pista_name: str) -> str:
    """
    Genera (o recupera da cache) un video POV per la pista data.

    feature: Feature OSM con geometry LineString (lista [lon, lat])
    pista_name: nome leggibile pista (usato per filename)

    Ritorna: path del file MP4 generato (sempre in cartella "videos/").
    Lancia RuntimeError se moviepy non è disponibile.
    """
    # Controllo MoviePy
    if mpy is None:
        raise RuntimeError(
            "Modulo 'moviepy' non disponibile nell'ambiente. "
            "Installa 'moviepy' e 'imageio[ffmpeg]' per abilitare il video POV."
        )

    # filename "pulito"
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in pista_name.lower().strip() or "pista"
    )
    out_path = VIDEO_DIR / f"{safe_name}_pov_sat_12s.mp4"

    # Cache: se esiste già, lo riuso
    if out_path.exists():
        return str(out_path)

    # 1) Traccia dalla feature
    track = build_track_from_feature(feature)
    if len(track) < 5:
        raise ValueError("Traccia insufficiente per POV (meno di 5 punti).")

    track = _resample_track(track, n_points=400)

    # 2) Immagine satellitare
    token = _get_mapbox_token()
    sat_img = _download_satellite_image(track, token)
    winter_img = _winterize_image(sat_img)

    # 3) Coordinate pixel della pista
    px_track = _track_to_pixels(track, img_size=winter_img.size[0], margin=80)

    # 4) Disegno pista sulla base
    base_with_track = _draw_track_on_base(winter_img, px_track)

    # 5) Genero tutti i frame
    frames = _make_frames_for_track(base_with_track, px_track)

    # 6) Crea clip video
    clip = mpy.ImageSequenceClip(frames, fps=FRAME_RATE)
    clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio=False,
        verbose=False,
        logger=None,
    )

    return str(out_path)
