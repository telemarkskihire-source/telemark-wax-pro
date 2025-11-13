# core/maps.py
# Mappa + piste da sci (lista selezionabile)

import math
import requests
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"}

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
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 30):
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


def _piste_options_from_geojson(gj):
    """
    Converte il GeoJSON delle piste in:
    - lista di opzioni per selectbox
    - mappa id -> feature
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
        # lunghezza approssimata
        length_km = 0.0
        for i in range(1, len(coords)):
            lon1, lat1 = coords[i - 1]
            lon2, lat2 = coords[i]
            length_km += _haversine_km(lon1, lat1, lon2, lat2)

        label = name if name else f"ID {pid}"
        label_full = f"{label} · {length_km:.1f} km"
        options.append((pid, label_full))
        by_id[pid] = f

    # ordina alfabeticamente su label
    options.sort(key=lambda x: x[1])
    return options, by_id


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

    # Se cambia località, resetto piste selezionate
    center_key = (round(lat, 5), round(lon, 5))
    if st.session_state.get("_piste_origin") != center_key:
        st.session_state["_piste_origin"] = center_key
        st.session_state.pop("piste_options", None)
        st.session_state.pop("piste_by_id", None)
        st.session_state.pop("selected_piste_id", None)

    # --- Fetch piste via Overpass ---
    try:
        gj = fetch_pistes_geojson(lat, lon, dist_km=30)
        options, by_id = _piste_options_from_geojson(gj)
        st.session_state["piste_options"] = options
        st.session_state["piste_by_id"] = by_id
    except Exception as e:
        st.warning(f"Impossibile caricare le piste da Overpass: {e}")
        options = []
        by_id = {}

    # --- UI lista piste ---
    col_toggle, col_sel = st.columns([1, 2])

    with col_toggle:
        show_all = st.checkbox("Mostra piste sulla mappa", value=True)

    selected_id = None
    with col_sel:
        if options:
            labels = [opt[1] for opt in options]
            ids = [opt[0] for opt in options]

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
            st.info("Nessuna pista trovata in zona (piste:type=downhill).")
            show_all = False

    # --- Costruzione mappa Folium ---
    map_key = f"map_{round(lat,5)}_{round(lon,5)}"
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
            if pid == selected_id:
                color = "#06b6d4"  # azzurrino Telemark
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

    # Click sulla mappa: aggiorno lat/lon globali
    if click:
        new_lat = float(click.get("lat"))
        new_lon = float(click.get("lng"))
        new_pair = (round(new_lat, 5), round(new_lon, 5))
        if st.session_state.get("_last_click_map") != new_pair:
            st.session_state["_last_click_map"] = new_pair
            st.session_state["lat"] = new_lat
            st.session_state["lon"] = new_lon
            # place_label verrà aggiornato da altri moduli (es. reverse geocode in site_meta)
            st.success(f"Posizione aggiornata da mappa: {new_lat:.5f}, {new_lon:.5f}")
            st.experimental_rerun()

    # Salvo nel contesto informazioni utili sulla pista selezionata
    if selected_id and by_id.get(selected_id):
        st.session_state["_selected_piste"] = by_id[selected_id]
    else:
        st.session_state.pop("_selected_piste", None)
