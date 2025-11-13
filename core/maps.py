# core/maps.py
# Mappa & piste (OSM / Overpass) per Telemark · Pro Wax & Tune

from __future__ import annotations
import math
from typing import List, Dict, Any, Optional

import requests
import streamlit as st

# Folium opzionale (l'app gira anche senza)
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

# ---------- Costanti ----------
UA = {
    "User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)",
    "Accept": "application/json",
}

# Proviamo piú endpoint Overpass
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

SEARCH_RADIUS_KM = 10        # raggio fisso del comprensorio
CLICK_MAX_DIST_KM = 0.4      # distanza massima dal click per considerare la pista “cliccata”


# ---------- Helper geografici ----------
def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due coordinate (formula di Haversine)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _line_length_km(coords: List[Dict[str, float]]) -> float:
    """Lunghezza approssimata (km) di una polyline (lat/lon)."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(coords)):
        p0, p1 = coords[i - 1], coords[i]
        total += _haversine(p0["lat"], p0["lon"], p1["lat"], p1["lon"])
    return total


def _nearest_point_distance_km(
    lat: float, lon: float, coords: List[Dict[str, float]]
) -> float:
    """Distanza minima (km) tra un punto e una polyline."""
    if not coords:
        return 999.0
    best = 999.0
    for p in coords:
        d = _haversine(lat, lon, p["lat"], p["lon"])
        if d < best:
            best = d
    return best


# ---------- Overpass ----------
def _overpass_request(query: str, timeout: int = 35) -> Dict[str, Any]:
    """Prova più endpoint Overpass in cascata."""
    last_err: Optional[Exception] = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data=query.encode("utf-8"), headers=UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pistes(lat: float, lon: float, dist_km: int = SEARCH_RADIUS_KM) -> List[Dict[str, Any]]:
    """
    Restituisce una lista di piste (ways/relations OSM) nel raggio dist_km:
    [
      {
        "id": 123,
        "osm_type": "way" | "relation",
        "name": "Pista ...",
        "difficulty": "red",
        "length_km": 1.8,
        "center_lat": ...,
        "center_lon": ...,
        "coords": [ {"lat":..,"lon":..}, ... ]
      },
      ...
    ]
    """
    radius_m = int(dist_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["piste:type"="downhill"];
      relation(around:{radius_m},{lat},{lon})["piste:type"="downhill"];
    );
    out tags geom center;
    """

    js = _overpass_request(query)
    elements = js.get("elements", []) or []

    pistes: List[Dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name") or tags.get("piste:name") or ""
        difficulty = tags.get("piste:difficulty", "")
        geom = el.get("geometry") or []
        if not geom:
            continue

        coords = [{"lat": g["lat"], "lon": g["lon"]} for g in geom]
        length_km = _line_length_km(coords)

        center = el.get("center") or {}
        if center:
            c_lat, c_lon = float(center["lat"]), float(center["lon"])
        else:
            c_lat = sum(p["lat"] for p in coords) / len(coords)
            c_lon = sum(p["lon"] for p in coords) / len(coords)

        pistes.append(
            dict(
                id=el.get("id"),
                osm_type=el.get("type", "way"),
                name=name,
                difficulty=difficulty,
                length_km=round(length_km, 2),
                center_lat=c_lat,
                center_lon=c_lon,
                coords=coords,
            )
        )

    pistes.sort(key=lambda p: (p["name"] or "zzzz", p["length_km"]))
    return pistes


# ---------- Label piste ----------
def _difficulty_label(diff: str, lang: str) -> str:
    if not diff:
        return ""
    if lang == "IT":
        it = {
            "green": "verde",
            "blue": "blu",
            "red": "rossa",
            "black": "nera",
        }
        return it.get(diff, diff)
    return diff


def _piste_option_label(p: Dict[str, Any], lang: str) -> str:
    name = p["name"] or (f"Pista {p['id']}")
    diff = _difficulty_label(p["difficulty"], lang)
    diff_part = f" · {diff}" if diff else ""
    len_part = f" · {p['length_km']:.1f} km" if p["length_km"] > 0 else ""
    return f"{name}{diff_part}{len_part}"


def _apply_selection_to_ctx(p: Dict[str, Any], ctx: Dict[str, Any]):
    """Quando seleziono una pista, aggiorno ctx e session_state per DEM/meteo."""
    base_label = ctx.get("place_label", "Località")
    main_name = base_label.split("—")[0].strip()
    new_label = f"{main_name} · {p['name'] or 'pista'}"

    ctx_lat = float(p["center_lat"])
    ctx_lon = float(p["center_lon"])

    ctx["lat"] = ctx_lat
    ctx["lon"] = ctx_lon
    ctx["place_label"] = new_label

    st.session_state["lat"] = ctx_lat
    st.session_state["lon"] = ctx_lon
    st.session_state["place_label"] = new_label


# ---------- RENDER PRINCIPALE ----------
def render_map(T, ctx: Dict[str, Any]):
    """
    Pannello "Mappa & piste".
    Usa ctx = {"lat","lon","place_label","iso2","lang",...}
    e aggiorna ctx / st.session_state quando l'utente seleziona una pista
    (da selectbox o cliccando direttamente sulla mappa).
    """
    lang = ctx.get("lang", "IT")
    lat = float(ctx.get("lat", 45.831))
    lon = float(ctx.get("lon", 7.730))
    place_label = ctx.get("place_label", "Località")

    st.markdown("### 4) Mappa & piste")

    show_pistes = st.checkbox("Mostra piste sulla mappa", value=True, key="show_pistes")

    # ---------- Fetch piste ----------
    pistes: List[Dict[str, Any]] = []
    if show_pistes:
        try:
            with st.spinner("Carico le piste da OpenStreetMap / Overpass…"):
                pistes = fetch_pistes(lat, lon)
        except requests.exceptions.Timeout:
            st.error("Errore caricando le piste (OSM/Overpass): timeout del servizio.")
        except requests.exceptions.HTTPError as e:
            st.error(f"Errore caricando le piste (OSM/Overpass): {e}")
        except Exception as e:
            st.error(f"Errore imprevisto caricando le piste (OSM/Overpass): {e}")

    if show_pistes and not pistes:
        st.info("Nessuna pista trovata in questo comprensorio (OSM/Overpass).")

    # ---------- Ricerca / selezione pista ----------
    selected_piste: Optional[Dict[str, Any]] = None

    if pistes:
        search_txt = st.text_input(
            "Cerca pista per nome",
            value=st.session_state.get("piste_search", ""),
            key="piste_search",
            placeholder="es. Del Bosco, Bettaforca, Sarezza…",
        ).strip()

        filtered: List[Dict[str, Any]] = []
        for p in pistes:
            name_norm = (p["name"] or "").lower()
            if not search_txt or search_txt.lower() in name_norm:
                filtered.append(p)

        if not filtered:
            st.warning("Nessuna pista corrisponde alla ricerca. Mostro l'elenco completo.")
            filtered = pistes

        options = [_piste_option_label(p, lang) for p in filtered]
        label_to_piste = {lbl: p for lbl, p in zip(options, filtered)}

        default_label = st.session_state.get("piste_select")
        if default_label not in options and options:
            default_label = options[0]

        chosen_label = st.selectbox(
            "Seleziona pista",
            options=options,
            index=options.index(default_label) if default_label in options else 0,
            key="piste_select",
        ) if options else None

        if chosen_label:
            selected_piste = label_to_piste.get(chosen_label)
            if selected_piste:
                _apply_selection_to_ctx(selected_piste, ctx)

    # ---------- Mappa ----------
    if not HAS_FOLIUM:
        st.info("Modulo mappa avanzata richiede 'folium' e 'streamlit-folium' installati.")
        return

    map_lat = float(ctx.get("lat", lat))
    map_lon = float(ctx.get("lon", lon))

    m = folium.Map(
        location=[map_lat, map_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )

    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        name="OSM",
        attr="© OpenStreetMap contributors",
        overlay=False,
        control=True,
    ).add_to(m)

    # marker della località / centro
    folium.Marker(
        [map_lat, map_lon],
        tooltip=ctx.get("place_label", place_label),
        icon=folium.Icon(color="lightgray", icon="info-sign"),
    ).add_to(m)

    # disegna piste
    selected_id = selected_piste["id"] if selected_piste else None
    if pistes:
        for p in pistes:
            coords = [(c["lat"], c["lon"]) for c in p["coords"]]
            if not coords:
                continue

            color = "#ff4b4b" if p["id"] == selected_id else "#3388ff"
            weight = 5 if p["id"] == selected_id else 3
            name = p["name"] or f"Pista {p['id']}"
            diff = _difficulty_label(p["difficulty"], lang)
            diff_txt = f" ({diff})" if diff else ""
            popup_txt = f"{name}{diff_txt} · {p['length_km']:.1f} km"

            folium.PolyLine(
                locations=coords,
                color=color,
                weight=weight,
                opacity=0.95,
                tooltip=popup_txt,
            ).add_to(m)

    # click → seleziona pista più vicina (ma solo se vicino alla linea)
    map_key = f"map_{round(map_lat,5)}_{round(map_lon,5)}"
    out = st_folium(
        m,
        height=420,
        use_container_width=True,
        key=map_key,
        returned_objects=["last_clicked"],
    )

    if pistes and out:
        click = (out or {}).get("last_clicked") or {}
        if click:
            click_lat = float(click.get("lat"))
            click_lon = float(click.get("lng"))
            pair = (round(click_lat, 5), round(click_lon, 5))
            last_pair = st.session_state.get("_last_piste_click")

            if pair != last_pair:
                st.session_state["_last_piste_click"] = pair

                best_p, best_d = None, 999.0
                for p in pistes:
                    d = _nearest_point_distance_km(click_lat, click_lon, p["coords"])
                    if d < best_d:
                        best_p, best_d = p, d

                if best_p is not None and best_d <= CLICK_MAX_DIST_KM:
                    lbl = _piste_option_label(best_p, lang)
                    st.session_state["piste_select"] = lbl
                    _apply_selection_to_ctx(best_p, ctx)
                    st.rerun()
