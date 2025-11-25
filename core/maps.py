# core/maps.py
# Mappa & piste (OSM / Overpass) per Telemark · Pro Wax & Tune
# Versione semplificata: solo piste con 'piste:type'

from __future__ import annotations

import math
from typing import List, Dict, Any

import requests
import streamlit as st

# Folium opzionale
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

UA = {
    "User-Agent": "telemark-wax-pro/2.0 (+https://telemarkskihire.com)",
    "Accept": "application/json",
}

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

BASE_RADIUS_KM = 10
FALLBACK_RADIUS_KM = 25


# ---------- Helper geografici ----------
def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _line_length_km(coords: List[Dict[str, float]]) -> float:
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(coords)):
        p0, p1 = coords[i - 1], coords[i]
        total += _haversine(p0["lat"], p0["lon"], p1["lat"], p1["lon"])
    return total


def _point_distance_km(lat1, lon1, lat2, lon2) -> float:
    return _haversine(lat1, lon1, lat2, lon2)


# ---------- Overpass ----------

def _overpass_query(lat: float, lon: float, dist_km: int) -> List[Dict[str, Any]]:
    radius_m = int(dist_km * 1000)
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["piste:type"];
      relation(around:{radius_m},{lat},{lon})["piste:type"];
    );
    out tags geom center;
    """

    last_exc = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data=query.encode("utf-8"), headers=UA, timeout=35)
            r.raise_for_status()
            js = r.json() or {}
            if "remark" in js:
                raise RuntimeError(f"Overpass remark: {js.get('remark')}")
            return js.get("elements", []) or []
        except Exception as e:
            last_exc = e

    if last_exc:
        raise last_exc
    return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pistes(lat: float, lon: float, dist_km: int) -> List[Dict[str, Any]]:
    elements = _overpass_query(lat, lon, dist_km)

    pistes: List[Dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        geom = el.get("geometry") or []
        if not geom:
            continue

        name = tags.get("name") or tags.get("piste:name") or tags.get("ref") or ""
        difficulty = tags.get("piste:difficulty", "")
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


# ---------- Label ----------
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
    diff = _difficulty_label(p["difficulty"], lang)
    diff_part = f" · {diff}" if diff else ""
    len_part = f" · {p['length_km']:.1f} km" if p["length_km"] > 0 else ""
    return f"{name}{diff_part}{len_part}"


# ---------- Render principale ----------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]):
    lang = ctx.get("lang", "IT")
    lat = float(ctx.get("lat", 45.831))
    lon = float(ctx.get("lon", 7.730))
    place_label = ctx.get("place_label", "Località")

    st.markdown("### 4) Mappa & piste")

    show_pistes = st.checkbox(
        "Mostra piste sulla mappa",
        value=True,
        key="show_pistes",
    )

    pistes: List[Dict[str, Any]] = []
    selected_id = st.session_state.get("selected_piste_id")

    raw_count = 0

    if show_pistes:
        try:
            with st.spinner(
                f"Carico le piste (raggio {BASE_RADIUS_KM} km) da OpenStreetMap / Overpass…"
            ):
                elements = _overpass_query(lat, lon, BASE_RADIUS_KM)
                raw_count = len(elements)
                pistes = fetch_pistes(lat, lon, BASE_RADIUS_KM)

            if not pistes:
                with st.spinner(
                    f"Nessuna pista nel raggio {BASE_RADIUS_KM} km, riprovo con {FALLBACK_RADIUS_KM} km…"
                ):
                    elements = _overpass_query(lat, lon, FALLBACK_RADIUS_KM)
                    raw_count = len(elements)
                    pistes = fetch_pistes(lat, lon, FALLBACK_RADIUS_KM)

        except Exception as e:
            st.error(f"Errore caricando le piste (OSM/Overpass): {e}")

    st.caption(f"Piste trovate dopo filtro: {len(pistes)} (elementi Overpass grezzi: {raw_count})")

    if show_pistes and not pistes:
        st.info("Nessuna pista trovata in questo comprensorio (OSM/Overpass).")

    # --- ricerca pista + selectbox come prima (omesso per brevità se non ti serve) ---

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

    folium.Marker(
        [map_lat, map_lon],
        tooltip=place_label,
        icon=folium.Icon(color="lightgray", icon="info-sign"),
    ).add_to(m)

    for p in pistes:
        coords = [(c["lat"], c["lon"]) for c in p["coords"]]
        if not coords:
            continue
        folium.PolyLine(
            locations=coords,
            color="#3388ff",
            weight=3,
            opacity=0.95,
            tooltip=p["name"] or f"Pista {p['id']}",
        ).add_to(m)

    st_folium(
        m,
        height=420,
        use_container_width=True,
        key=f"map_{round(map_lat,5)}_{round(map_lon,5)}",
    )
