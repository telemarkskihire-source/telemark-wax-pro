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
#     · BASEMAP SATELLITARE Mapbox (se è presente una API key)
#     · linea rossa 3D della pista (con quota finta che scende)
#     · marker START (verde) e FINISH (rosso)
#     · camera molto inclinata e zoomata → effetto “discesa”
#
# FUNZIONI ESPORTE:
#   - render_pov_3d(ctx)        → nuova API
#   - render_pov_extract(...)   → wrapper retro-compatibile per la vecchia app

from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional
from collections.abc import Mapping

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
# Configurazione Mapbox per avere il SATELLITE (lettura robusta)
# ----------------------------------------------------------------------
def _configure_mapbox_token() -> None:
    """
    Imposta la API key Mapbox per pydeck, se disponibile.

    Cerca nell'ordine:
      1) se pdk.settings.mapbox_api_key è già settato → non fa nulla
      2) st.secrets (convertito in dict):
         - chiavi "MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN", "MAPBOX_TOKEN"
           e varianti minuscole
         - valori annidati che sembrano un token Mapbox (es. iniziano con "pk.")
      3) variabili d'ambiente:
         - MAPBOX_API_KEY, MAPBOX_ACCESS_TOKEN, MAPBOX_TOKEN

    Mostra un messaggio informativo SOLO se, dopo tutti i tentativi,
    non trova nessuna API key.
    """
    # se è già configurato da qualche altra parte, non tocchiamo niente
    if getattr(pdk.settings, "mapbox_api_key", None):
        return

    token: Optional[str] = None

    # --- 1) st.secrets: chiavi dirette + oggetto completo convertito in dict ---
    secrets_dict: Dict[str, Any] = {}
    try:
        if hasattr(st.secrets, "to_dict"):
            secrets_dict = st.secrets.to_dict()  # type: ignore[assignment]
        else:
            secrets_dict = dict(st.secrets)  # type: ignore[arg-type]

        direct_keys = [
            "MAPBOX_API_KEY",
            "MAPBOX_ACCESS_TOKEN",
            "MAPBOX_TOKEN",
            "mapbox_api_key",
            "mapbox_access_token",
            "mapbox_token",
        ]
        for key in direct_keys:
            if key in secrets_dict:
                val = secrets_dict[key]
                if isinstance(val, str) and val.strip():
                    token = val.strip()
                    break
    except Exception:
        secrets_dict = {}

    # --- 2) st.secrets: sezioni nidificate / valori che "assomigliano" a un token Mapbox ---
    if not token and secrets_dict:

        def _search_in_obj(obj: Any) -> Optional[str]:
            # stringa diretta
            if isinstance(obj, str):
                v = obj.strip()
                if v.startswith("pk."):
                    return v
                if len(v) > 30:
                    return v
                return None
            # mapping generico (dict, Secrets, ecc.)
            if isinstance(obj, Mapping):
                for v in obj.values():
                    found = _search_in_obj(v)
                    if found:
                        return found
            # liste/tuple
            if isinstance(obj, (list, tuple)):
                for v in obj:
                    found = _search_in_obj(v)
                    if found:
                        return found
            return None

        candidate = _search_in_obj(secrets_dict)
        if candidate:
            token = candidate

    # --- 3) variabili d'ambiente ---
    if not token:
        env_keys = ["MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN", "MAPBOX_TOKEN"]
        for key in env_keys:
            val = os.environ.get(key)
            if isinstance(val, str) and val.strip():
                token = val.strip()
                break

    # --- 4) se finalmente abbiamo un token, configuriamo pydeck ---
    if token:
        pdk.settings.mapbox_api_key = token
    else:
        st.info(
            "Per una vista 3D più realistica (satellite), configura una API key "
            "Mapbox (`MAPBOX_API_KEY`) in *Secrets* o come variabile d'ambiente."
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

    # --- costruiamo un path 3D: lon, lat, alt ---
    # quota finta: partiamo alto alla partenza e scendiamo verso il traguardo
    n = len(coords)
    max_drop_m = 250.0  # dislivello "virtuale" in metri per l'effetto 3D
    path_lonlat: List[List[float]] = []
    for i, (lat, lon) in enumerate(coords):
        t = i / max(1, n - 1)  # 0 → 1
        alt = max_drop_m * (1.0 - t)  # partenza più alta, arrivo più basso
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

    # View "POV": camera molto inclinata e zoomata
    view_state = pdk.ViewState(
        latitude=avg_lat,
        longitude=avg_lon,
        zoom=14.8,   # un po' più lontano per vedere la discesa 3D
        pitch=70,    # inclinato → effetto "discesa"
        bearing=-35, # leggera rotazione
    )

    # Layer pista 3D
    path_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 70, 40],
        width_scale=6,
        width_min_pixels=4,
        # usa la terza coordinata (alt) per l'elevazione
        get_width=4,
    )

    # Layer start/finish
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

    # Deck completo
    deck = pdk.Deck(
        layers=[path_layer, points_layer],
        initial_view_state=view_state,
        map_provider="mapbox",
        map_style="mapbox://styles/mapbox/satellite-streets-v12",
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
