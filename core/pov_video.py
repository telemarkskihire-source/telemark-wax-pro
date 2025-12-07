# core/pov_video.py
# POV VIDEO 3D con Mapbox Static API -> GIF animata
#
# - Nessuna dipendenza da moviepy (usa solo requests + Pillow + imageio).
# - Prende i punti pista (ctx["pov_piste_points"] o GeoJSON Feature) e
#   genera una GIF di ~12s in stile "volo d'uccello" sulla pista.
# - Camera bassa (zoom alto + pitch 60°) e movimento più fluido
#   grazie a frame più numerosi e time-easing.
#
# Output: videos/<nome_pista>_pov_12s.gif
#
# Uso:
#   from core import pov_video as pov_video_mod
#   path = pov_video_mod.generate_pov_video(points_or_feature, "Del Bosco")

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union, Optional
import math
import io

import requests
import numpy as np
from PIL import Image
import imageio.v2 as imageio  # v2 API compatibile
import streamlit as st  # solo per leggere st.secrets


# ------------------------------------------------------------
# CONFIGURAZIONE BASE
# ------------------------------------------------------------
UA = {"User-Agent": "telemark-wax-pro/2.0"}

# Durata target del POV
TOTAL_SECONDS = 12.0
# Numero frame (più alto = più fluido)
TOTAL_FRAMES = 120  # circa 10 fps su 12 s

# Dimensioni GIF
FRAME_WIDTH = 800
FRAME_HEIGHT = 450

# Parametri camera (visuale bassa + effetto 3D)
CAMERA_ZOOM = 16.0   # zoom alto -> vicino al terreno
CAMERA_PITCH = 60.0  # massimo consentito da Mapbox Static (più "prima persona")
ROLL_AMPLITUDE_DEG = 3.0  # piccolo roll sinusoidale per effetto cinema (simulato via bearing)


# ------------------------------------------------------------
# MAPBOX TOKEN
# ------------------------------------------------------------
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

    import os

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    return token or None


# ------------------------------------------------------------
# UTILS GEO
# ------------------------------------------------------------
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
    """Bearing (gradi) da punto 1 a punto 2 (0 = nord, 90 = est)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlambda
    )
    b = math.degrees(math.atan2(x, y))
    return (b + 360.0) % 360.0


def _pick_main_segment(
    points: List[Dict[str, float]], max_jump_m: float = 2000.0
) -> List[Dict[str, float]]:
    """
    Dato un elenco di punti [{lat, lon, elev}, ...] prende il segmento continuo
    più lungo, dove la distanza fra due punti consecutivi non supera max_jump_m.

    Serve per eliminare salti assurdi (tipo Italia → Francia).
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

    best = max(segments, key=seg_length)
    return best


# ------------------------------------------------------------
# NORMALIZZAZIONE INPUT
# ------------------------------------------------------------
PointSeq = Sequence[Dict[str, float]]
GeoJSONFeature = Dict[str, Any]


def _normalize_input(
    data: Union[PointSeq, GeoJSONFeature]
) -> List[Dict[str, float]]:
    """
    Accetta:
    - lista di dict con chiavi "lat", "lon" (e opz. "elev")
    - Feature GeoJSON {"type": "Feature", "geometry": {"type": "LineString", ...}}
    Restituisce lista di dict {"lat": float, "lon": float, "elev": float}.
    """
    points: List[Dict[str, float]] = []

    # Caso GeoJSON Feature
    if isinstance(data, dict) and data.get("type") == "Feature":
        geom = data.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates") or []
            for c in coords:
                try:
                    lon = float(c[0])
                    lat = float(c[1])
                except Exception:
                    continue
                elev = float(c[2]) if len(c) > 2 else 0.0
                points.append({"lat": lat, "lon": lon, "elev": elev})
        return points

    # Caso lista di punti "nostri"
    for p in data:  # type: ignore[assignment]
        try:
            lat = float(p.get("lat"))  # type: ignore[arg-type]
            lon = float(p.get("lon"))  # type: ignore[arg-type]
            elev = float(p.get("elev", 0.0))  # type: ignore[arg-type]
        except Exception:
            continue
        points.append({"lat": lat, "lon": lon, "elev": elev})

    return points


# ------------------------------------------------------------
# PATH OVERLAY PER MAPBOX (RIDOTTO!)
# ------------------------------------------------------------
def _build_path_overlay(points: List[Dict[str, float]]) -> str:
    """
    Per evitare URL troppo lunghi (errore 422),
    limitiamo l’overlay a massimo 25 coordinate.

    Formato:
      path-5+ff4422-1(lon1,lat1;lon2,lat2;...)
    """
    max_pts = 25

    if len(points) > max_pts:
        step = max(1, len(points) // max_pts)
        pts = points[::step]
    else:
        pts = points

    coords = ";".join(f"{p['lon']},{p['lat']}" for p in pts)
    return f"path-5+ff4422-1({coords})"


# ------------------------------------------------------------
# RESAMPLING E TRAIETTORIA CAMERA (EFFETTO CINEMA)
# ------------------------------------------------------------
def _resample_along_path(
    points: List[Dict[str, float]],
    n_frames: int,
) -> List[Tuple[float, float, float]]:
    """
    Restituisce per ogni frame: (lat, lon, bearing).
    Usa un easing cosinusoidale per avere partenza/arrivo lenti
    e velocità maggiore a metà pista (effetto più cinematografico).
    """
    if len(points) < 2:
        p = points[0]
        return [(p["lat"], p["lon"], 0.0)] * n_frames

    # distanze cumulate
    dists = [0.0]
    for i in range(1, len(points)):
        a = points[i - 1]
        b = points[i]
        d = _dist_m(a["lat"], a["lon"], b["lat"], b["lon"])
        dists.append(dists[-1] + d)

    total = dists[-1] or 1.0

    # funzione easing: s(t) in [0,1]
    def ease(t: float) -> float:
        # smooth cos easing (slow start & end)
        return 0.5 * (1 - math.cos(math.pi * t))

    frames: List[Tuple[float, float, float]] = []

    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        s = ease(t)
        target = s * total

        # trova il segmento relativo
        j = 1
        while j < len(dists) and dists[j] < target:
            j += 1
        if j == len(dists):
            j = len(dists) - 1

        d2 = dists[j]
        d1 = dists[j - 1] if j > 0 else d2
        seg_len = max(d2 - d1, 1e-6)
        alpha = (target - d1) / seg_len if seg_len > 0 else 0.0

        p1 = points[j - 1]
        p2 = points[j]

        lat = p1["lat"] + alpha * (p2["lat"] - p1["lat"])
        lon = p1["lon"] + alpha * (p2["lon"] - p1["lon"])

        bearing = _bearing_deg(p1["lat"], p1["lon"], p2["lat"], p2["lon"])

        frames.append((lat, lon, bearing))

    return frames


# ------------------------------------------------------------
# DOWNLOAD FRAME DA MAPBOX
# ------------------------------------------------------------
def _fetch_frame(
    token: str,
    path_overlay: str,
    lat: float,
    lon: float,
    bearing: float,
    width: int,
    height: int,
    zoom: float,
    pitch: float,
) -> Image.Image:
    """
    Scarica un singolo frame dalla Mapbox Static API.
    """
    # bearing con piccolo roll sinusoidale per "cinema"
    bearing = bearing % 360.0

    url = (
        "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{path_overlay}/"
        f"{lon:.6f},{lat:.6f},{zoom:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{width}x{height}"
        f"?access_token={token}"
    )

    resp = requests.get(url, headers=UA, timeout=12)
    resp.raise_for_status()

    return Image.open(io.BytesIO(resp.content)).convert("RGB")


# ------------------------------------------------------------
# FUNZIONE PRINCIPALE
# ------------------------------------------------------------
def generate_pov_video(
    data: Union[PointSeq, GeoJSONFeature],
    pista_name: str,
    overwrite: bool = True,
) -> str:
    """
    Genera (o rigenera) una GIF POV 3D 12s per la pista.
    Restituisce il path del file GIF sul disco.
    """
    token = _get_mapbox_token()
    if not token:
        raise RuntimeError("MAPBOX_API_KEY non configurata (st.secrets o env).")

    # directory output
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.gif"

    if out_path.exists() and not overwrite:
        return str(out_path)

    # normalizza e pulisci punti
    raw_points = _normalize_input(data)
    if not raw_points or len(raw_points) < 2:
        raise ValueError("Pochi punti per generare il POV (minimo 2).")

    cleaned = _pick_main_segment(raw_points, max_jump_m=2000.0)
    if len(cleaned) < 4:
        raise ValueError(
            "Segmento pista troppo corto dopo pulizia; impossibile generare POV."
        )

    # overlay della pista (path ridotto per URL)
    path_overlay = _build_path_overlay(cleaned)

    # traiettoria camera con easing (effetto cinema)
    cam_frames = _resample_along_path(cleaned, TOTAL_FRAMES)

    imgs: List[Image.Image] = []

    for idx, (lat, lon, bearing_base) in enumerate(cam_frames):
        # piccolo roll sinusoidale ±ROLL_AMPLITUDE_DEG
        phase = 2.0 * math.pi * idx / max(TOTAL_FRAMES - 1, 1)
        roll = ROLL_AMPLITUDE_DEG * math.sin(phase)
        bearing = (bearing_base + roll) % 360.0

        img = _fetch_frame(
            token=token,
            path_overlay=path_overlay,
            lat=lat,
            lon=lon,
            bearing=bearing,
            width=FRAME_WIDTH,
            height=FRAME_HEIGHT,
            zoom=CAMERA_ZOOM,
            pitch=CAMERA_PITCH,
        )
        imgs.append(img)

    # converte in numpy array per imageio
    frames_np = [np.asarray(im) for im in imgs]
    frame_duration = TOTAL_SECONDS / max(len(frames_np), 1)  # secondi per frame

    imageio.mimsave(str(out_path), frames_np, duration=frame_duration)

    return str(out_path)
