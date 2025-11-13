# core/maps.py
# Mappa & piste (OSM / Overpass) per Telemark · Pro Wax & Tune

from __future__ import annotations

import math
from typing import List, Dict, Any

import requests
import streamlit as st

# -------------------------------------------------------------------
# Folium opzionale (l'app gira comunque anche senza)
# -------------------------------------------------------------------
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium

    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

# -------------------------------------------------------------------
# Costanti & endpoint Overpass
# -------------------------------------------------------------------
UA = {
    "User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)",
    "Accept": "application/json",
}

# Più endpoint: proviamo in ordine finché uno risponde
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

# Raggi dinamici (km): locale → comprensorio → zona allargata
# 18 km da Champoluc resta ancora entro Monterosa, senza arrivare a Zermatt.
SEARCH_RADII_KM = [7, 12, 18]


# -------------------------------------------------------------------
# Helper geografici
# -------------------------------------------------------------------
def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in km tra due coordinate WGS84."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _line_length_km(coords: List[Dict[str, float]]) -> float:
    """Lunghezza approssimata (km) di una polyline (lista di dict lat/lon)."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(coords)):
        p0, p1 = coords[i - 1], coords[i]
        total += _haversine(p0["lat"], p0["lon"], p1["lat"], p1["lon"])
    return total


# -------------------------------------------------------------------
# Overpass: esegui query con fallback su più endpoint
# -------------------------------------------------------------------
def _run_overpass_query(query: str) -> Dict[str, Any]:
    last_error: Exception | None = None
    for url in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                url, data=query.encode("utf-8"), headers=UA, timeout=35
            )
            r.raise_for_status()
            return r.json() or {}
        except Exception as e:
            last_error = e
            continue
    # se tutti gli endpoint falliscono, propaghiamo l'ultimo errore
    if last_error:
        raise last_error
    return {}


# -------------------------------------------------------------------
# Fetch piste da Overpass (con raggio dinamico)
# -------------------------------------------------------------------
def _fetch_raw_pistes(lat: float, lon: float, dist_km: int) -> List[Dict[str, Any]]:
    """
    Scarica le piste 'downhill' nel raggio dist_km (km) intorno a (lat,lon)
    da OSM/Overpass e ritorna una lista di dict normalizzati.
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

    data = _run_overpass_query(query)
    elements = data.get("elements", []) or []

    pistes: List[Dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags", {}) or {}

        # accettiamo solo downhill (ignora nordic, ski route, ecc.)
        piste_type = tags.get("piste:type") or tags.get("piste:type:1") or ""
        if piste_type != "downhill":
            continue

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

        name = tags.get("name") or tags.get("piste:name") or ""
        difficulty = tags.get("piste:difficulty", "")

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

    # ordina per nome (vuoti in fondo) e poi per lunghezza
    pistes.sort(key=lambda p: (p["name"] or "zzzz", p["length_km"]))
    return pistes


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pistes(lat: float, lon: float) -> List[Dict[str, Any]]:
    """
    Restituisce le piste per un dato resort, usando un raggio dinamico:
    1) 7 km  (locale)
    2) 12 km (comprensorio)
    3) 18 km (zona allargata, ma senza arrivare ai comprensori vicini tipo Zermatt)
    """
    for dist_km in SEARCH_RADII_KM:
        try:
            pistes = _fetch_raw_pistes(lat, lon, dist_km)
            if pistes:
                return pistes
        except Exception:
            # tenta il raggio successivo / endpoint successivo
            continue
    return []


# -------------------------------------------------------------------
# Label / difficoltà
# -------------------------------------------------------------------
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
    name = p["name"] or f"Pista {p['id']}"
    diff = _difficulty_label(p.get("difficulty", ""), lang)
    diff_part = f" · {diff}" if diff else ""
    len_part = f" · {p['length_km']:.1f} km" if p.get("length_km", 0) > 0 else ""
    return f"{name}{diff_part}{len_part}"


# -------------------------------------------------------------------
# Render principale
# -------------------------------------------------------------------
def render_map(T, ctx: Dict[str, Any]):
    """
    Pannello "Mappa & piste".
    Usa ctx = {"lat","lon","place_label","iso2","lang",...}
    e aggiorna ctx / st.session_state quando l'utente seleziona una pista.
    """
    lang = ctx.get("lang", "IT")
    lat = float(ctx.get("lat", 45.831))
    lon = float(ctx.get("lon", 7.730))
    place_label = ctx.get("place_label", "Località")

    st.markdown("### 4) Mappa & piste")

    show_pistes = st.checkbox(
        "Mostra piste sulla mappa", value=True, key="show_pistes"
    )

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

    # ---------------------------------------------------------------
    # Ricerca / selezione pista
    # ---------------------------------------------------------------
    selected_piste = None
    if pistes:
        search_txt = st.text_input(
            "Cerca pista per nome",
            value="",
            key="piste_search",
            placeholder="es. Del Bosco, Bettaforca, Sarezza…",
        ).strip()

        # filtra la lista per nome
        filtered: List[Dict[str, Any]] = []
        for p in pistes:
            name_norm = (p.get("name") or "").lower()
            if not search_txt or search_txt.lower() in name_norm:
                filtered.append(p)

        if not filtered:
            st.warning(
                "Nessuna pista corrisponde alla ricerca. Mostro l'elenco completo."
            )
            filtered = pistes

        options = [_piste_option_label(p, lang) for p in filtered]
        label_to_piste = {label: p for label, p in zip(options, filtered)}

        chosen_label = (
            st.selectbox(
                "Seleziona pista",
                options=options,
                index=0 if options else None,
                key="piste_select",
            )
            if options
            else None
        )

        if chosen_label:
            selected_piste = label_to_piste.get(chosen_label)
            if selected_piste:
                # aggiorna ctx e session sulla pista scelta → DEM/meteo useranno questa posizione
                ctx_lat = float(selected_piste["center_lat"])
                ctx_lon = float(selected_piste["center_lon"])
                ctx_label = (
                    f"{place_label.split('—')[0].strip()} · "
                    f"{selected_piste['name'] or 'pista'}"
                )

                ctx["lat"] = ctx_lat
                ctx["lon"] = ctx_lon
                ctx["place_label"] = ctx_label

                st.session_state["lat"] = ctx_lat
                st.session_state["lon"] = ctx_lon
                st.session_state["place_label"] = ctx_label
                # molto importante: aggiorniamo anche il ctx condiviso
                st.session_state["_ctx"] = ctx

    # ---------------------------------------------------------------
    # Mappa
    # ---------------------------------------------------------------
    if not HAS_FOLIUM:
        st.info(
            "Modulo mappa avanzata richiede i pacchetti "
            "`folium` e `streamlit-folium` installati."
        )
        return

    # centro mappa: se c'è una pista selezionata, usa il suo centro
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

    # marker della località / centro (può coincidere con la pista selezionata)
    folium.Marker(
        [map_lat, map_lon],
        tooltip=ctx.get("place_label", place_label),
        icon=folium.Icon(color="lightgray", icon="info-sign"),
    ).add_to(m)

    # disegna piste se presenti
    if pistes:
        selected_id = selected_piste["id"] if selected_piste else None

        for p in pistes:
            coords = [(c["lat"], c["lon"]) for c in p.get("coords", [])]
            if not coords:
                continue

            is_selected = p["id"] == selected_id
            color = "#ff4b4b" if is_selected else "#3388ff"
            weight = 5 if is_selected else 3

            name = p["name"] or f"Pista {p['id']}"
            diff = _difficulty_label(p.get("difficulty", ""), lang)
            diff_txt = f" ({diff})" if diff else ""
            popup_txt = f"{name}{diff_txt} · {p['length_km']:.1f} km"

            folium.PolyLine(
                locations=coords,
                color=color,
                weight=weight,
                opacity=0.95,
                tooltip=popup_txt,
            ).add_to(m)

    # mostra mappa
    st_folium(
        m,
        height=420,
        use_container_width=True,
        key=f"map_{round(map_lat,5)}_{round(map_lon,5)}",
    )
