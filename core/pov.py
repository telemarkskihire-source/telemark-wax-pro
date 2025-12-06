# core/pov.py
# Vista 3D (POV) di una pista selezionata
#
# - Legge dal contesto:
#     · ctx["selected_piste_name"]   → nome pista scelto in maps.py
#     · ctx["base_lat"], ["base_lon"] o ctx["lat"], ["lon"] come centro
# - Riusa la funzione _fetch_downhill_pistes di core.maps per recuperare
#   i segmenti OSM (piste:type=downhill).
# - Trova tutti i segmenti con lo stesso nome, li unisce in un'unica traccia
#   ordinata (in modo semplice).
# - Mostra una vista 3D “tipo POV” con pydeck:
#     · BASEMAP SATELLITARE (se è presente MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN)
#     · linea rossa della pista
#     · marker START (verde) e FINISH (rosso)
#     · camera molto inclinata e zoomata → effetto più realistico
#
# FUNZIONI ESPORTE:
#   - render_pov_3d(ctx)        → nuova API
#   - render_pov_extract(...)   → wrapper retro-compatibile per la vecchia app
#
# La vecchia chiamata:
#   ctx = render_pov_extract(T, ctx)
# continuerà a funzionare grazie al wrapper.

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

import math
import os

import streamlit as st
import pydeck as pdk

try:
    # riusiamo la funzione del modulo mappe per non duplicare Overpass
    from core.maps import _fetch_downhill_pistes
except Exception:  # pragma: no cover - fallback se maps non è disponibile
    _fetch_downhill_pistes = None  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Configurazione Mapbox per avere il SATELLITE
# ----------------------------------------------------------------------
def _configure_mapbox_token() -> None:
    """
    Imposta la API key Mapbox per pydeck, se disponibile.
    Cerca nell'ordine:
      - st.secrets["MAPBOX_API_KEY"]
      - st.secrets["MAPBOX_ACCESS_TOKEN"]
      - variabili d'ambiente MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN
    """
    token = None

    # st.secrets (se disponibile)
    try:
        if "MAPBOX_API_KEY" in st.secrets:
            token = st.secrets["MAPBOX_API_KEY"]
        elif "MAPBOX_ACCESS_TOKEN" in st.secrets:
            token = st.secrets["MAPBOX_ACCESS_TOKEN"]
    except Exception:
        pass

    # env vars
    if not token:
        token = (
            os.environ.get("MAPBOX_API_KEY")
            or os.environ.get("MAPBOX_ACCESS_TOKEN")
        )

    if token:
        pdk.settings.mapbox_api_key = token
    else:
        # nessun errore duro, ma avvisiamo che senza token la resa sarà scarsa
        st.info(
            "Per una vista 3D più realistica (satellite), configura "
            "`MAPBOX_API_KEY` o `MAPBOX_ACCESS_TOKEN` su Streamlit."
        )


# ----------------------------------------------------------------------
# Utility: distanza in metri (per ordinare i segmenti)
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
    e chiama _fetch_downhill_pistes di core.maps.

    Se non trova nulla, ritorna None.
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

    # raggio 5 km attorno al centro
    _, polylines, names = _fetch_downhill_pistes(base_lat, base_lon, radius_km=5.0)

    # prendo tutti i segmenti che hanno esattamente quel nome
    segments: List[List[Tuple[float, float]]] = [
        coords
        for coords, nm in zip(polylines, names)
        if nm == piste_name and coords
    ]

    if not segments:
        return None

    if len(segments) == 1:
        # caso semplice: un solo segmento
        return segments[0]

    # Se ci sono più segmenti con lo stesso nome (pista spezzata),
    # li uniamo in modo semplice: partiamo dal segmento più lungo e
    # aggiungiamo ogni volta il segmento il cui inizio è più vicino alla fine.
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
# Render POV 3D con pydeck (NUOVA API)
# ----------------------------------------------------------------------
def render_pov_3d(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Renderizza una vista 3D (POV) della pista selezionata.

    Richiede:
      - ctx["selected_piste_name"] impostato (da maps.py)
      - core.maps._fetch_downhill_pistes disponibile

    Se non ci sono dati sufficienti, mostra un messaggio informativo.
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

    # Configuriamo Mapbox per avere il satellite se possibile
    _configure_mapbox_token()

    # centro della pista per la camera
    avg_lat = sum(lat for lat, _ in coords) / len(coords)
    avg_lon = sum(lon for _, lon in coords) / len(coords)

    # punti di start/finish (inizio e fine della traccia)
    start_lat, start_lon = coords[0]
    finish_lat, finish_lon = coords[-1]

    # convertiamo la traccia in formato [lon, lat] per pydeck
    path_lonlat: List[List[float]] = [[lon, lat] for lat, lon in coords]

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
            "position": [start_lon, start_lat],
        },
        {
            "type": "finish",
            "name": f"{piste_name} · FINISH",
            "position": [finish_lon, finish_lat],
        },
    ]

    # View "POV": camera molto inclinata e zoomata
    view_state = pdk.ViewState(
        latitude=avg_lat,
        longitude=avg_lon,
        zoom=15.5,   # un filo più vicino
        pitch=70,    # più inclinato → effetto più "discesa"
        bearing=-35, # leggera rotazione
    )

    # Layer pista
    path_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 70, 40],
        width_scale=6,
        width_min_pixels=4,
    )

    # Layer start/finish
    points_layer = pdk.Layer(
        "ScatterplotLayer",
        data=points_data,
        get_position="position",
        get_radius=12,
        get_fill_color=[
            "255 * (type == 'finish')",
            "255 * (type == 'start')",
            0,
        ],
        pickable=True,
    )

    # Deck completo
    deck = pdk.Deck(
        layers=[path_layer, points_layer],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/satellite-v9",
        tooltip={"text": "{name}"},
    )

    st.subheader("🎥 POV pista (beta)")

    st.pydeck_chart(deck)

    st.caption(
        f"POV 3D della pista **{piste_name}** "
        "(satellite + start/finish; puoi ruotare e zoomare con le dita o il mouse)."
    )

    # Salviamo la traccia nel contesto per usi futuri (profilo altimetrico, animazione, ecc.)
    ctx["pov_coords"] = coords

    return ctx


# ----------------------------------------------------------------------
# Wrapper retro-compatibile: render_pov_extract
# ----------------------------------------------------------------------
def render_pov_extract(*args, **kwargs) -> Dict[str, Any]:
    """
    Wrapper di compatibilità per il vecchio nome `render_pov_extract`.

    Accetta sia:
      - render_pov_extract(ctx)
      - render_pov_extract(T, ctx)
      - render_pov_extract(ctx=ctx)

    e inoltra sempre a render_pov_3d(ctx).
    """
    ctx: Optional[Dict[str, Any]] = None

    # pattern più comuni:
    #   (ctx,)
    #   (T, ctx)
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
