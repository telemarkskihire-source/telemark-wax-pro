# core/maps.py
# Mappa & piste da sci (OSM / Overpass) + selezione pista

import math
import requests
import streamlit as st

try:
    from streamlit_folium import st_folium
    import folium
    from folium import TileLayer, LayerControl, Marker, GeoJson, GeoJsonTooltip
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

UA = {"User-Agent": "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"}


# ---------- util ----------

def _haversine_km(lat1, lon1, lat2, lon2):
    """Distanza approssimata in km tra due punti."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 18):
    """
    Scarica piste alpine (piste:type=downhill) in un raggio dist_km.
    Torna un GeoJSON FeatureCollection.
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
        timeout=40,
    )
    r.raise_for_status()
    data = r.json().get("elements", [])

    feats = []
    for el in data:
        tags = el.get("tags", {}) or {}
        name = tags.get("name", "")
        if "geometry" not in el:
            continue
        coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
        if len(coords) < 2:
            continue

        # lunghezza approssimata
        length_km = 0.0
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
            length_km += _haversine_km(y1, x1, y2, x2)

        feat = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "id": el.get("id"),
                "name": name,
                "piste:type": tags.get("piste:type", ""),
                "length_km": round(length_km, 1),
            },
        }
        feats.append(feat)

    return {"type": "FeatureCollection", "features": feats}


def _build_piste_options(geojson, resort_hint: str | None = None):
    """
    Costruisce una lista di tuple (id, label, feature) per la selectbox.
    Prova a mettere in alto le piste che contengono il nome località.
    """
    feats = geojson.get("features", []) if geojson else []
    opts = []
    for f in feats:
        props = f.get("properties", {}) or {}
        pid = props.get("id")
        name = props.get("name", "") or ""
        length = props.get("length_km", 0.0)
        if name:
            label = f"{name} · {length:.1f} km"
        else:
            label = f"{pid} · {length:.1f} km"
        opts.append((pid, label, f))

    # resort_hint = nome località (es. "Champoluc") per dare priorità
    if resort_hint:
        hint = resort_hint.lower()
        opts.sort(
            key=lambda t: (
                0 if hint in (t[2].get("properties", {}).get("name", "").lower()) else 1,
                t[2].get("properties", {}).get("name", ""),
            )
        )
    else:
        opts.sort(key=lambda t: t[2].get("properties", {}).get("name", ""))

    return opts


def _feature_centroid_latlon(feat):
    coords = (feat.get("geometry", {}) or {}).get("coordinates", []) or []
    if not coords:
        return None, None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return sum(ys) / len(ys), sum(xs) / len(xs)


# ---------- UI principale ----------

def render_map(T, ctx):
    """
    Pannello "4) Mappa & piste".
    ctx: {"lat","lon","place_label","iso2","lang","T"}
    """
    lat = float(ctx["lat"])
    lon = float(ctx["lon"])
    place_label = ctx.get("place_label", "")
    resort_hint = place_label.split(",")[0].strip() if place_label else None

    st.markdown("### 4) Mappa & piste")

    if not HAS_FOLIUM:
        st.warning(
            "Modulo mappe (folium) non disponibile in questo ambiente. "
            "La mappa interattiva non può essere mostrata."
        )
        return

    show_pistes = st.checkbox("Mostra piste sulla mappa", value=True, key="show_pistes")

    # --- Caricamento piste OSM ---
    geojson = None
    piste_opts = []
    if show_pistes:
        try:
            geojson = fetch_pistes_geojson(lat, lon, dist_km=18)
            piste_opts = _build_piste_options(geojson, resort_hint=resort_hint)
        except Exception as e:
            st.error(f"Errore caricando le piste (OSM/Overpass): {e}")

    # ---------- Ricerca & selezione pista ----------
    selected_feat = None

    if piste_opts:
        name_query = st.text_input("Cerca pista per nome", key="piste_name_query")

        # filtro testo
        if name_query:
            q = name_query.lower().strip()
            filtered = [
                (pid, lbl, f)
                for (pid, lbl, f) in piste_opts
                if q in (f.get("properties", {}).get("name", "").lower())
            ]
            if filtered:
                piste_opts_filtered = filtered
            else:
                piste_opts_filtered = piste_opts
        else:
            piste_opts_filtered = piste_opts

        labels = [lbl for (_, lbl, _) in piste_opts_filtered]
        ids = [pid for (pid, _, _) in piste_opts_filtered]

        # default: ultimo id usato se esiste
        prev_id = st.session_state.get("selected_piste_id")
        try:
            default_index = ids.index(prev_id) if prev_id in ids else 0
        except Exception:
            default_index = 0

        chosen_label = st.selectbox(
            "Seleziona pista",
            labels,
            index=default_index if labels else 0,
            key="piste_selectbox",
        )

        if labels:
            chosen_idx = labels.index(chosen_label)
            chosen_id, _, chosen_feat = piste_opts_filtered[chosen_idx]
            selected_feat = chosen_feat

            # se è cambiata la pista selezionata → aggiorniamo stato globale
            if chosen_id != prev_id:
                st.session_state["selected_piste_id"] = chosen_id
                cy, cx = _feature_centroid_latlon(chosen_feat)
                if cy is not None and cx is not None:
                    st.session_state["lat"] = cy
                    st.session_state["lon"] = cx
                    # label sintetica
                    pname = (
                        chosen_feat.get("properties", {}).get("name", "")
                        or f"Pista {chosen_id}"
                    )
                    st.session_state["place_label"] = f"{pname} — {place_label}"
                    # forza ricalcolo DEM sul nuovo punto
                    st.session_state.pop("_alt_sync_key", None)
                    # ricarica app con i nuovi valori
                    st.rerun()
    else:
        st.info("Nessuna pista trovata in questo raggio (OSM/Overpass).")

    # ---------- Mappa interattiva ----------
    # rileggo eventuali lat/lon aggiornati da `st.rerun()` sopra
    lat = float(st.session_state.get("lat", lat))
    lon = float(st.session_state.get("lon", lon))
    place_label = st.session_state.get("place_label", place_label)

    m = folium.Map(
        location=[lat, lon],
        zoom_start=13,
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

    # piste
    if show_pistes and geojson and geojson.get("features"):
        def _style(f):
            # pista selezionata leggermente diversa
            pid = f.get("properties", {}).get("id")
            if selected_feat and pid == selected_feat.get("properties", {}).get("id"):
                return {"color": "#ff9900", "weight": 5, "opacity": 0.95}
            return {"color": "#3388ff", "weight": 3, "opacity": 0.9}

        GeoJson(
            data=geojson,
            name="Piste alpine (OSM)",
            tooltip=GeoJsonTooltip(
                fields=["name", "piste:type", "length_km"],
                aliases=["Nome", "Tipo", "Lunghezza (km)"],
                localize=True,
            ),
            style_function=_style,
        ).add_to(m)

    Marker(
        [lat, lon],
        tooltip=place_label,
        icon=folium.Icon(color="lightgray"),
    ).add_to(m)

    LayerControl(position="bottomleft", collapsed=True).add_to(m)

    st_folium(m, height=420, use_container_width=True, key=f"map_{round(lat,5)}_{round(lon,5)}")
