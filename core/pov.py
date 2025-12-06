# core/pov.py
# POV 2D + estrazione pista per Telemark · Pro Wax & Tune
#
# - Estrae la pista selezionata dal contesto (ctx)
# - Salva i punti in ctx["pov_piste_points"] + ctx["pov_piste_name"]
# - Prova a mostrare un POV 2D molto semplice con pydeck
#   SENZA usare PathLayer (compatibile con pydeck "ridotto")

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

try:
    import pydeck as pdk  # tipo: ignore
except Exception:  # pydeck non disponibile
    pdk = None  # type: ignore[assignment]


# ---------------------------------------------------------
# Normalizzazione punti
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# POV 2D + estrazione
# ---------------------------------------------------------
def render_pov_extract(T: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estrae la pista selezionata dal ctx, la salva nei campi POV e,
    se possibile, mostra un POV 2D molto semplice.

    Non usa PathLayer (compatibile con pydeck ridotto).
    """
    # 1) Trovo i punti della pista
    points = _guess_piste_points_from_ctx(ctx)
    if not points:
        st.info("POV non disponibile per questa località (nessuna pista selezionata).")
        return ctx

    # 2) Salvo nel contesto per il modulo 3D
    ctx["pov_piste_points"] = points
    piste_name = (
        ctx.get("pov_piste_name")
        or ctx.get("selected_piste_name")
        or T.get("selected_slope", "pista")
    )
    ctx["pov_piste_name"] = piste_name

    # 3) Se pydeck non c'è o è troppo limitato → niente grafica, solo testo
    if pdk is None or not hasattr(pdk, "Deck"):
        st.caption(
            f"POV 2D della pista {piste_name}: "
            "pydeck non disponibile / troppo limitato, uso solo dati interni."
        )
        return ctx

    try:
        # Prepariamo un semplice scatter dei punti (nessun PathLayer)
        scatter_data = [
            {"lat": p["lat"], "lon": p["lon"]} for p in points
        ]

        # Vista centrata a metà pista
        mid = points[len(points) // 2]
        view_state = pdk.ViewState(
            latitude=float(mid["lat"]),
            longitude=float(mid["lon"]),
            zoom=12,
            pitch=0,
            bearing=0,
        )

        # ScatterplotLayer: se la classe non esiste, usiamo la forma generica
        if hasattr(pdk, "ScatterplotLayer"):
            scatter_layer = pdk.ScatterplotLayer(
                "pov2d_points",
                data=scatter_data,
                get_position="[lon, lat]",
                get_radius=25,
                get_fill_color=[255, 80, 60],
                pickable=False,
            )
        else:
            scatter_layer = pdk.Layer(
                "ScatterplotLayer",
                data=scatter_data,
                get_position="[lon, lat]",
                get_radius=25,
                get_fill_color=[255, 80, 60],
                pickable=False,
            )

        deck = pdk.Deck(
            layers=[scatter_layer],
            initial_view_state=view_state,
            map_style=None,  # sfondo neutro
            tooltip={"text": piste_name},
        )

        st.pydeck_chart(deck)
        st.caption(
            f"POV 2D semplificato della pista {piste_name} "
            "(solo punti; il vero profilo 3D è gestito dal modulo POV 3D)."
        )

    except Exception:
        # Anche se pydeck è mezzo rotto, NON facciamo crashare l'app
        st.caption(
            f"POV 2D della pista {piste_name}: "
            "pydeck in questa installazione non supporta i layer necessari, "
            "uso solo i dati interni per il POV 3D."
        )

    return ctx
