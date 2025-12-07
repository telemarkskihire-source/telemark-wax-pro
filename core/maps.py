# core/pov_video.py
# POV 3D “in stile sciatore” basato su Mapbox Static API
#
# - Input: traccia pista (GeoJSON LineString oppure lista di dict {lat, lon, ...})
# - Output: GIF 12 s salvata in ./videos/<nome_pista>_pov_12s.gif
#
# Nota:
#  - Usiamo solo la camera 3D (zoom + bearing + pitch), senza overlay path,
#    per evitare errori 422 dovuti a URL troppo lunghi.
#  - Pitch è tenuto <= 60° (limite Mapbox) → niente più 422.
#  - I frame sono distribuiti a velocità costante lungo la pista (in metri).

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

# Risoluzione video (consigliato <= 1280x1280 per Mapbox)
WIDTH = 1280
HEIGHT = 720

# Durata e fluidità
DURATION_S = 12.0
FPS = 20  # 20 fps → 240 frame ~ fluido ma non troppo pesante

# Camera “sciatore”
STYLE_ID = "mapbox/satellite-v9"
ZOOM = 16.3          # abbastanza vicino alla pista
PITCH = 55.0         # <= 60° (limite Mapbox), visuale con orizzonte
# Bearing dinamico, calcolato segmento per segmento

# Eventuale filtro “freddo neve” (per ora disattivato)
ENABLE_SNOW_FILTER = False


# -----------------------------------------------------
# Utility generali
# -----------------------------------------------------

def _get_mapbox_token() -> str:
    """Legge MAPBOX_API_KEY da st.secrets o ENV."""
    try:
        token = str(st.secrets.get("MAPBOX_API_KEY", "")).strip()
        if token:
            return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if not token:
        raise RuntimeError(
            "MAPBOX_API_KEY non configurata in st.secrets o come variabile d'ambiente."
        )
    return token


def _as_points(track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
    """Normalizza l'input in lista di dict {lat, lon}."""
    # Caso GeoJSON Feature LineString
    if isinstance(track, dict) and track.get("type") == "Feature":
        geom = track.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError("GeoJSON deve essere una LineString per il POV.")
        coords = geom.get("coordinates") or []
        pts: List[Dict[str, float]] = []
        for lon, lat in coords:
            pts.append({"lat": float(lat), "lon": float(lon)})
        return pts

    # Caso lista di punti generica
    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _haversine_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Distanza geodetica in metri tra due punti lat/lon."""
    R = 6371000.0
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * R * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da a → b."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _build_centers_and_bearings(
    points: List[Dict[str, float]],
    n_frames: int,
) -> List[Dict[str, float]]:
    """
    Costruisce n_frames posizioni camera lungo la pista a velocità costante.

    Usiamo la distanza metrica cumulata così ogni frame avanza
    la stessa distanza lungo la LineString (non il stesso indice).
    La bearing del frame k è data dal segmento locale (a→b).
    """
    if len(points) < 2:
        raise ValueError("Servono almeno 2 punti per calcolare un POV.")

    # Distanze cumulative lungo la traccia
    dists = [0.0]
    for i in range(1, len(points)):
        d = _haversine_m(points[i - 1], points[i])
        dists.append(dists[-1] + max(d, 0.01))  # evitiamo segmenti a 0

    total = dists[-1] or 1.0  # evitare divisioni per 0
    centers: List[Dict[str, float]] = []
    bearings: List[float] = []

    # Per ogni frame, distanza target lungo la pista
    for frame_idx in range(n_frames):
        t = frame_idx / max(1, n_frames - 1)
        target = t * total

        # Trova il segmento in cui cade "target"
        j = 0
        while j < len(dists) - 2 and dists[j + 1] < target:
            j += 1

        a = points[j]
        b = points[j + 1]
        seg_len = dists[j + 1] - dists[j]
        if seg_len <= 0:
            frac = 0.0
        else:
            frac = (target - dists[j]) / seg_len

        lat = a["lat"] + (b["lat"] - a["lat"]) * frac
        lon = a["lon"] + (b["lon"] - a["lon"]) * frac

        centers.append({"lat": lat, "lon": lon})
        bearings.append(_bearing(a, b))

    # Attacchiamo la bearing dentro ai dict per comodità
    for c, br in zip(centers, bearings):
        c["bearing"] = br

    return centers


def _fetch_frame(token: str, center: Dict[str, float]) -> Image.Image:
    """
    Scarica un singolo frame statico da Mapbox.

    Usiamo solo la camera (lon,lat,zoom,bearing,pitch) senza overlay path,
    per restare con URL corti e stabili.
    """
    lon = center["lon"]
    lat = center["lat"]
    bearing = center.get("bearing", 0.0)

    # Pitch clampato a 0–60° per rispettare i vincoli Mapbox
    pitch = max(0.0, min(PITCH, 60.0))

    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{lon:.5f},{lat:.5f},{ZOOM:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )

    r = requests.get(url, timeout=25)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    return img


def _apply_snow_filter(img: Image.Image) -> Image.Image:
    """
    Hook per un eventuale filtro “freddo/neve”.
    Per ora è disattivato (ENABLE_SNOW_FILTER=False) per non sbiadire la pista.
    """
    if not ENABLE_SNOW_FILTER:
        return img

    arr = np.asarray(img).astype("float32") / 255.0

    # Tono leggermente più freddo + un filo di contrasto
    arr = (arr - 0.5) * 1.05 + 0.5
    arr[..., 0] *= 0.98  # meno rosso
    arr[..., 2] *= 1.03  # un po' più blu
    arr = np.clip(arr, 0.0, 1.0)

    arr = (arr * 255.0).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


# -----------------------------------------------------
# Funzione principale
# -----------------------------------------------------

def generate_pov_video(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]],
    pista_name: str,
    duration_s: float = DURATION_S,
    fps: int = FPS,
) -> str:
    """
    Genera una GIF POV 3D di ~duration_s secondi.

    Parametri:
        track      - GeoJSON LineString oppure lista di dict {lat, lon, ...}
        pista_name - nome usato per il file su disco
        duration_s - durata desiderata (default 12 s)
        fps        - frame per secondo (default 20)

    Ritorna:
        percorso assoluto del file GIF generato in ./videos/<nome>_pov_12s.gif
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    n_frames = int(max(1, duration_s * fps))

    centers = _build_centers_and_bearings(points, n_frames)

    frames: List[np.ndarray] = []
    for c in centers:
        img = _fetch_frame(token, c)
        img = _apply_snow_filter(img)
        frames.append(np.asarray(img))

    # Salvataggio GIF
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.gif"

    imageio.mimsave(str(out_path), frames, fps=fps)

    return str(out_path)
