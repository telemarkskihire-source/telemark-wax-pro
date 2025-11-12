# core/maps.py
# Telemark · Pro Wax & Tune — modulo MAPS (folium + OSM fallback)
# Espone: render_map(T, ctx)  (alias: render)

import math, requests, streamlit as st

UA = {"User-Agent":"telemark-wax-pro/1.0"}

# --- Funzioni utili per tile & reverse geocode ---
@st.cache_data(ttl=6*3600, show_spinner=False)
def osm_tile(lat, lon, z=9):
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8)
    r.raise_for_status()
    return r.content

@st.cache_data(ttl=3*3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 30):
    """Scarica piste alpine (piste:type=downhill) via Overpass."""
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
    );
    out geom;
    """
    r = requests.post("https://overpass-api.de/api/interpreter", data=query, headers=UA, timeout=30)
    r.raise_for_status()
    data = r.json().get("elements", [])
    feats = []
    for el in data:
        props = {
            "id": el.get("id"),
            "piste:type": (el.get("tags") or {}).get("piste:type", ""),
            "name": (el.get("tags") or {}).get("name", "")
        }
        if "geometry" in el:
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
            geom = {"type": "LineString", "coordinates": coords}
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}

def reverse_geocode(lat, lon):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lon, "zoom": 12, "addressdetails": 1},
            headers=UA, timeout=8
        )
        r.raise_for_status()
        j = r.json()
        addr = j.get("address", {}) or {}
        cc = addr.get("country_code", "")
        name = addr.get("village") or addr.get("town") or addr.get("city") or j.get("display_name", "")
        region = addr.get("state") or addr.get("region") or ""
        label = ", ".join([p for p in [name, region] if p])
        if cc:
            label = f"{chr(127397+ord(cc[0].upper()))}{chr(127397+ord(cc[1].upper()))}  {label}"
        return label
    except Exception:
        return f"{lat:.5f}, {lon:.5f}"

# --- UI principale ---
def render_map(T, ctx):
    """
    Pannello mappa interattiva Folium + fallback tile.
    Usa ctx['lat'], ctx['lon'] e aggiorna session_state["lat"/"lon"/"place_label"] se si clicca.
    """
    lat = float(ctx.get("lat", st.session_state.get("lat", 45.831)))
    lon = float(ctx.get("lon", st.session_state.get("lon", 7.730)))
    iso2 = ctx.get("iso2", "IT")
    place_label = ctx.get("place_label", st.session_state.get("place_label", "Champoluc"))

    # tenta import folium
    HAS_FOLIUM = False
    try:
        from streamlit_folium import st_folium
        import folium
        from folium import TileLayer, LayerControl, Marker
        from folium.plugins import MousePosition
        HAS_FOLIUM = True
    except Exception:
        HAS_FOLIUM = False

    if HAS_FOLIUM:
        with st.expander(T.get("map", "Mappa") + " — clicca sulla mappa per selezionare", expanded=True):
            map_key = f"map_{round(lat,5)}_{round(lon,5)}_{iso2}"
            m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None, control_scale=True, prefer_canvas=True)
            TileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                      name="Strade", attr="© OSM", overlay=False, control=True).add_to(m)

            # piste
            try:
                gj = fetch_pistes_geojson(lat, lon, dist_km=30)
                if gj["features"]:
                    folium.GeoJson(
                        data=gj, name="Piste alpine (OSM)",
                        tooltip=folium.GeoJsonTooltip(fields=["name","piste:type"], aliases=["Nome","Tipo"]),
                        style_function=lambda f: {"color":"#3388ff","weight":3,"opacity":0.95}
                    ).add_to(m)
            except Exception:
                pass

            Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)
            MousePosition().add_to(m)
            LayerControl(position="bottomleft", collapsed=True).add_to(m)

            out = st_folium(m, height=420, use_container_width=True, key=map_key, returned_objects=["last_clicked"])
            click = (out or {}).get("last_clicked") or {}

            if click:
                new_lat = float(click.get("lat"))
                new_lon = float(click.get("lng"))
                new_pair = (round(new_lat,5), round(new_lon,5))
                if st.session_state.get("_last_click") != new_pair:
                    st.session_state["_last_click"] = new_pair
                    st.session_state["lat"] = new_lat
                    st.session_state["lon"] = new_lon
                    st.session_state["place_label"] = reverse_geocode(new_lat, new_lon)
                    st.success(f"Posizione aggiornata: {st.session_state['place_label']}")
                    st.rerun()
    else:
        st.warning("Folium non disponibile, uso tile statico OSM.")
        try:
            tile = osm_tile(lat, lon, z=9)
            st.image(tile, caption=T.get("map", "Mappa"), width=220)
        except Exception as e:
            st.error(f"Impossibile caricare tile OSM: {e}")

    # --- Pannello per inserire coordinate manualmente ---
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
            st.rerun()

# alias per l’orchestratore
render = render_map
