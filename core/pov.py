# core/pov.py
# POV 2D + estrazione pista per Telemark · Pro Wax & Tune
#
# Questo modulo:
#   - prende la pista selezionata dal ctx
#   - normalizza i punti in una polyline
#   - li salva in ctx["pov_piste_points"] + ctx["pov_piste_name"]
#   - mostra un POV 2D statico (linea rossa) usando pydeck se disponibile
#
# Nessun uso di deck_kwargs, nessuna gestione Mapbox (solo linea su sfondo semplice).

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

try:
    import pydeck as pdk
except Exception:  # pydeck non disponibile
    pdk = None  # type: ignore[assignment]


def _normalize_points(raw_points: Any) -> List[Dict[str, float]]:
    """
    Normalizza i punti della pista in formato uniforme:
      [{ "lat": ..., "lon": ..., "elev": ... }, ...]
    Accetta:
      - lista di dict con chiavi lat/lon/elev_m
      - lista di liste/tuple [lat, lon] o [lat, lon, elev] o [lon, lat, elev]
    """
    if not raw_points:
        return []

    out: List[Dict[str, float]] = []

    for p in raw_points:
        lat = lon = elev = None

        # dict
        if isinstance(p, dict):
            lat = p.get("lat") or p.get("latitude")
            lon = p.get("lon") or p.get("longitude")
            elev = p.get("elev_m") or p.get("elevation") or 0.0

        # lista/tuple
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            a, b = float(p[0]), float(p[1])

            # euristica: lon di solito ha modulo > 90
            if abs(a) > 90 and abs(b) <= 90:
                lon, lat = a, b
            else:
                lat, lon = a, b

            elev = float(p[2]) if len(p) > 2 else 0.0

        if lat is None or lon is None:
            continue

        try:
            out.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "elev": float(elev or 0.0),
                }
            )
        except Exception:
            continue

    return out


def _guess_piste_points_from_ctx(ctx: Dict[str, Any]) -> List[Dict[str, float]]:
    """
    Cerca i punti della pista nel contesto.
    Prova varie chiavi per compatibilità con versioni precedenti di core.maps.
    """
    candidates = [
        "pov_piste_points",
        "selected_piste_points",
        "selected_piste_polyline",
        "selected_piste_coords",
    ]

    raw = None
    for key in candidates:
        if key in ctx and ctx[key]:
            raw = ctx[key]
            break

    return _normalize_points(raw)


def render_pov_extract(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estrae la pista selezionata dal ctx, la salva nei campi POV e,
    se possibile, mostra un POV 2D statico.
    """
    # 1) Trovo i punti della pista
    points = _guess_piste_points_from_ctx(ctx)
    if not points:
        st.info("POV non disponibile per questa località (nessuna pista selezionata).")
        return ctx

    # 2) Salvo nel contesto per l'uso da parte del modulo 3D
    ctx["pov_piste_points"] = points
    piste_name = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or T.get("selected_slope", "pista")
    )
    ctx["pov_piste_name"] = piste_name

    # 3) POV 2D statico con pydeck (se presente)
    if pdk is None:
        st.caption(
            f"POV 2D statico della pista {piste_name} (pydeck non disponibile, "
            "niente anteprima grafica)."
        )
        return ctx

    # Costruisco la polyline come [lon, lat, elev]
    path = [[p["lon"], p["lat"], p["elev"]] for p in points]

    line_layer = pdk.PathLayer(
        "pov_2d_pista",
        data=[{"path": path}],
        get_path="path",
        get_color=[255, 80, 60],
        width_scale=3,
        width_min_pixels=2,
        get_width=3,
    )

    # Punto di partenza (marker)
    start = points[0]
    start_layer = pdk.ScatterplotLayer(
        "pov_2d_start",
        data=[{"lon": start["lon"], "lat": start["lat"]}],
        get_position="[lon, lat]",
        get_color=[0, 255, 80],
        get_radius=20,
        radius_min_pixels=5,
    )

    # View centrata circa a metà pista
    mid = points[len(points) // 2]
    view_state = pdk.ViewState(
        longitude=mid["lon"],
        latitude=mid["lat"],
        zoom=12,
        pitch=0,
        bearing=0,
    )

    deck = pdk.Deck(
        layers=[line_layer, start_layer],
        initial_view_state=view_state,
        map_style=None,  # sfondo neutro (niente Mapbox)
        tooltip={"text": piste_name},
    )

    st.pydeck_chart(deck)
    st.caption(
        f"POV 2D statico della pista {piste_name} "
        "(vista dall'alto; il vero 3D è gestito dal modulo POV 3D)."
    )

    return ctx
