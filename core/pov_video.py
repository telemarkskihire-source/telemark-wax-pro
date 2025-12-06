# core/pov_video.py
# POV 3D / 2.5D in GIF stile GoPro per piste da sci
#
# - NON usa moviepy / ffmpeg: solo Pillow.
# - Input flessibile:
#       · lista di punti   [{lat, lon, elev?}, ...]
#       · lista di tuple   [ (lat, lon), (lat, lon, elev), ... ]
#       · Feature GeoJSON  {"geometry": {"type": "LineString", "coordinates": [[lon, lat], ...]}}
# - Output: GIF 16:9 salvata in "videos/<nome_pista>_pov.gif"
#
# Funzione principale usata dalla app:
#
#   generate_pov_video(points_or_feature, pista_name) -> str (path GIF)
#
# La funzione è robusta:
#   - clamp automatico di tutte le coordinate nello schermo
#   - nessun errore del tipo "y1 must be greater than or equal to y0"

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Union
from pathlib import Path
import math
import os

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------
# CONFIG VIDEO / GIF
# ---------------------------------------------------------------------

FRAME_RATE = 25               # fps (GIF fluida ma non enorme)
VIDEO_DURATION = 12           # secondi
N_FRAMES = FRAME_RATE * VIDEO_DURATION

# Risoluzione video (16:9)
WIDTH = 1280
HEIGHT = 720

# Directory di output per le GIF
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------
# UTILS GEO & TRACCIA
# ---------------------------------------------------------------------

def _haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due punti (lat/lon in gradi)."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _normalize_points(
    raw: Union[List[Any], Dict[str, Any]]
) -> List[Dict[str, float]]:
    """
    Normalizza vari formati di input in:
        [{"lat": float, "lon": float, "elev": float}, ...]
    Elevazione opzionale → default 0.0.
    """
    points: List[Dict[str, float]] = []

    # Caso Feature GeoJSON
    if isinstance(raw, dict) and "geometry" in raw:
        geom = raw.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates") or []  # [lon, lat] o [lon, lat, elev]
            for c in coords:
                if not isinstance(c, (list, tuple)) or len(c) < 2:
                    continue
                lon = float(c[0])
                lat = float(c[1])
                elev = float(c[2]) if len(c) > 2 else 0.0
                points.append({"lat": lat, "lon": lon, "elev": elev})
        return points

    # Caso lista generica
    if isinstance(raw, list):
        for p in raw:
            # dict con lat/lon/elev
            if isinstance(p, dict):
                try:
                    lat = float(p.get("lat") or p.get("latitude"))
                    lon = float(p.get("lon") or p.get("longitude"))
                except Exception:
                    continue
                elev = float(p.get("elev") or p.get("elevation") or 0.0)
                points.append({"lat": lat, "lon": lon, "elev": elev})
            # lista/tupla [lat, lon] o [lat, lon, elev] o [lon, lat, elev]
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    a, b = float(p[0]), float(p[1])
                except Exception:
                    continue

                # euristica: lon ha modulo > 90 di solito
                if abs(a) > 90 and abs(b) <= 90:
                    lon, lat = a, b
                else:
                    lat, lon = a, b

                elev = 0.0
                if len(p) > 2:
                    try:
                        elev = float(p[2])
                    except Exception:
                        elev = 0.0

                points.append({"lat": lat, "lon": lon, "elev": elev})

    return points


def _build_track(raw: Union[List[Any], Dict[str, Any]]) -> List[Dict[str, float]]:
    """
    Converte l'input in una traccia con:
      {"lat", "lon", "elev", "dist"}
    dove "dist" è la distanza cumulativa in metri.
    """
    pts = _normalize_points(raw)
    if len(pts) < 2:
        return []

    # Se tutte le elevazioni sono 0, aggiungo una pendenza leggera fittizia
    elevs = [p["elev"] for p in pts]
    if max(elevs) == min(elevs):
        # calo di 300 m lungo la pista
        total = len(pts) - 1
        for i, p in enumerate(pts):
            p["elev"] = float(pts[0]["elev"] + (i / max(1, total)) * -300.0)

    # distanza cumulativa
    dists = [0.0]
    for i in range(1, len(pts)):
        p1 = pts[i - 1]
        p2 = pts[i]
        d = _haversine_dist(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
        dists.append(dists[-1] + d)

    for p, d in zip(pts, dists):
        p["dist"] = d

    return pts


def _resample_track(track: List[Dict[str, float]], n_points: int) -> List[Dict[str, float]]:
    """
    Uniforma la traccia a n_points equispaziati in distanza.
    Utile per avere un POV fluido e costante.
    """
    if len(track) <= n_points:
        return track

    total = track[-1]["dist"]
    if total <= 0:
        return track

    resampled: List[Dict[str, float]] = []
    idx = 0

    for i in range(n_points):
        target_d = (i / max(1, n_points - 1)) * total

        while idx < len(track) - 2 and track[idx + 1]["dist"] < target_d:
            idx += 1

        p1 = track[idx]
        p2 = track[idx + 1]
        d1 = p1["dist"]
        d2 = p2["dist"]

        if d2 <= d1:
            t = 0.0
        else:
            t = (target_d - d1) / (d2 - d1)

        lat = p1["lat"] + (p2["lat"] - p1["lat"]) * t
        lon = p1["lon"] + (p2["lon"] - p1["lon"]) * t
        elev = p1["elev"] + (p2["elev"] - p1["elev"]) * t

        resampled.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "elev": float(elev),
                "dist": float(target_d),
            }
        )

    return resampled


# ---------------------------------------------------------------------
# UTILS GRAFICI — CLAMP SAFE
# ---------------------------------------------------------------------

def _cx(x: float) -> int:
    """Clamp X nelle coordinate schermo."""
    return max(0, min(WIDTH - 1, int(round(x))))


def _cy(y: float) -> int:
    """Clamp Y nelle coordinate schermo."""
    return max(0, min(HEIGHT - 1, int(round(y))))


def _safe_rect(draw: ImageDraw.ImageDraw, x0, y0, x1, y1, **kwargs) -> None:
    """Disegna un rettangolo solo se l'area è valida, clampando le coordinate."""
    x0, x1 = sorted((_cx(x0), _cx(x1)))
    y0, y1 = sorted((_cy(y0), _cy(y1)))
    if x1 <= x0 or y1 <= y0:
        return
    draw.rectangle([x0, y0, x1, y1], **kwargs)


def _safe_polygon(draw: ImageDraw.ImageDraw, pts, **kwargs) -> None:
    """Disegna un poligono con clamp coordinate (Pillow accetta punti fuori, ma noi ripuliamo)."""
    clamped = [(_cx(x), _cy(y)) for (x, y) in pts]
    if len(clamped) < 3:
        return
    draw.polygon(clamped, **kwargs)


# ---------------------------------------------------------------------
# RENDERING POV 2.5D (STILE GOPRO / PRIMA PERSONA)
# ---------------------------------------------------------------------

def _draw_pov_frame(
    track: List[Dict[str, float]],
    t_norm: float,
    pista_name: str,
) -> Image.Image:
    """
    Crea un singolo frame POV stile GoPro:
      - neve in primo piano
      - pista centrale in prospettiva
      - bosco / montagne sullo sfondo
      - HUD con altitudine e distanza
    """
    # Setup immagine
    img = Image.new("RGB", (WIDTH, HEIGHT), (200, 220, 240))
    draw = ImageDraw.Draw(img)

    # Fondo cielo (gradientino semplice)
    sky_h = int(HEIGHT * 0.45)
    for y in range(sky_h):
        alpha = y / max(1, sky_h - 1)
        # azzurro freddo → più chiaro verso l'orizzonte
        r = int(80 + 40 * alpha)
        g = int(120 + 50 * alpha)
        b = int(170 + 60 * alpha)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # Montagne stilizzate (sfondo innevato)
    mid_y = sky_h + 40
    mountain_colors = [(215, 222, 230), (190, 200, 214)]
    offsets = [-250, 180]
    for offset, color in zip(offsets, mountain_colors):
        _safe_polygon(
            draw,
            [
                (0 + offset, mid_y + 40),
                (WIDTH * 0.25 + offset, sky_h - 60),
                (WIDTH * 0.55 + offset, mid_y),
                (WIDTH * 0.9 + offset, mid_y + 50),
            ],
            fill=color,
        )

    # Neve / pendio in primo piano
    snow_top = int(HEIGHT * 0.35)
    _safe_rect(draw, 0, snow_top, WIDTH, HEIGHT, fill=(242, 246, 252))

    # Parametri prospettiva
    center_x = WIDTH // 2
    horizon_y = snow_top + 35
    bottom_y = HEIGHT + 80  # sotto lo schermo per dare profondità

    # Posizione sulla pista (indice)
    idx = int(t_norm * (len(track) - 1))
    idx = max(2, min(len(track) - 3, idx))

    # curvatura stimata dalla variazione di lon/lat
    window = track[idx - 2: idx + 3]
    dlon = window[-1]["lon"] - window[0]["lon"]
    curvature = max(-1.0, min(1.0, dlon * 200.0))  # fattore grezzo per curva

    # larghezza pista (in basso e in alto)
    width_bottom = WIDTH * 0.8
    width_top = WIDTH * 0.12

    # spostamento laterale del centro
    center_shift = curvature * (WIDTH * 0.18)

    cx_bottom = center_x + center_shift
    cx_top = center_x + center_shift * 0.4

    # Poligono pista (trapezio prospettico)
    pista_poly = [
        (cx_bottom - width_bottom / 2, bottom_y),
        (cx_bottom + width_bottom / 2, bottom_y),
        (cx_top + width_top / 2, horizon_y),
        (cx_top - width_top / 2, horizon_y),
    ]
    _safe_polygon(draw, pista_poly, fill=(230, 238, 248))

    # Ombre laterali / bordo pista
    shade_color = (210, 220, 234)
    _safe_polygon(
        draw,
        [
            (0, HEIGHT),
            (cx_bottom - width_bottom / 2, bottom_y),
            (cx_top - width_top / 2 - 40, horizon_y),
            (0, HEIGHT),
        ],
        fill=shade_color,
    )
    _safe_polygon(
        draw,
        [
            (WIDTH, HEIGHT),
            (cx_bottom + width_bottom / 2, bottom_y),
            (cx_top + width_top / 2 + 40, horizon_y),
            (WIDTH, HEIGHT),
        ],
        fill=shade_color,
    )

    # Reti laterali (linee rosse)
    net_color = (220, 40, 40)
    steps = 14
    for side in (-1, 1):
        for i in range(steps):
            f = i / steps
            x1 = cx_bottom + side * (width_bottom / 2) * (1 - f)
            y1 = bottom_y - (bottom_y - horizon_y) * f
            x2 = x1 + side * 24
            y2 = y1 - 32
            draw.line(
                [(_cx(x1), _cy(y1)), (_cx(x2), _cy(y2))],
                fill=net_color,
                width=2,
            )

    # Traccia centrale (linea di gara)
    line_color = (160, 180, 205)
    for i in range(36):
        f = i / 36.0
        x = cx_bottom + (cx_top - cx_bottom) * f
        y = bottom_y + (horizon_y - bottom_y) * f
        r = max(1, int(7 - 5 * f))
        x0, y0 = _cx(x - r), _cy(y - r)
        x1, y1 = _cx(x + r), _cy(y + r)
        if x1 <= x0 or y1 <= y0:
            continue
        draw.ellipse([x0, y0, x1, y1], fill=line_color)

    # -----------------------------------------------------------------
    # HUD / TESTO
    # -----------------------------------------------------------------
    # Punto attuale per info altitudine/distanza
    p = track[idx]
    alt = p["elev"]
    dist = p["dist"]
    total_dist = track[-1]["dist"]

    # Carica font (fallback se manca arial)
    try:
        font_title = ImageFont.truetype("arial.ttf", 38)
        font_small = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Barra semi-trasparente in alto
    hud_h = 90
    hud = Image.new("RGBA", (WIDTH, hud_h), (0, 0, 0, 140))
    img.paste(hud, (0, 0), hud)

    # Testi
    draw = ImageDraw.Draw(img)
    title_text = f"{pista_name} – POV 3D"
    draw.text(
        (_cx(30), _cy(18)),
        title_text,
        fill=(255, 255, 255),
        font=font_title,
    )

    info_text = (
        f"Alt: {alt:.0f} m    Distanza: {dist/1000:.2f} km / {total_dist/1000:.2f} km"
    )
    draw.text(
        (_cx(30), _cy(54)),
        info_text,
        fill=(235, 240, 255),
        font=font_small,
    )

    # Indicatore progresso a destra
    bar_w = 18
    bar_x = WIDTH - 70
    bar_y1 = 18
    bar_y2 = hud_h - 18
    _safe_rect(
        draw,
        bar_x,
        bar_y1,
        bar_x + bar_w,
        bar_y2,
        outline=(255, 255, 255),
        width=2,
    )

    prog_y = bar_y2 - (bar_y2 - bar_y1) * t_norm
    # piccolo "riempimento" dal basso fino alla posizione corrente
    _safe_rect(
        draw,
        bar_x + 3,
        prog_y,
        bar_x + bar_w - 3,
        bar_y2 - 3,
        fill=(255, 80, 80),
    )

    return img


# ---------------------------------------------------------------------
# GENERAZIONE GIF POV
# ---------------------------------------------------------------------

def generate_pov_video(
    points_or_feature: Union[List[Any], Dict[str, Any]],
    pista_name: str,
) -> str:
    """
    Entry point usato dallo streamlit_app.

    Accetta:
      - lista di punti (dict / tuple / list)
      - Feature GeoJSON OSM

    Ritorna:
      path assoluto (stringa) della GIF generata.
    """
    # Nome file sicuro
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in pista_name.lower()
    ) or "pista"

    out_path = VIDEO_DIR / f"{safe_name}_pov.gif"

    # Se già esiste, lo rigeneriamo comunque (ci mettono comunque poco)
    track = _build_track(points_or_feature)
    if len(track) < 5:
        raise ValueError("Traccia insufficiente per POV (meno di 5 punti validi).")

    # Traccia resampled per fluidità
    track = _resample_track(track, n_points=600)

    frames: List[Image.Image] = []
    for i in range(N_FRAMES):
        t_norm = i / max(1, N_FRAMES - 1)
        frame = _draw_pov_frame(track, t_norm, pista_name)
        frames.append(frame)

    # Salva GIF animata con Pillow
    if not frames:
        raise ValueError("Nessun frame generato per il POV.")

    duration_ms = int(1000 / FRAME_RATE)  # durata per frame in ms
    first, *rest = frames
    first.save(
        out_path,
        save_all=True,
        append_images=rest,
        duration=duration_ms,
        loop=0,
        optimize=False,
    )

    return str(out_path)
