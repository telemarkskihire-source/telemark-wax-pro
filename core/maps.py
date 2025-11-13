# core/maps.py
# Mappa + piste da sci (lista selezionabile, filtro comprensorio, click-select)

import math
import requests
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"}

# Raggio per query Overpass (un po' largo) e raggio effettivo del comprensorio
OVERPASS_RADIUS_KM = 25      # quanto lontano chiediamo a Overpass
RESORT_RADIUS_KM   = 10      # quali piste teniamo davvero in lista (centro comprensorio)

# ---- Folium opzionale ----
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False


# =========================
#  Overpass: piste GeoJSON
# =========================
@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = OVERPASS_RADIUS_KM):
    """
    Restituisce un FeatureCollection con piste alpine (piste:type=downhill)
    nel raggio dist_km intorno a (lat, lon).
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
    data = r.json().get("elements", []) or []

    feats = []
    for el in data:
        tags = el.get("tags") or {}
        name = tags.get("name", "").strip()
        ptype = tags.get("piste:type", "")
        if "geometry" not in el:
            continue
        coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
        geom = {"type": "LineString", "coordinates": coords}
        props = {
            "id": el.get("id"),
            "name": name,
            "piste:type": ptype,
        }
        feats.append({"type": "Feature", "geometry": geom, "properties": props})

    return {"type": "FeatureCollection", "features": feats}


def _haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _piste_options_from_geojson(gj, center_lat, center_lon, max_km=RESORT_RADIUS_KM):
    """
    Converte il GeoJSON delle piste in:
    - lista di opzioni per selectbox (pid, label)
    - mappa id -> feature
    Filtra le piste il cui CENTRO cade oltre max_km dal centro località
    (così Champoluc non prende Zermatt & co).
    """
    feats = gj.get("features", []) if gj else []
    options = []
    by_id = {}

    for f in feats:
        props = f.get("properties", {}) or {}
        pid = props.get("id")
        name = (props.get("name") or "").strip()
        if not pid:
            continue

        coords = f.get("geometry", {}).get("coordinates") or []
        if not coords:
            continue

        # centro geometrico della pista (media dei punti)
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        clat = sum(lats) / len(lats)
        clon = sum(lons) / len(lons)

        dist_center = _haversine_km(center_lon, center_lat, clon, clat)
        if dist_center > max_km:
            continue  # troppo lontana → probabilmente un altro comprensorio

        # lunghezza approssimata
        length_km = 0.0
        for i in range(1, len(coords)):
            lon1, lat1 = coords[i - 1]
            lon2, lat2 = coords[i]
            length_km += _haversine_km(lon1, lat1, lon2, lat2)

        label = name if name else f"ID {pid}"
        label_full = f"{label} · {length_km:.1f} km"
        options.append((pid, label_full))
        f["__centroid__"] = (clat, clon)
        by_id[pid] = f

    # ordina alfabeticamente su label
    options.sort(key=lambda x: x[1])
    return options, by_id


def _nearest_piste_to_click(by_id, click_lat, click_lon):
    """
    Trova la pista più vicina al click (uso vertici, non la polilinea continua).
    Ritorna (piste_id, distanza_km) oppure (None, None)
    """
    best_id = None
    best_d = None
    for pid, feat in by_id.items():
        coords = feat.get("geometry", {}).get("coordinates") or []
        for lon, lat in coords:
            d = _haversine_km(click_lon, click_lat, lon, lat)
            if best_d is None or d < best_d:
                best_d = d
                best_id = pid
    return best_id, best_d


# =========================
#  RENDER PRINCIPALE
# =========================
def render_map(T, ctx):
    """
    Pannello mappa + lista piste.
    ctx: dict con lat, lon, place_label, ...
    """
    lat = float(ctx.get("lat", 45.831))
    lon = float(ctx.get("lon", 7.730))
    place_label = ctx.get("place_label", "Località")

    st.markdown("### 4) Mappa & piste")

    if not HAS_FOLIUM:
        st.info("Folium non disponibile nell'ambiente. Mostro solo coordinate.")
        st.write(f"lat={lat:.5f}, lon={lon:.5f}")
        return

    # Se cambia località, resetto liste piste
    center_key = (round(lat, 5), round(lon, 5))
    if st.session_state.get("_piste_origin") != center_key:
        st.session_state["_piste_origin"] = center_key
        st.session_state.pop("piste_options", None)
        st.session_state.pop("piste_by_id", None)
        st.session_state.pop("selected_piste_id", None)

    # --- Fetch piste via Overpass ---
    try:
        gj = fetch_pistes_geojson(lat, lon)
        options, by_id = _piste_options_from_geojson(gj, lat, lon)
        st.session_state["piste_options"] = options
        st.session_state["piste_by_id"] = by_id
    except Exception as e:
        st.warning(f"Impossibile caricare le piste da Overpass: {e}")
        options = []
        by_id = {}

    # --- UI lista piste ---
    col_toggle, col_search, col_sel = st.columns([1, 1.2, 2])

    with col_toggle:
        show_all = st.checkbox("Mostra piste sulla mappa", value=True)

    # filtro per nome pista
    with col_search:
        search_q = st.text_input("Cerca pista per nome", "", key="piste_search").strip().lower()

    selected_id = None
    label_by_id = {pid: label for pid, label in options}

    with col_sel:
        filtered = options
        if search_q:
            filtered = [
                (pid, label)
                for pid, label in options
                if search_q in label.lower()
            ]

        if filtered:
            labels = [opt[1] for opt in filtered]
            ids = [opt[0] for opt in filtered]

            # default: ultima selezionata o prima
            default_idx = 0
            if "selected_piste_id" in st.session_state:
                try:
                    default_idx = ids.index(st.session_state["selected_piste_id"])
                except ValueError:
                    default_idx = 0

            choice = st.selectbox(
                "Seleziona pista",
                options=range(len(labels)),
                format_func=lambda i: labels[i],
                index=default_idx,
                key="piste_selectbox",
            )
            selected_id = ids[choice]
            st.session_state["selected_piste_id"] = selected_id
        else:
            st.info("Nessuna pista trovata (controlla filtro o zona).")
            show_all = False

    # --- Se ho una pista selezionata, aggiorno lat/lon per DEM & co. ---
    if selected_id and selected_id in by_id:
        feat = by_id[selected_id]
        clat, clon = feat.get("__centroid__", (lat, lon))
        anchor = (round(clat, 5), round(clon, 5))
        if st.session_state.get("_dem_anchor") != anchor:
            # aggiorno posizione "ufficiale" per moduli DEM/meteo
            st.session_state["_dem_anchor"] = anchor
            st.session_state["lat"] = float(clat)
            st.session_state["lon"] = float(clon)
            # al prossimo run streamlit_app rigenera ctx e il DEM userà il nuovo punto
            st.experimental_rerun()

    # --- Costruzione mappa Folium ---
    map_key = f"map_{center_key[0]}_{center_key[1]}"
    m = folium.Map(
        location=[lat, lon],
        zoom_start=12,
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr="© OpenStreetMap",
        control_scale=True,
    )

    # Marker principale (centro località)
    folium.Marker(
        [lat, lon],
        tooltip=place_label,
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Disegno tutte le piste (se richiesto)
    if show_all and by_id:
        for pid, feat in by_id.items():
            coords = feat["geometry"]["coordinates"]
            pts = [(lat_, lon_) for (lon_, lat_) in coords]

            # pista selezionata: più spessa e colore diverso
            if pid == st.session_state.get("selected_piste_id"):
                color = "#06b6d4"  # Telemark
                weight = 6
            else:
                color = "#3388ff"
                weight = 3

            folium.PolyLine(
                pts,
                color=color,
                weight=weight,
                opacity=0.95,
            ).add_to(m)

    # Output interattivo
    out = st_folium(
        m,
        height=420,
        use_container_width=True,
        key=map_key,
        returned_objects=["last_clicked"],
    )
    click = (out or {}).get("last_clicked") or {}

    # Click sulla mappa → se vicino a una pista, seleziono quella pista
    if click and by_id:
        click_lat = float(click.get("lat"))
        click_lon = float(click.get("lng"))
        nearest_id, dist_km = _nearest_piste_to_click(by_id, click_lat, click_lon)

        # se il click è entro 300 m da una pista, lo interpreto come selezione di quella pista
        if nearest_id is not None and dist_km is not None and dist_km < 0.3:
            st.session_state["selected_piste_id"] = nearest_id
            st.session_state["_last_click_map"] = (round(click_lat, 5), round(click_lon, 5))
            label = label_by_id.get(nearest_id, str(nearest_id))
            st.success(f"Pista selezionata dalla mappa: {label}")
            st.experimental_rerun()
        else:
            # click libero: aggiorno solo coordinate (se vuoi mantenere questo comportamento)
            st.session_state["_last_click_map"] = (round(click_lat, 5), round(click_lon, 5))
            st.session_state["lat"] = click_lat
            st.session_state["lon"] = click_lon
            st.success(f"Posizione aggiornata da mappa: {click_lat:.5f}, {click_lon:.5f}")
            st.experimental_rerun()

    # salvo nel contesto eventuale pista selezionata (se serve ad altri moduli)
    if st.session_state.get("selected_piste_id") in by_id:
        st.session_state["_selected_piste"] = by_id[st.session_state["selected_piste_id"]]
    else:
        st.session_state.pop("_selected_piste", None)
