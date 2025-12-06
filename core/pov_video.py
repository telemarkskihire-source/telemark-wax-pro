# core/pov_video.py
# POV 3D "in prima persona" generato come GIF animata
#
# - NIENTE moviepy, NIENTE ffmpeg → compatibile con Streamlit Cloud
# - Usa solo Pillow + numpy per disegnare i frame
# - Può lavorare sia:
#     a) da ctx["pov_piste_points"] (flusso raccomandato, come POV 3D)
#     b) da una feature GeoJSON (back-compat con generate_pov_video)
#
# Uso consigliato nella app:
#   from core import pov_video as pov_video_mod
#   ctx = pov_video_mod.render_pov_video_section(T, ctx)
#
# Il file GIF viene salvato in ./videos/<pista>_pov_12s.gif
# e mostrato con st.image.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Iterable

import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# ---------------------------------------------------------------------
# CONFIGURAZIONE GENERALE
# ---------------------------------------------------------------------

# Cartella dove salvare le GIF POV
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)

# Durata e frame-rate GIF
GIF_DURATION_S = 12          # secondi
GIF_FPS = 24                 # frame al secondo
N_FRAMES = GIF_DURATION_S * GIF_FPS

# Risoluzione GIF (ridotta per peso / performance)
WIDTH = 960
HEIGHT = 540


# ---------------------------------------------------------------------
# UTILS GEO
# ---------------------------------------------------------------------

def _haversine_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri tra due coordinate geografiche."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ---------------------------------------------------------------------
# COSTRUZIONE TRACCIA
# ---------------------------------------------------------------------

def _build_track_from_ctx_points(points: Iterable[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Converte i punti ctx["pov_piste_points"] in una traccia con:
      lat, lon, elev, dist (distanza cumulativa).
    """
    pts = list(points)
    if len(pts) < 2:
        return []

    track: List[Dict[str, float]] = []
    dist = 0.0

    prev_lat = float(pts[0].get("lat", 0.0))
    prev_lon = float(pts[0].get("lon", 0.0))
    prev_elev = float(pts[0].get("elev", 0.0))
    track.append(
        {
            "lat": prev_lat,
            "lon": prev_lon,
            "elev": prev_elev,
            "dist": 0.0,
        }
    )

    for p in pts[1:]:
        lat = float(p.get("lat", 0.0))
        lon = float(p.get("lon", 0.0))
        elev = float(p.get("elev", prev_elev))
        d = _haversine_dist(prev_lat, prev_lon, lat, lon)
        dist += d
        track.append(
            {
                "lat": lat,
                "lon": lon,
                "elev": elev,
                "dist": dist,
            }
        )
        prev_lat, prev_lon, prev_elev = lat, lon, elev

    return track


def _build_track_from_feature(feature: Dict[str, Any]) -> List[Dict[str, float]]:
    """
    Back-compat: costruisce la traccia da una Feature GeoJSON
    geometry.type = 'LineString', coords = [lon, lat, (elev?)].

    Elevazione: se non presente, assume 0.
    """
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if not coords:
        return []

    lats = []
    lons = []
    elevs = []

    for c in coords:
        if len(c) >= 2:
            lon = float(c[0])
            lat = float(c[1])
            lons.append(lon)
            lats.append(lat)
            if len(c) >= 3:
                elevs.append(float(c[2]))
            else:
                elevs.append(0.0)

    if len(lats) < 2:
        return []

    track: List[Dict[str, float]] = []
    dist = 0.0

    prev_lat = lats[0]
    prev_lon = lons[0]
    prev_elev = elevs[0]
    track.append(
        {
            "lat": prev_lat,
            "lon": prev_lon,
            "elev": prev_elev,
            "dist": 0.0,
        }
    )

    for lat, lon, elev in zip(lats[1:], lons[1:], elevs[1:]):
        d = _haversine_dist(prev_lat, prev_lon, lat, lon)
        dist += d
        track.append(
            {
                "lat": lat,
                "lon": lon,
                "elev": elev,
                "dist": dist,
            }
        )
        prev_lat, prev_lon, prev_elev = lat, lon, elev

    return track


def _resample_track(track: List[Dict[str, float]], n_points: int = 320) -> List[Dict[str, float]]:
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
            p1 = track[idx - 1]
            p2 = track[idx]
            t = float((td - dists[idx - 1]) / (dists[idx] - dists[idx - 1] + 1e-9))

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
# RENDERING POV INVERNALE
# ---------------------------------------------------------------------

def _load_fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
    """Carica due font (titolo + testo). Fallback: default."""
    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 26)
    except Exception:
        font_title = ImageFont.load_default()
        font_small = ImageFont.load_default()
    return font_title, font_small


def _draw_pov_frame(track: List[Dict[str, float]], t_norm: float, pista_name: str) -> Image.Image:
    """
    Crea un singolo frame POV stile "volo d'uccello" invernale:
    - cielo blu freddo
    - montagne innevate
    - vallata con boschi
    - pista in prospettiva che scende verso il basso
    """
    # Setup immagine
    img = Image.new("RGB", (WIDTH, HEIGHT), (200, 220, 240))
    draw = ImageDraw.Draw(img)

    # --- CIELO INVERNALE (gradiente blu freddo) ---
    sky_h = int(HEIGHT * 0.45)
    for y in range(sky_h):
        blend = y / max(1, sky_h - 1)
        r = int(40 + 20 * blend)
        g = int(80 + 40 * blend)
        b = int(140 + 50 * blend)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # --- MONTAGNE INNEVATE (sfondo) ---
    # Due strati di montagne stilizzate, leggermente sfalsati
    mid_y = sky_h + 40
    mountain_colors = [(220, 230, 235), (205, 215, 225)]
    offsets = [-220, 120]
    for offset, col in zip(offsets, mountain_colors):
        draw.polygon(
            [
                (0 + offset, mid_y + 30),
                (WIDTH * 0.25 + offset, sky_h - 40),
                (WIDTH * 0.55 + offset, mid_y),
                (WIDTH * 0.9 + offset, sky_h - 30),
                (WIDTH * 1.2 + offset, mid_y + 40),
            ],
            fill=col,
        )

    # Creste rocciose più scure sotto la neve
    ridge_y = mid_y + 15
    draw.rectangle([0, ridge_y, WIDTH, ridge_y + 25], fill=(170, 180, 190))

    # --- NEVE / PENDENZA (primo piano) ---
    snow_top = int(HEIGHT * 0.33)
    draw.rectangle([0, snow_top, WIDTH, HEIGHT], fill=(245, 247, 252))

    # --- PARAMETRI PROSPETTIVA ---
    center_x = WIDTH // 2
    horizon_y = snow_top + 40
    bottom_y = HEIGHT + 40

    # Tendenza curva in funzione dell'andamento reale della pista
    # (usiamo finestra di punti attorno alla posizione corrente)
    idx = int(t_norm * max(1, len(track) - 1))
    idx = max(2, min(len(track) - 3, idx))

    window = track[idx - 2: idx + 3]
    dlon = window[-1]["lon"] - window[0]["lon"]
    curvature = max(-1.0, min(1.0, dlon * 200))  # fattore grezzo per dx / sx

    # larghezza pista in prospettiva
    width_bottom = WIDTH * 0.85
    width_top = WIDTH * 0.08

    center_shift = curvature * (WIDTH * 0.15)
    cx_bottom = center_x + center_shift
    cx_top = center_x + center_shift * 0.4

    # Poligono pista (neve battuta)
    pista_poly = [
        (cx_bottom - width_bottom / 2, bottom_y),
        (cx_bottom + width_bottom / 2, bottom_y),
        (cx_top + width_top / 2, horizon_y),
        (cx_top - width_top / 2, horizon_y),
    ]
    draw.polygon(pista_poly, fill=(235, 243, 250))

    # Aggiungo leggere bande di pressione / strutture neve
    for i in range(12):
        f = i / 11.0
        x1 = cx_bottom - width_bottom * 0.45 + width_bottom * 0.9 * f
        y1 = bottom_y - (bottom_y - horizon_y) * (0.1 + 0.8 * f)
        x2 = x1 + 30
        y2 = y1 + 4
        col = (220, 230, 240)
        draw.rectangle([x1, y1, x2, y2], fill=col)

    # --- BOSCO AI LATI (macchie di abeti scuri) ---
    forest_color = (50, 90, 70)
    for side in (-1, 1):
        for i in range(40):
            f = i / 40.0
            base_x = cx_bottom + side * (width_bottom / 2 + 30 + 80 * f)
            base_y = bottom_y - (bottom_y - snow_top) * f
            h = 35 + 40 * (1 - f)
            w = 18 + 10 * (1 - f)
            x1 = base_x - w / 2
            y1 = base_y - h
            x2 = base_x + w / 2
            y2 = base_y
            draw.polygon(
                [(x1, y2), ((x1 + x2) / 2, y1), (x2, y2)],
                fill=forest_color,
            )

    # --- RETI LATERALI (linee rosse) ---
    net_color = (220, 40, 40)
    steps = 12
    for side in (-1, 1):
        for i in range(steps):
            f = i / steps
            x1 = cx_bottom + side * (width_bottom / 2) * (1 - f * 0.8)
            y1 = bottom_y - (bottom_y - horizon_y) * f
            x2 = x1 + side * 22
            y2 = y1 - 32
            draw.line([(x1, y1), (x2, y2)], fill=net_color, width=2)

    # --- TRACCIA CENTRALE (linea gara) ---
    gate_color = (160, 180, 210)
    for i in range(32):
        f = i / 32.0
        x = cx_bottom + (cx_top - cx_bottom) * f
        y = bottom_y + (horizon_y - bottom_y) * f
        r = max(1, int(6 - 4 * f))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=gate_color)

    # -----------------------------------------------------------------
    # HUD / TESTO
    # -----------------------------------------------------------------
    font_title, font_small = _load_fonts()

    # Barra semi-trasparente in alto
    hud_h = 82
    hud = Image.new("RGBA", (WIDTH, hud_h), (0, 0, 0, 130))
    img.paste(hud, (0, 0), hud)

    # Info altitudine e distanza (stimate dal track)
    p = track[idx]
    alt = float(p["elev"])
    dist = float(p["dist"])
    total_dist = float(track[-1]["dist"])

    title_text = f"{pista_name} – POV 3D"
    info_text = f"Alt: {alt:.0f} m   Distanza: {dist/1000:.2f} / {total_dist/1000:.2f} km"

    draw = ImageDraw.Draw(img)
    draw.text((26, 18), title_text, fill=(255, 255, 255), font=font_title)
    draw.text((26, 52), info_text, fill=(235, 245, 255), font=font_small)

    # Indicatore progresso a destra
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

    return img


# ---------------------------------------------------------------------
# GENERAZIONE GIF
# ---------------------------------------------------------------------

def _safe_filename_from_name(pista_name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pista_name.lower())
    if not safe:
        safe = "pista"
    return safe


def _generate_gif_from_track(track: List[Dict[str, float]], pista_name: str) -> str:
    """
    Genera (o rigenera) la GIF POV da una traccia geometrica.
    Restituisce il path locale del file GIF.
    """
    if len(track) < 5:
        raise ValueError("Traccia insufficiente per POV (meno di 5 punti).")

    track = _resample_track(track, n_points=320)

    safe_name = _safe_filename_from_name(pista_name)
    out_path = VIDEO_DIR / f"{safe_name}_pov_12s.gif"

    frames: List[Image.Image] = []
    for i in range(N_FRAMES):
        t_norm = i / max(1, N_FRAMES - 1)
        frame = _draw_pov_frame(track, t_norm, pista_name)
        frames.append(frame)

    duration_ms = int(1000 / GIF_FPS)  # durata per frame
    frames[0].save(
        str(out_path),
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )

    return str(out_path)


# ---------------------------------------------------------------------
# API PUBBLICHE
# ---------------------------------------------------------------------

def generate_pov_video(feature: Dict[str, Any], pista_name: str) -> str:
    """
    Back-compat: stessa firma storica ma ora genera una GIF POV 3D.

    feature: Feature OSM/GeoJSON LineString.
    pista_name: nome leggibile pista.

    Ritorna: path del file GIF.
    """
    track = _build_track_from_feature(feature)
    if not track:
        raise ValueError("Impossibile costruire la traccia dalla feature.")
    return _generate_gif_from_track(track, pista_name)


def generate_pov_gif_from_ctx(ctx: Dict[str, Any]) -> Optional[str]:
    """
    Nuova API principale per la app:
      - legge ctx["pov_piste_points"] (lista dict lat/lon/elev)
      - legge ctx["pov_piste_name"] o ctx["selected_piste_name"]
      - genera la GIF POV 3D
    """
    raw_points = ctx.get("pov_piste_points") or ctx.get("selected_piste_points")
    if not raw_points:
        return None

    pista_name = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or "pista selezionata"
    )

    track = _build_track_from_ctx_points(raw_points)
    if not track:
        return None

    try:
        path = _generate_gif_from_track(track, str(pista_name))
    except Exception as e:
        st.error(f"Errore nella generazione GIF POV: {e}")
        return None

    return path


def render_pov_video_section(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sezione Streamlit completa per il video POV 3D:

    - Mostra titolo + pulsante "Genera / aggiorna video POV"
    - Usa ctx["pov_piste_points"] (se presenti)
    - Mostra la GIF in pagina (st.image)
    """
    st.markdown("### 🎬 Video POV 3D (GIF 12 s)")

    if not ctx.get("pov_piste_points"):
        st.info(
            "Per generare il video POV serve una pista estratta. "
            "Seleziona prima una pista dalla mappa."
        )
        return ctx

    pista_name = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or "pista selezionata"
    )
    safe_name = _safe_filename_from_name(str(pista_name))
    gif_path = VIDEO_DIR / f"{safe_name}_pov_12s.gif"

    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        do_generate = st.button("Genera / aggiorna video POV", key="btn_generate_pov_gif")
    with col_info:
        if gif_path.exists():
            st.caption(f"GIF attuale: `{gif_path.name}` (clicca il bottone per rigenerarla).")
        else:
            st.caption("Nessuna GIF POV generata per questa pista.")

    if do_generate or not gif_path.exists():
        path = generate_pov_gif_from_ctx(ctx)
        if path:
            st.success("GIF POV generata con successo.")
            gif_path = Path(path)
        else:
            st.error("Impossibile generare la GIF POV per questa pista.")

    if gif_path.exists():
        st.image(
            str(gif_path),
            caption=f"POV 3D GIF della pista {pista_name}",
            use_column_width=True,
        )
        ctx["pov_gif_path"] = str(gif_path)

    return ctx
