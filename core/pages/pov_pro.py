# core/pages/pov_pro.py
# Telemark · Pro Wax & Tune — POV PRO (2D + 3D + Video)

from __future__ import annotations

from typing import Any, Dict, Optional, List
from pathlib import Path
import os
import math

import streamlit as st

from core.i18n import L
from core import pov as pov_mod
from core import pov_3d as pov3d_mod
from core import pov_video as pov_video_mod


# -------------------------------------------------------------
# CONFIG PAGINA
# -------------------------------------------------------------
st.set_page_config(
    page_title="POV PRO — Piste",
    page_icon="🎬",
    layout="wide",
)

# lingua come nello streamlit_app
lang = st.session_state.get("lang", "IT")
T = L["it"] if lang == "IT" else L["en"]

st.title("🎬 POV PRO — Piste")
st.caption("Vista dedicata alla pista selezionata: POV 2D, 3D e video 12s.")


# -------------------------------------------------------------
# LETTURA CONTEXT DA session_state
# -------------------------------------------------------------
ctx: Dict[str, Any] = st.session_state.get("pov_ctx", {}) or {}

points: List[Dict[str, float]] = ctx.get("pov_piste_points") or []

if not points:
    st.error(
        "Nessun tracciato pista trovato per il POV.\n\n"
        "Torna alla pagina principale, seleziona una pista sulla mappa "
        "e usa il bottone **'Apri POV PRO'**."
    )
    st.stop()

pista_name: str = (
    ctx.get("pov_piste_name")
    or ctx.get("selected_piste_name")
    or T.get("selected_slope", "pista")
)
ctx["pov_piste_name"] = pista_name  # mi assicuro sia presente


# -------------------------------------------------------------
# STATISTICHE RAPIDE (lunghezza, dislivello)
# -------------------------------------------------------------
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


def _compute_stats(pts: List[Dict[str, float]]) -> Dict[str, float]:
    length = 0.0
    elevs: List[float] = []
    for i in range(1, len(pts)):
        a = pts[i - 1]
        b = pts[i]
        length += _dist_m(
            float(a.get("lat", 0.0)),
            float(a.get("lon", 0.0)),
            float(b.get("lat", 0.0)),
            float(b.get("lon", 0.0)),
        )
    for p in pts:
        elevs.append(float(p.get("elev", 0.0)))
    if elevs:
        min_e = min(elevs)
        max_e = max(elevs)
    else:
        min_e = max_e = 0.0

    return {
        "length_m": length,
        "vert_m": max_e - min_e,
        "min_elev": min_e,
        "max_elev": max_e,
    }


stats = _compute_stats(points)

col_info, col_nums = st.columns([2, 1])
with col_info:
    st.markdown(
        f"<div class='card small'>"
        f"<b>Pista selezionata:</b> {pista_name}<br>"
        f"<span class='small'>POV basato sui dati estratti dalla mappa.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
with col_nums:
    st.metric("Lunghezza stimata", f"{stats['length_m'] / 1000:.2f} km")
    st.metric("Dislivello", f"{stats['vert_m']:.0f} m")


st.divider()

# -------------------------------------------------------------
# POV 2D + 3D
# -------------------------------------------------------------
st.subheader("🎯 Vista 2D + 3D della pista")

c2d, c3d = st.columns(2)

with c2d:
    st.markdown("**POV 2D semplificato**")
    ctx = pov_mod.render_pov_extract(T, ctx) or ctx

with c3d:
    st.markdown("**POV 3D (pydeck + Mapbox)**")
    ctx = pov3d_mod.render_pov3d_view(T, ctx) or ctx

# mantengo il contesto aggiornato in session_state
st.session_state["pov_ctx"] = ctx


# -------------------------------------------------------------
# SEZIONE VIDEO POV 12s
# -------------------------------------------------------------
st.divider()
st.subheader("🎥 Video POV 3D (12 s) — esportabile")

def _render_pov_video_section(ctx: Dict[str, Any]) -> None:
    points = ctx.get("pov_piste_points") or []
    if not points:
        st.info("Video POV non disponibile: nessuna pista estratta.")
        return

    pista_name_local = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or T.get("selected_slope", "pista")
    )

    st.markdown("Genera un breve video POV (12 s) con camera tipo sciatore.")

    video_path: Optional[str] = None

    if st.button("🚀 Genera / aggiorna video POV 12s", key="btn_pov_video_pro"):
        with st.spinner("Genero il POV invernale della pista…"):
            try:
                video_path = pov_video_mod.generate_pov_video(points, pista_name_local)
                st.success("Video POV generato.")
            except Exception as e:
                st.error(f"Impossibile generare il video POV: {e}")
                video_path = None

    # Se non ho appena generato, provo a caricare da cache su disco
    if video_path is None:
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in str(pista_name_local).lower()
        )
        candidate_gif = Path("videos") / f"{safe_name}_pov_12s.gif"
        candidate_mp4 = Path("videos") / f"{safe_name}_pov_12s.mp4"
        if candidate_mp4.exists():
            video_path = str(candidate_mp4)
        elif candidate_gif.exists():
            video_path = str(candidate_gif)

    # Mostra video / GIF se disponibile
    if video_path is not None and os.path.exists(video_path):
        if video_path.lower().endswith(".gif"):
            st.image(video_path)
        else:
            st.video(video_path)

        # bottone download
        try:
            with open(video_path, "rb") as f:
                mime = "image/gif" if video_path.lower().endswith(".gif") else "video/mp4"
                st.download_button(
                    "📥 Scarica POV",
                    data=f,
                    file_name=os.path.basename(video_path),
                    mime=mime,
                    key="dl_pov_pro",
                )
        except Exception:
            pass
    else:
        st.caption("Nessun file POV trovato ancora: genera il video per creare il file.")


_render_pov_video_section(ctx)
