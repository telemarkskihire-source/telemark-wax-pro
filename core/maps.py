# core/maps.py
# Mappa + piste da sci (OSM/Overpass) + selezione pista

import math
import requests
import streamlit as st

from core.search import BASE_UA, HEADERS_NOM, _flag, _concise_label, _retry

# -----------------------------------------------------------------------------
# Config comuni
# -----------------------------------------------------------------------------

UA = {"User-Agent": BASE_UA}

# Proviamo a caricare folium, altrimenti fallback immagine statica
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    from folium import TileLayer, LayerControl, Marker
    from folium.plugins import MousePosition

    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False


# -----------------------------------------------------------------------------
# Helpers OSM / Overpass
# -----------------------------------------------------------------------------

@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 30):
    """
    Scarica piste da sci alpino da Overpass in un raggio dist_km.
    Ritorna un GeoJSON FeatureCollection.
    """
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
    );
    out geom;
    """

    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data=query,
        headers=UA,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json().get("elements", [])
    feats = []
    for el in data:
        props = {
            "id": el.get("id"),
            "piste:type": (el.get("tags") or {}).get("piste:type", ""),
            "name": (el.get("tags") or {}).get("name", ""),
        }
        if "geometry" in el:
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
            geom = {"type": "LineString", "coordinates": coords}
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def osm_tile(lat: float, lon: float, z: int = 9):
    """Piccolo fallback: scarica una singola tile OSM come immagine."""
    n = 2 ** z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0
        * n
    )
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8)
    r.raise_for_status()
    return r.content


def reverse_geocode(lat: float, lon: float) -> str:
    """Da coordinate a etichetta leggibile, usando Nominatim."""
    try:
        def go():
            return requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "json",
                    "lat": lat,
                    "lon": lon,
                    "zoom": 12,
                    "addressdetails": 1,
                },
                headers=HEADERS_NOM,
                timeout=8,
            )

        r = _retry(go)
        r.raise_for_status()
        j = r.json()
        addr = j.get("address", {}) or {}
        lab = _concise_label(addr, j.get("display_name", ""))
        cc = addr.get("country_code", "")
        return f"{_flag(cc)}  {lab}"
    except Exception:
        return f"{lat:.5f}, {lon:.5f}"


# -----------------------------------------------------------------------------
# UI: selezione pista da lista
# -----------------------------------------------------------------------------

def _piste_select_ui(features):
    """
    Mostra la selectbox delle piste trovate e salva la scelta in session_state.
    """
    if not features:
        st.info("Nessun comprensorio sciistico trovato entro 30 km dalla località scelta.")
        return

    piste_labels = []
    piste_ids = []

    for f in features:
        props = f.get("properties", {}) or {}
        pid = props.get("id")
        name = props.get("name") or f"Pista ID {pid}"
        if pid is None:
            continue
        piste_ids.append(pid)
        piste_labels.append(name)

    if not piste_ids:
        st.info("Nessuna pista 'downhill' disponibile in questa zona.")
        return

    # default: se abbiamo già una pista salvata, la riselezioniamo
    idx_default = 0
    saved_id = st.session_state.get("pista_id")
    if saved_id in piste_ids:
        idx_default = piste_ids.index(saved_id)

    sel_label = st.selectbox("Seleziona pista", piste_labels, index=idx_default)
    sel_idx = piste_labels.index(sel_label)
    sel_id = piste_ids[sel_idx]

    st.session_state["pista_id"] = sel_id
    st.session_state["pista_name"] = sel_label

    st.caption(
        "La quota di partenza/arrivo verrà impostata in un modulo separato "
        "(altitudine pista), indipendentemente dalla posizione del puntatore."
    )


# -----------------------------------------------------------------------------
# ENTRYPOINT PRINCIPALE
# -----------------------------------------------------------------------------

def render_map(T, ctx):
    """
    Pannello mappa + piste:
    - mostra la mappa centrata su ctx["lat"], ctx["lon"]
    - consente click per aggiornare la posizione
    - carica piste OSM e permette la selezione della pista
    """
    lat = float(ctx["lat"])
    lon = float(ctx["lon"])
    place_label = ctx["place_label"]
    iso2 = ctx["iso2"]

    st.markdown("### 4) Mappa & piste")

    # Carichiamo subito le piste per poter usare la stessa lista sia su mappa che su selectbox
    try:
        gj = fetch_pistes_geojson(lat, lon, dist_km=30)
        features = gj.get("features", []) or []
    except Exception:
        gj = {"type": "FeatureCollection", "features": []}
        features = []
        st.warning("Impossibile contattare Overpass per le piste da sci in questo momento.")

    # ------------------ Mappa interattiva / fallback --------------------------
    if HAS_FOLIUM:
        with st.expander(T["map"] + " — clicca sulla mappa per selezionare", expanded=True):
            # chiave dinamica per reinit quando cambia località/paese
            map_key = f"map_{round(lat,5)}_{round(lon,5)}_{iso2}"

            m = folium.Map(
                location=[lat, lon],
                zoom_start=12,
                tiles=None,
                control_scale=True,
                prefer_canvas=True,
                zoom_control=True,
            )
            TileLayer(
                "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                name="Strade",
                attr="© OpenStreetMap contributors",
                overlay=False,
                control=True,
            ).add_to(m)

            # Piste come overlay GeoJson
            if features:
                sel_id = st.session_state.get("pista_id")

                def style_fn(f):
                    fid = (f.get("properties") or {}).get("id")
                    if sel_id and fid == sel_id:
                        return {"color": "#ff4b4b", "weight": 4, "opacity": 0.95}
                    return {"color": "#3388ff", "weight": 3, "opacity": 0.95}

                folium.GeoJson(
                    data=gj,
                    name="Piste alpine (OSM)",
                    tooltip=folium.GeoJsonTooltip(
                        fields=["name", "piste:type"],
                        aliases=["Nome", "Tipo"],
                    ),
                    style_function=style_fn,
                ).add_to(m)

            # Marker posizione attuale
            Marker(
                [lat, lon],
                tooltip=place_label,
                icon=folium.Icon(color="lightgray"),
            ).add_to(m)

            MousePosition().add_to(m)
            LayerControl(position="bottomleft", collapsed=True).add_to(m)

            out = st_folium(
                m,
                height=420,
                use_container_width=True,
                key=map_key,
                returned_objects=["last_clicked"],
            )
            click = (out or {}).get("last_clicked") or {}

            # Click → aggiorna coordinate e label
            if click:
                new_lat = float(click.get("lat"))
                new_lon = float(click.get("lng"))
                new_pair = (round(new_lat, 5), round(new_lon, 5))
                if st.session_state.get("_last_click") != new_pair:
                    st.session_state["_last_click"] = new_pair
                    st.session_state["lat"] = new_lat
                    st.session_state["lon"] = new_lon
                    new_label = reverse_geocode(new_lat, new_lon)
                    st.session_state["place_label"] = new_label
                    # aggiorniamo anche ctx usato dagli altri moduli
                    ctx["lat"] = new_lat
                    ctx["lon"] = new_lon
                    ctx["place_label"] = new_label
                    st.success(f"Posizione aggiornata: {new_label}")
                    st.rerun()
    else:
        # Fallback: sola immagine tile
        try:
            tile = osm_tile(lat, lon, z=9)
            st.image(tile, caption=T["map"], use_container_width=True)
        except Exception:
            st.info("Mappa non disponibile (manca streamlit-folium e il download tile è fallito).")

    # ------------------ Coordinate manuali -----------------------------------
    with st.expander("➕ Imposta coordinate manuali / Set precise coordinates", expanded=False):
        c_lat, c_lon = st.columns(2)
        new_lat = c_lat.number_input("Lat", value=float(lat), format="%.6f")
        new_lon = c_lon.number_input("Lon", value=float(lon), format="%.6f")
        if st.button("Imposta / Set"):
            st.session_state["_last_click"] = None
            st.session_state["lat"] = float(new_lat)
            st.session_state["lon"] = float(new_lon)
            new_label = reverse_geocode(float(new_lat), float(new_lon))
            st.session_state["place_label"] = new_label
            ctx["lat"] = float(new_lat)
            ctx["lon"] = float(new_lon)
            ctx["place_label"] = new_label
            st.rerun()

    # ------------------ Selettore piste --------------------------------------
    st.markdown("#### Piste disponibili nella zona")
    _piste_select_ui(features)
