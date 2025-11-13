# core/maps.py
# Mappa & piste (OSM / Overpass) per Telemark · Pro Wax & Tune

from __future__ import annotations

import math
from typing import List, Dict, Any

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

UA = {
    "User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)",
    "Accept": "application/json",
}

# Endpoints Overpass (primario + fallback)
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

MAX_RADIUS_KM = 10  # raggio comprensorio

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

# ---------- Fetch piste da Overpass ----------

def _overpass_query(lat: float, lon: float, dist_km: int) -> List[Dict[str, Any]]:
    radius_m = int(dist_km * 1000)
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["piste:type"];
      relation(around:{radius_m},{lat},{lon})["piste:type"];
      way(around:{radius_m},{lat},{lon})["piste:difficulty"];
      relation(around:{radius_m},{lat},{lon})["route"="piste"];
    );
    out tags geom center;
    """
    last_exc = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data=query.encode("utf-8"), headers=UA, timeout=35)
            r.raise_for_status()
            return (r.json() or {}).get("elements", []) or []
        except Exception as e:
            last_exc = e
    # se tutti gli endpoint falliscono, rilanciamo l'ultima eccezione
    if last_exc:
        raise last_exc
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pistes(lat: float, lon: float, dist_km: int = MAX_RADIUS_KM) -> List[Dict[str, Any]]:
    """
    Restituisce una lista di piste nel raggio dist_km:
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
    elements = _overpass_query(lat, lon, dist_km)

    pistes: List[Dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        # Filtra solo cose che sembrano piste
        if (
            "piste:type" not in tags
            and "piste:difficulty" not in tags
            and not (tags.get("route") == "piste")
        ):
            continue

        name = tags.get("name") or tags.get("piste:name") or tags.get("ref") or ""
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

# ---------- Label & difficulty ----------

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
    """
    Pannello 'Mappa & piste'.
    """
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
    if show_pistes:
        try:
            with st.spinner("Carico le piste da OpenStreetMap / Overpass…"):
                pistes = fetch_pistes(lat, lon, dist_km=MAX_RADIUS_KM)
        except requests.exceptions.Timeout:
            st.error("Errore caricando le piste (OSM/Overpass): timeout del servizio.")
        except requests.exceptions.HTTPError as e:
            st.error(f"Errore caricando le piste (OSM/Overpass): {e}")
        except Exception as e:
            st.error(f"Errore imprevisto caricando le piste (OSM/Overpass): {e}")

    if show_pistes and not pistes:
        st.info("Nessuna pista trovata in questo comprensorio (OSM/Overpass).")

    # ----------- Ricerca / select pista -----------

    selected_piste = None
    selected_id = st.session_state.get("selected_piste_id")

    if pistes:
        search_txt = st.text_input(
            "Cerca pista per nome",
            value="",
            key="piste_search",
            placeholder="es. Del Bosco, Bettaforca, Sarezza…",
        ).strip().lower()

        filtered = []
        for p in pistes:
            name_norm = (p["name"] or "").lower()
            if not search_txt or search_txt in name_norm:
                filtered.append(p)

        if not filtered:
            st.warning("Nessuna pista corrisponde alla ricerca. Mostro l'elenco completo.")
            filtered = pistes

        options = [_piste_option_label(p, lang) for p in filtered]
        label_to_piste = { _piste_option_label(p, lang): p for p in filtered }

        # default: se abbiamo una pista già selezionata, posizioniamo l'indice su quella
        default_index = 0
        if selected_id is not None:
            for i, p in enumerate(filtered):
                if p["id"] == selected_id:
                    default_index = i
                    break

        chosen_label = st.selectbox(
            "Seleziona pista",
            options=options,
            index=default_index if options else 0,
            key="piste_select",
        ) if options else None

        if chosen_label:
            selected_piste = label_to_piste.get(chosen_label)
            if selected_piste:
                selected_id = selected_piste["id"]
                st.session_state["selected_piste_id"] = selected_id

                ctx_lat = float(selected_piste["center_lat"])
                ctx_lon = float(selected_piste["center_lon"])
                ctx_label = f"{place_label.split('—')[0].strip()} · {selected_piste['name'] or 'pista'}"

                ctx["lat"] = ctx_lat
                ctx["lon"] = ctx_lon
                ctx["place_label"] = ctx_label

                st.session_state["lat"] = ctx_lat
                st.session_state["lon"] = ctx_lon
                st.session_state["place_label"] = ctx_label

    # ---------- Mappa Leaflet / Folium ----------

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

    # marker località
    folium.Marker(
        [map_lat, map_lon],
        tooltip=ctx.get("place_label", place_label),
        icon=folium.Icon(color="lightgray", icon="info-sign"),
    ).add_to(m)

    # disegna piste
    if pistes:
        for p in pistes:
            coords = [(c["lat"], c["lon"]) for c in p["coords"]]
            if not coords:
                continue

            is_sel = (selected_id is not None and p["id"] == selected_id)
            color = "#ff4b4b" if is_sel else "#3388ff"
            weight = 5 if is_sel else 3

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

    # mostra mappa + click → selezione pista più vicina
    out = st_folium(
        m,
        height=420,
        use_container_width=True,
        key=f"map_{round(map_lat,5)}_{round(map_lon,5)}",
        returned_objects=["last_clicked"],
    )

    click = (out or {}).get("last_clicked") or {}
    if click and pistes:
        c_lat = float(click.get("lat"))
        c_lon = float(click.get("lng"))

        # trova la pista col punto più vicino al click
        best_p = None
        best_d = 9999.0
        for p in pistes:
            for c in p["coords"]:
                d = _point_distance_km(c_lat, c_lon, c["lat"], c["lon"])
                if d < best_d:
                    best_d = d
                    best_p = p

        if best_p and best_p["id"] != st.session_state.get("selected_piste_id"):
            st.session_state["selected_piste_id"] = best_p["id"]
            # aggiorna anche ctx e centri per meteo/DEM
            ctx_lat = float(best_p["center_lat"])
            ctx_lon = float(best_p["center_lon"])
            ctx_label = f"{place_label.split('—')[0].strip()} · {best_p['name'] or 'pista'}"
            ctx["lat"] = ctx_lat
            ctx["lon"] = ctx_lon
            ctx["place_label"] = ctx_label
            st.session_state["lat"] = ctx_lat
            st.session_state["lon"] = ctx_lon
            st.session_state["place_label"] = ctx_label
