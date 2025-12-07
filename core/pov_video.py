# core/pov_video.py
# POV 3D piste Telemark – versione STABILE & OTTIMIZZATA
#
# - Camera “tipo sciatore” (pitch alto ma entro il limite 0–60 di Mapbox)
# - Movimento fluido lungo la pista
# - Limitazione punti per evitare 422 (URL troppo lungo)
# - Output principale: MP4 (fallback GIF se MP4 fallisce)

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union
import io
import math
import os
from pathlib import Path

import numpy as np
import requests
from PIL import Image
import imageio
import streamlit as st


# -----------------------------------------------------
# Config POV
# -----------------------------------------------------

# Risoluzione “16:9” HD
WIDTH = 1280
HEIGHT = 720

# Durata e fluidità
DURATION_S = 12.0
FPS = 24  # cinematico ma fluido

# Stile base: satellite 3D Mapbox
STYLE_ID = "mapbox/satellite-v9"

# Linea pista (sovrapposta sulla mappa)
LINE_COLOR = "ff4422"   # arancio/rosso ben visibile
LINE_WIDTH = 4          # spessore in px per il path
LINE_OPACITY = 0.9      # 0–1

# Pitch massimo consentito dalla Static API (vedi errore "Pitch must be between 0-60.")
CAMERA_PITCH = 58.0     # alto, ma entro il limite 60º
CAMERA_ZOOM = 16.3      # zoom abbastanza vicino alla pista

# Limite punti per il path (evita URL troppo lunghi → 422)
MAX_PATH_POINTS = 80

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# -----------------------------------------------------
# Utility
# -----------------------------------------------------

def _get_mapbox_token() -> str:
    """Legge la MAPBOX_API_KEY da st.secrets o ENV."""
    try:
        token = str(st.secrets.get("MAPBOX_API_KEY", "")).strip()
        if token:
            return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if not token:
        raise RuntimeError(
            "MAPBOX_API_KEY non configurata (né in st.secrets né in variabili d'ambiente)."
        )
    return token


def _as_points(track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
    """
    Normalizza la traccia in lista di dict {"lat": ..., "lon": ...}.

    Supporta:
    - GeoJSON Feature LineString
    - Lista di dict {lat, lon, ...}
    """
    # GeoJSON Feature
    if isinstance(track, dict) and track.get("type") == "Feature":
        geom = track.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError("GeoJSON non è una LineString.")
        coords = geom.get("coordinates") or []
        pts: List[Dict[str, float]] = []
        for lon, lat in coords:
            pts.append({"lat": float(lat), "lon": float(lon)})
        return pts

    # Lista di punti generici
    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _resample(points: List[Dict[str, float]], max_points: int) -> List[Dict[str, float]]:
    """
    Limita il numero di punti per il path Static API.

    Mantiene il primo e l’ultimo punto e prende un punto ogni N.
    """
    n = len(points)
    if n <= max_points:
        return points

    step = max(1, n // max_points)
    out: List[Dict[str, float]] = []
    for i in range(0, n, step):
        out.append(points[i])
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da punto a → b (gradi)."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _build_path_param(points: List[Dict[str, float]]) -> str:
    """
    Costruisce il parametro path-... per la Static API.
    Esempio:
      path-4+ff4422-0.9(lon1,lat1;lon2,lat2;...)
    """
    pts = _resample(points, max_points=MAX_PATH_POINTS)
    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)

    # NOTA: opacity nella sintassi path è sempre 0–1; usiamo LINE_OPACITY.
    return f"path-{LINE_WIDTH}+{LINE_COLOR}-{LINE_OPACITY}({coord_str})"


def _fetch_frame(
    token: str,
    center: Dict[str, float],
    bearing: float,
    path_param: str,
    zoom: float = CAMERA_ZOOM,
    pitch: float = CAMERA_PITCH,
) -> Image.Image:
    """
    Scarica un singolo frame statico da Mapbox.

    Usa stile satellite, path pista, zoom e pitch per effetto 3D.
    Pitch è clampato tra 0 e 60 per rispettare i vincoli Mapbox.
    """
    # clamp per sicurezza
    pitch = max(0.0, min(60.0, pitch))

    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{center['lon']:.5f},{center['lat']:.5f},{zoom:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )

    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    return img


def _apply_color_tweak(img: Image.Image) -> Image.Image:
    """
    Piccolissima correzione colore (leggero tono freddo/contrasto),
    SENZA lavare l’immagine. Può essere disattivata se non serve.
    """
    # Se non vuoi alcuna modifica, basta restituire direttamente img.
    # return img

    arr = np.asarray(img).astype("float32") / 255.0

    # Micro contrasto
    arr = (arr - 0.5) * 1.03 + 0.5

    # Leggero raffreddamento (quasi impercettibile)
    arr[..., 0] *= 0.99  # rosso
    arr[..., 2] *= 1.01  # blu

    arr = np.clip(arr, 0.0, 1.0)
    arr = (arr * 255.0).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


def _safe_filename(name: str) -> str:
    """Normalizza il nome pista per usarlo come filename."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.lower())
    return safe or "pista"


# -----------------------------------------------------
# Funzione principale usata da streamlit_app
# -----------------------------------------------------

def generate_pov_video(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]],
    pista_name: str,
    duration_s: float = DURATION_S,
    fps: int = FPS,
) -> str:
    """
    Genera un video POV 3D ~duration_s secondi in MP4 (fallback GIF).

    track:
      - GeoJSON Feature LineString
      - oppure lista di punti {lat, lon, ...}

    Ritorna:
      path del file video generato (MP4 o GIF) nella cartella ./videos/
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    # Path completo (disegnato su tutti i frame)
    path_param = _build_path_param(points)

    # Timeline frame: ci muoviamo lungo la pista
    n_frames = max(8, int(duration_s * fps))
    # Campioniamo tra il primo e il penultimo punto (segmenti a → b)
    idx_float = np.linspace(0, len(points) - 2, n_frames)

    centers: List[Dict[str, float]] = []
    bearings: List[float] = []

    for t in idx_float:
        i = int(math.floor(t))
        frac = float(t - i)

        a = points[i]
        b = points[i + 1]

        lat = a["lat"] + (b["lat"] - a["lat"]) * frac
        lon = a["lon"] + (b["lon"] - a["lon"]) * frac

        centers.append({"lat": lat, "lon": lon})
        bearings.append(_bearing(a, b))

    # Scarico tutti i frame
    frames: List[np.ndarray] = []

    for c, brng in zip(centers, bearings):
        img = _fetch_frame(token, c, brng, path_param)
        img = _apply_color_tweak(img)
        frames.append(np.asarray(img))

    # Directory output
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = _safe_filename(pista_name)
    mp4_path = out_dir / f"{base_name}_pov_{int(duration_s)}s.mp4"
    gif_path = out_dir / f"{base_name}_pov_{int(duration_s)}s.gif"

    # -------------------------------------------------
    # Tentativo 1: MP4 (codec H.264)
    # -------------------------------------------------
    try:
        writer = imageio.get_writer(
            mp4_path,
            fps=fps,
            codec="libx264",
            quality=8,
        )
        for frame in frames:
            writer.append_data(frame)
        writer.close()
        return str(mp4_path)
    except Exception as e:
        # Se qualcosa va storto (es. ffmpeg non disponibile),
        # facciamo fallback a GIF così l'utente ha comunque un risultato.
        st.warning(f"Impossibile scrivere MP4 ({e}); fallback a GIF.")

    # -------------------------------------------------
    # Fallback: GIF
    # -------------------------------------------------
    imageio.mimsave(str(gif_path), frames, fps=fps)
    return str(gif_path)
