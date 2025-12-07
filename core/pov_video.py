# core/pov.py
from __future__ import annotations

from typing import Dict, Any, List
import math

import requests
import streamlit as st

# -------------------------------------------------------------
# Config
# -------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
UA = {"User-Agent": "telemark-wax-pro/2.0"}

RADIUS_M = 900              # raggio di ricerca piste intorno al puntatore
MAX_POINTS_PER_PISTE = 160  # max punti per il profilo altimetrico


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


def _resample_points(
    points: List[Dict[str, float]], max_points: int
) -> List[Dict[str, float]]:
    """Semplifica la traccia mantenendo al massimo max_points vertici."""
    if len(points) <= max_points:
        return points

    step = max(1, len(points) // max_points)
    new_pts: List[Dict[str, float]] = []
    for idx in range(0, len(points), step):
        new_pts.append(points[idx])
    if new_pts[-1] is not points[-1]:
        new_pts.append(points[-1])
    return new_pts


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_pistes(lat: float, lon: float, radius_m: int) -> List[Dict[str, Any]]:
    """Scarica le piste da Overpass nel raggio specificato."""
    query = f"""[out:json][timeout:25];
(
  way["piste:type"]["area"!="yes"](around:{radius_m},{lat},{lon});
);
out geom tags;
"""
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, headers=UA, timeout=30)
        r.raise_for_status()
        js = r.json() or {}
    except Exception:
        return []

    elements = js.get("elements") or []
    pistes: List[Dict[str, Any]] = []

    for el in elements:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue

        pts: List[Dict[str, float]] = [
            {"lat": float(g["lat"]), "lon": float(g["lon"])} for g in geom
        ]

        # lunghezza stimata
        length = 0.0
        for i in range(1, len(pts)):
            a = pts[i - 1]
            b = pts[i]
            length += _dist_m(a["lat"], a["lon"], b["lat"], b["lon"])

        # distanza minima dal puntatore
        min_d = min(_dist_m(lat, lon, p["lat"], p["lon"]) for p in pts)

        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("ref") or "Pista senza nome"
        difficulty = tags.get("piste:difficulty") or ""
        ref = tags.get("ref") or ""

        label_parts = [name]
        if ref and ref not in name:
            label_parts.append(f"({ref})")
        if difficulty:
            label_parts.append(f"[{difficulty}]")
        label = " ".join(label_parts)

        pistes.append(
            {
                "id": el.get("id"),
                "name": name,
                "label": label,
                "difficulty": difficulty,
                "length_m": length,
                "dist_m": min_d,
                "points": pts,
            }
        )

    # la prima è quella più vicina (e a parità la più lunga)
    pistes.sort(key=lambda x: (x["dist_m"], -x["length_m"]))
    return pistes


def _fetch_elevation(points: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Arricchisce i punti con quota 'elev' usando Open-Meteo DEM.

    Se qualcosa va storto, restituisce i punti originali con elevazione 0.0.
    """
    if not points:
        return points

    pts = _resample_points(points, MAX_POINTS_PER_PISTE)

    lat_list = ",".join(f"{p['lat']:.5f}" for p in pts)
    lon_list = ",".join(f"{p['lon']:.5f}" for p in pts)

    elev: List[float]
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lat_list, "longitude": lon_list},
            headers=UA,
            timeout=15,
        )
        r.raise_for_status()
        js = r.json() or {}
        elev = js.get("elevation") or []
    except Exception:
        elev = []

    if len(elev) != len(pts):
        # fallback: quota piatta
        for p in pts:
            p["elev"] = 0.0
        return pts

    for p, h in zip(pts, elev):
        try:
            p["elev"] = float(h)
        except Exception:
            p["elev"] = 0.0

    return pts


def render_pov_extract(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Trova la pista più vicina al punto selezionato e prepara i dati POV.

    Aggiorna ctx con:
      - ctx["pov_piste_points"] = [{"lat","lon","elev"}, ...]
      - ctx["pov_piste_name"]   = nome pista
    """
    lat = float(ctx.get("lat") or 0.0)
    lon = float(ctx.get("lon") or 0.0)
    if not lat and not lon:
        st.info("POV non disponibile: posizione non valida.")
        return ctx

    with st.spinner("Cerco piste da sci vicine…"):
        pistes = _fetch_pistes(lat, lon, RADIUS_M)

    if not pistes:
        st.info(
            "Nessuna pista da sci trovata in un raggio di circa "
            f"{RADIUS_M} m. Sposta il puntatore più vicino alle piste."
        )
        ctx.pop("pov_piste_points", None)
        ctx.pop("pov_piste_name", None)
        return ctx

    st.caption(
        f"Piste trovate: {len(pistes)} — raggio ricerca ≈ {RADIUS_M} m "
        "(per default uso la più vicina al puntatore)."
    )

    # ---- selezione opzionale da lista ----
    use_list = st.checkbox(
        "Attiva selezione da lista piste",
        value=False,
        key="pov_use_list",
        help="Se attivo, puoi scegliere manualmente la pista tra quelle trovate.",
    )

    chosen = pistes[0]
    if use_list:
        labels = [
            f"{p['label']} · {int(p['length_m'])} m · {int(p['dist_m'])} m dal puntatore"
            for p in pistes
        ]
        label_to_p = {lab: p for lab, p in zip(labels, pistes)}

        prev_label = st.session_state.get("pov_selected_label")
        default_idx = labels.index(prev_label) if prev_label in label_to_p else 0

        selected_label = st.selectbox(
            "Pista da usare per POV",
            labels,
            index=default_idx,
            key="pov_piste_select",
        )
        st.session_state["pov_selected_label"] = selected_label
        chosen = label_to_p[selected_label]

    # ---- profilo con quota (serve per pendenza + POV 3D) ----
    pts_elev = _fetch_elevation(chosen["points"])

    ctx["pov_piste_points"] = pts_elev
    ctx["pov_piste_name"] = chosen["name"]

    length_m = chosen["length_m"]
    dist_m = chosen["dist_m"]
    st.markdown(
        "**Pista selezionata per il POV**: "
        f"{chosen['label']}  \n"
        f"Lunghezza stimata: ~{int(length_m)} m · distanza dal puntatore: ~{int(dist_m)} m."
    )

    return ctx
