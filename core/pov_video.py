# core/pov_video.py
# POV VIDEO 3D con Mapbox Static API -> MP4 + GIF
#
# - Usa Mapbox satellite 3D per geometria e orizzonte.
# - Camera bassa e inclinata in avanti: effetto quasi prima persona.
# - Pendenza locale della pista -> pitch dinamico (si “sente” il muro).
# - Smoothing su direzione e pendenza -> movimento fluido.
# - Effetto neve:
#     * agisce soprattutto sulla vegetazione (zone verdi)
#     * resto della scena solo leggermente desaturato
#     * niente filtro che “sbianca tutto”.
#
# Output:
#   videos/<nome_pista>_pov_12s.mp4
#   videos/<nome_pista>_pov_12s.gif

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union, Optional
import math
import io
import os

import requests
import numpy as np
from PIL import Image, ImageDraw
import imageio.v2 as imageio
import streamlit as st

# ------------------------------------------------------------
# CONFIGURAZIONE BASE
# ------------------------------------------------------------
UA = {"User-Agent": "telemark-wax-pro/2.0"}

# Durata target del POV
TOTAL_SECONDS = 12.0
# Più frame → più fluidità
TOTAL_FRAMES = 480  # ~40 fps

# Dimensioni frame
FRAME_WIDTH = 800
FRAME_HEIGHT = 450

# Camera: più bassa e molto inclinata in avanti
CAMERA_ZOOM = 17.0          # 17 = parecchio vicino al terreno
PITCH_MIN = 45.0            # falsopiano / pianetto
PITCH_MAX = 60.0            # muro ripido (max Mapbox)

# Piccola oscillazione cinematografica sul bearing
ROLL_AMPLITUDE_DEG = 3.0

# Smoothing
SMOOTH_WINDOW = 13          # numero di frame per la media mobile


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
      con eventuale quota in posizione [2].
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
# RESAMPLING & PENDENZA
# ------------------------------------------------------------
def _resample_along_path(
    points: List[Dict[str, float]],
    n_frames: int,
) -> List[Tuple[float, float, float, float]]:
    """
    Restituisce per ogni frame: (lat, lon, bearing, slope_deg).
    Usa un easing cosinusoidale per avere partenza/arrivo lenti.
    """
    if len(points) < 2:
        p = points[0]
        return [(p["lat"], p["lon"], 0.0, 0.0)] * n_frames

    dists = [0.0]
    slopes_deg: List[float] = []

    for i in range(1, len(points)):
        a = points[i - 1]
        b = points[i]
        horiz = max(_dist_m(a["lat"], a["lon"], b["lat"], b["lon"]), 1e-3)
        dz = float(b.get("elev", 0.0)) - float(a.get("elev", 0.0))

        # pendenza positiva in discesa
        slope_rad = math.atan2(-dz, horiz)
        slope = math.degrees(slope_rad)
        if slope < 0:
            slope = 0.0
        slopes_deg.append(slope)

        dists.append(dists[-1] + horiz)

    total = dists[-1] or 1.0

    def ease(t: float) -> float:
        # smooth cos easing (slow start & end)
        return 0.5 * (1 - math.cos(math.pi * t))

    frames: List[Tuple[float, float, float, float]] = []

    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        s = ease(t)
        target = s * total

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
        slope_here = slopes_deg[j - 1] if j - 1 < len(slopes_deg) else 0.0

        frames.append((lat, lon, bearing, slope_here))

    return frames


# ------------------------------------------------------------
# SMOOTHING (PER FLUIDITÀ)
# ------------------------------------------------------------
def _smooth(values: List[float], window: int) -> List[float]:
    if window <= 1 or len(values) <= 2:
        return values[:]

    k = window // 2
    padded = [values[0]] * k + values + [values[-1]] * k
    smoothed: List[float] = []

    for i in range(k, k + len(values)):
        window_vals = padded[i - k : i + k + 1]
        smoothed.append(sum(window_vals) / len(window_vals))

    return smoothed


def _smooth_angles_deg(angles: List[float], window: int) -> List[float]:
    if window <= 1 or len(angles) <= 2:
        return angles[:]

    rad = [math.radians(a) for a in angles]
    xs = [math.cos(r) for r in rad]
    ys = [math.sin(r) for r in rad]

    xs_s = _smooth(xs, window)
    ys_s = _smooth(ys, window)

    out: List[float] = []
    for x, y in zip(xs_s, ys_s):
        ang = math.degrees(math.atan2(y, x))
        out.append((ang + 360.0) % 360.0)
    return out


# ------------------------------------------------------------
# DOWNLOAD FRAME DA MAPBOX
# ------------------------------------------------------------
def _fetch_frame(
    token: str,
    path_overlay: str,
    lat: float,
    lon: float,
    bearing: float,
    pitch: float,
    width: int,
    height: int,
) -> Image.Image:
    """
    Scarica un singolo frame dalla Mapbox Static API.
    """
    bearing = bearing % 360.0
    pitch = max(0.0, min(60.0, pitch))

    url = (
        "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{path_overlay}/"
        f"{lon:.6f},{lat:.6f},{CAMERA_ZOOM:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{width}x{height}"
        f"?access_token={token}"
    )

    resp = requests.get(url, headers=UA, timeout=12)
    resp.raise_for_status()

    return Image.open(io.BytesIO(resp.content)).convert("RGB")


# ------------------------------------------------------------
# RENDERIZZAZIONE NEVE
# ------------------------------------------------------------
def _apply_snow_render(img: Image.Image) -> Image.Image:
    """
    Trasforma la scena in “invernale” privilegiando:
      - vegetazione (zone verdi) -> più bianco (neve)
      - edifici/rocce/strade: quasi originali, solo un pelo desaturati.

    NB: tutte le maschere sono 2D (H,W) così non ci sono errori di shape.
    """
    arr = np.asarray(img).astype(np.float32) / 255.0  # (H, W, 3)

    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]

    bright = (r + g + b) / 3.0  # (H, W)

    # vegetazione: verde dominante, non troppo scuro
    veg = (g > r * 1.15) & (g > b * 1.15) & (bright > 0.18)

    snow_arr = arr.copy()
    white = np.ones_like(arr)

    # zone neve -> verso il bianco ma manteniamo un po' di texture
    snow_arr[veg] = snow_arr[veg] * 0.45 + white[veg] * 0.55

    # desaturazione leggera globale per rendere l'ambiente più “freddo”
    gray = bright[..., None]                # (H, W, 1)
    gray3 = np.repeat(gray, 3, axis=2)
    snow_arr = snow_arr * 0.82 + gray3 * 0.18

    # leggerissima dominante fredda
    snow_arr[..., 2] = np.clip(snow_arr[..., 2] * 1.04, 0.0, 1.0)

    snow_arr = np.clip(snow_arr, 0.0, 1.0)
    out = (snow_arr * 255.0).astype("uint8")
    return Image.fromarray(out)


# ------------------------------------------------------------
# FUNZIONE PRINCIPALE
# ------------------------------------------------------------
def generate_pov_video(
    data: Union[PointSeq, GeoJSONFeature],
    pista_name: str,
    overwrite: bool = True,
) -> str:
    """
    Genera (o rigenera) un POV 3D 12s per la pista.
    Crea sia MP4 che GIF, ma restituisce il path dell'MP4.

    "data" può essere:
      - lista di punti {"lat", "lon", "elev"}
      - Feature GeoJSON LineString con coords [lon, lat, elev?]
    """
    token = _get_mapbox_token()
    if not token:
        raise RuntimeError("MAPBOX_API_KEY non configurata (st.secrets o env).")

    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(pista_name).lower()
    )
    out_gif = out_dir / f"{safe_name}_pov_12s.gif"
    out_mp4 = out_dir / f"{safe_name}_pov_12s.mp4"

    if out_mp4.exists() and not overwrite:
        return str(out_mp4)

    # normalizza e pulisci punti
    raw_points = _normalize_input(data)
    if not raw_points or len(raw_points) < 2:
        raise ValueError("Pochi punti per generare il POV (minimo 2).")

    cleaned = _pick_main_segment(raw_points, max_jump_m=2000.0)
    if len(cleaned) < 4:
        raise ValueError(
            "Segmento pista troppo corto dopo pulizia; impossibile generare POV."
        )

    # overlay ridotto per evitare URL 422
    path_overlay = _build_path_overlay(cleaned)

    # traiettoria camera con pendenze
    cam_frames = _resample_along_path(cleaned, TOTAL_FRAMES)

    # smoothing su bearing e pendenza per fluidità
    lats = [c[0] for c in cam_frames]
    lons = [c[1] for c in cam_frames]
    bearings = [c[2] for c in cam_frames]
    slopes = [c[3] for c in cam_frames]

    bearings_s = _smooth_angles_deg(bearings, SMOOTH_WINDOW)
    slopes_s = _smooth(slopes, SMOOTH_WINDOW)

    imgs: List[Image.Image] = []

    for idx, (lat, lon, bearing_base, slope_deg) in enumerate(
        zip(lats, lons, bearings_s, slopes_s)
    ):
        # pitch in base alla pendenza (0–40° -> PITCH_MIN–PITCH_MAX)
        slope_clamped = max(0.0, min(slope_deg, 40.0))
        t_pitch = slope_clamped / 40.0
        pitch = PITCH_MIN + (PITCH_MAX - PITCH_MIN) * t_pitch

        # piccolo roll sinusoidale sul bearing per effetto cinema
        phase = 2.0 * math.pi * idx / max(TOTAL_FRAMES - 1, 1)
        roll = ROLL_AMPLITUDE_DEG * math.sin(phase)
        bearing = (bearing_base + roll) % 360.0

        # frame satellite 3D
        img = _fetch_frame(
            token=token,
            path_overlay=path_overlay,
            lat=lat,
            lon=lon,
            bearing=bearing,
            pitch=pitch,
            width=FRAME_WIDTH,
            height=FRAME_HEIGHT,
        )

        # effetto neve
        img = _apply_snow_render(img)

        # HUD pendenza in alto a sinistra
        draw = ImageDraw.Draw(img)
        hud_text = f"{slope_deg:.0f}°"
        box_w, box_h = 60, 28
        draw.rectangle((8, 8, 8 + box_w, 8 + box_h), fill=(0, 0, 0))
        draw.text((14, 12), hud_text, fill=(255, 255, 255))

        imgs.append(img)

    frames_np = [np.asarray(im) for im in imgs]
    frame_duration = TOTAL_SECONDS / max(len(frames_np), 1)
    fps = len(frames_np) / TOTAL_SECONDS

    # GIF (loop infinito)
    imageio.mimsave(str(out_gif), frames_np, duration=frame_duration)

    # MP4 per st.video
    with imageio.get_writer(
        str(out_mp4),
        fps=fps,
        codec="libx264",
        quality=8,
    ) as writer:
        for fr in frames_np:
            writer.append_data(fr)

    return str(out_mp4)
