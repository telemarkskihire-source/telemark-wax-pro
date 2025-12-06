# core/pov.py
# Vista 3D (POV) di una pista selezionata
#
# - ctx["selected_piste_name"]   → nome pista scelto in maps.py
# - ctx["base_lat"], ["base_lon"] o ctx["lat"], ["lon"] come centro
# - Riusa core.maps._fetch_downhill_pistes per i segmenti OSM
# - Unisce i segmenti della stessa pista
# - Mostra:
#     · basemap satellitare Mapbox (se la key funziona)
#     · linea rossa 3D (dislivello finto ma coerente)
#     · START/FINISH
# - Espone:
#     · render_pov_3d(ctx)
#     · render_pov_extract(...) (compatibilità vecchio nome)

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import os

import streamlit as st
import pydeck as pdk

try:
    from core.maps import _fetch_downhill_pistes
except Exception:  # pragma: no cover
    _fetch_downhill_pistes = None  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Mapbox token: lettura semplice + forzatura su Deck(mapbox_key=...)
# ----------------------------------------------------------------------
def _get_mapbox_token() -> Optional[str]:
    """Ritorna il token Mapbox da usare, se disponibile."""

    # 1) Secrets con nomi "classici"
    try:
        for key in (
            "MAPBOX_API_KEY",
            "MAPBOX_ACCESS_TOKEN",
            "MAPBOX_TOKEN",
            "mapbox_api_key",
            "mapbox_access_token",
            "mapbox_token",
        ):
            if key in st.secrets:
                val = st.secrets[key]
                if isinstance(val, str) and val.strip():
                    return val.strip()
    except Exception:
        pass

    # 2) Variabile d'ambiente
    for key in ("MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN", "MAPBOX_TOKEN"):
        val = os.environ.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return None


# ----------------------------------------------------------------------
# Utility: distanza in metri
# ----------------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# ----------------------------------------------------------------------
# Recupero e costruzione traccia per la pista selezionata
# ----------------------------------------------------------------------
def _get_selected_piste_coords(ctx: Dict[str, Any]) -> Optional[List[Tuple[float, float]]]:
    """
    Ritorna una lista ordinata di (lat, lon) per la pista selezionata.

    Usa:
      - ctx["selected_piste_name"]
      - ctx["base_lat"], ctx["base_lon"] oppure ctx["lat"], ctx["lon"]
      - core.maps._fetch_downhill_pistes
    """
    piste_name = ctx.get("selected_piste_name")
    if not isinstance(piste_name, str) or not piste_name.strip():
        return None

    if _fetch_downhill_pistes is None:
        return None

    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))

    _, polylines, names = _fetch_downhill_pistes(base_lat, base_lon, radius_km=5.0)

    segments: List[List[Tuple[float, float]]] = [
        coords
        for coords, nm in zip(polylines, names)
        if nm == piste_name and coords
    ]

    if not segments:
        return None

    if len(segments) == 1:
        return segments[0]

    # Unione dei segmenti (approccio greedy semplice)
    segments = sorted(segments, key=len, reverse=True)
    track: List[Tuple[float, float]] = list(segments[0])
    used = {0}

    while len(used) < len(segments):
        last_lat, last_lon = track[-1]
        best_idx = None
        best_dist = float("inf")
        for idx, seg in enumerate(segments):
            if idx in used:
                continue
            start_lat, start_lon = seg[0]
            d = _dist_m(last_lat, last_lon, start_lat, start_lon)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        if best_idx is None:
            break
        used.add(best_idx)
        track.extend(segments[best_idx])

    return track


# ----------------------------------------------------------------------
# Render POV 3D con pydeck
# ----------------------------------------------------------------------
def render_pov_3d(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Renderizza una vista 3D (POV) della pista selezionata.

    Richiede:
      - ctx["selected_piste_name"] impostato (da maps.py)
      - core.maps._fetch_downhill_pistes disponibile
    """
    piste_name = ctx.get("selected_piste_name")
    if not isinstance(piste_name, str) or not piste_name.strip():
        st.info("Seleziona prima una pista sulla mappa per vedere la vista 3D.")
        return ctx

    if _fetch_downhill_pistes is None:
        st.error(
            "Modulo mappe non disponibile per il POV 3D "
            "(core.maps._fetch_downhill_pistes mancante)."
        )
        return ctx

    coords = _get_selected_piste_coords(ctx)
    if not coords or len(coords) < 2:
        st.warning(
            f"Non sono riuscito a ricostruire il tracciato per la pista "
            f"**{piste_name}**. Prova a zoomare sulla zona e riselezionarla."
        )
        return ctx

    # Mapbox token
    token = _get_mapbox_token()
    if token:
    if token:
        # forza uso Mapbox satellite (la key è già in pdk.settings.mapbox_api_key)
        deck_kwargs.update(
            map_provider="mapbox",
            map_style="mapbox://styles/mapbox/satellite-v9",
        )
    else:
        # fallback minimale (senza sfondo)
        deck_kwargs.update(
            map_provider=None,
            map_style=None,
        )

    # piccolo debug visivo (puoi toglierlo dopo)
    st.caption(
        f"Mapbox key attiva: {bool(token)} "
        f"(prefisso: {token[:3] if token else '---'})"
    )

    # centro della pista per la camera
    avg_lat = sum(lat for lat, _ in coords) / len(coords)
    avg_lon = sum(lon for _, lon in coords) / len(coords)

    # start/finish
    start_lat, start_lon = coords[0]
    finish_lat, finish_lon = coords[-1]

    # --- path 3D: [lon, lat, alt] con dislivello finto ---
    n = len(coords)
    max_drop_m = 250.0
    path_lonlat: List[List[float]] = []
    for i, (lat, lon) in enumerate(coords):
        t = i / max(1, n - 1)  # 0 → 1
        alt = max_drop_m * (1.0 - t)  # alto → basso
        path_lonlat.append([lon, lat, alt])

    path_data = [
        {
            "name": piste_name,
            "path": path_lonlat,
        }
    ]

    points_data = [
        {
            "type": "start",
            "name": f"{piste_name} · START",
            "position": [start_lon, start_lat, max_drop_m],
        },
        {
            "type": "finish",
            "name": f"{piste_name} · FINISH",
            "position": [finish_lon, finish_lat, 0.0],
        },
    ]

    view_state = pdk.ViewState(
        latitude=avg_lat,
        longitude=avg_lon,
        zoom=14.8,
        pitch=70,
        bearing=-35,
    )

    path_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 70, 40],
        width_scale=6,
        width_min_pixels=4,
    )

    points_layer = pdk.Layer(
        "ScatterplotLayer",
        data=points_data,
        get_position="position",
        get_radius=20,
        get_fill_color=[
            "255 * (type == 'finish')",
            "255 * (type == 'start')",
            0,
        ],
        pickable=True,
    )

    deck_kwargs: Dict[str, Any] = dict(
        layers=[path_layer, points_layer],
        initial_view_state=view_state,
        tooltip={"text": "{name}"},
    )

    if token:
        # forza uso Mapbox satellite
        deck_kwargs.update(
            map_provider="mapbox",
            map_style="mapbox://styles/mapbox/satellite-v9",
            mapbox_key=token,
        )
    else:
        # fallback minimale (senza sfondo) – ma dovrebbe essere il tuo caso solo se manca la key
        deck_kwargs.update(
            map_provider=None,
            map_style=None,
        )

    deck = pdk.Deck(**deck_kwargs)

    st.subheader("🎥 POV pista (beta)")
    st.pydeck_chart(deck)

    st.caption(
        f"POV 3D della pista **{piste_name}** "
        "(puoi ruotare e zoomare con le dita o il mouse)."
    )

    ctx["pov_coords"] = coords
    return ctx


# ----------------------------------------------------------------------
# Wrapper retro-compatibile
# ----------------------------------------------------------------------
def render_pov_extract(*args, **kwargs) -> Dict[str, Any]:
    """
    Compatibilità col vecchio nome `render_pov_extract`.

    Accetta:
      - render_pov_extract(ctx)
      - render_pov_extract(T, ctx)
      - render_pov_extract(ctx=ctx)
    """
    ctx: Optional[Dict[str, Any]] = None

    if args:
        if len(args) == 1:
            ctx = args[0]
        elif len(args) >= 2:
            ctx = args[1]

    if ctx is None:
        ctx = kwargs.get("ctx")

    if ctx is None:
        ctx = {}

    return render_pov_3d(ctx)
