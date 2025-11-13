# core/maps.py
# Mappa & piste da sci (OSM / Overpass) + selezione pista e filtro per comprensorio

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


# ---------- util geometrici ----------

def _haversine_km(lat1, lon1, lat2, lon2):
    """Distanza approssimata in km tra due punti (lat/lon in gradi)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _feature_centroid(feat):
    coords = (feat.get("geometry", {}) or {}).get("coordinates", []) or []
    if not coords:
        return None, None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return sum(ys) / len(ys), sum(xs) / len(xs)


# ---------- download piste ----------

@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _fetch_pistes_raw(lat: float, lon: float, dist_km: int = 22):
    """
    Scarica piste alpine (piste:type=downhill) in un raggio dist_km.
    Ritorna una lista di Feature (GeoJSON-like) arricchite con:
      props["center_lat"], props["center_lon"], props["center_dist_km"], props["length_km"]
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
        geom = el.get("geometry")
        if not geom:
            continue
        coords = [(g["lon"], g["lat"]) for g in geom]
        if len(coords) < 2:
            continue

        # lunghezza
        length_km = 0.0
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
            length_km += _haversine_km(y1, x1, y2, x2)

        cy, cx = _feature_centroid({"geometry": {"coordinates": coords}})
        dist_center = _haversine_km(lat, lon, cy, cx) if cy is not None else 999.0

        feat = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "id": el.get("id"),
                "name": name,
                "piste:type": tags.get("piste:type", ""),
                "length_km": round(length_km, 1),
                "center_lat": cy,
                "center_lon": cx,
                "center_dist_km": round(dist_center, 2),
            },
        }
        feats.append(feat)

    return feats


def _cluster_same_resort(feats, resort_lat, resort_lon,
                         seed_radius_km=5.0, link_radius_km=5.0):
    """
    Heuristica: tiene solo il 'comprensorio' collegato alla località.

    1. Trova piste seed con centro entro seed_radius_km dalla località.
    2. Costruisce un grafo di adiacenza tra piste con centri entro link_radius_km.
    3. Prende la componente connessa che contiene le seed.
    """
    if not feats:
        return []

    # seed = piste vicino al punto di località
    seed_idx = []
    for i, f in enumerate(feats):
        props = f.get("properties", {}) or {}
        d = props.get("center_dist_km", 999)
        if d <= seed_radius_km:
            seed_idx.append(i)

    if not seed_idx:
        # fallback: tieni solo quelle entro 10 km
        return [f for f in feats
                if (f.get("properties", {}) or {}).get("center_dist_km", 999) <= 10.0]

    n = len(feats)
    adj = [[] for _ in range(n)]
    centers = [
        (f["properties"].get("center_lat"), f["properties"].get("center_lon"))
        for f in feats
    ]

    for i in range(n):
        lat1, lon1 = centers[i]
        if lat1 is None:
            continue
        for j in range(i + 1, n):
            lat2, lon2 = centers[j]
            if lat2 is None:
                continue
            d = _haversine_km(lat1, lon1, lat2, lon2)
            if d <= link_radius_km:
                adj[i].append(j)
                adj[j].append(i)

    # BFS dalle seed
    visited = set(seed_idx)
    stack = list(seed_idx)
    while stack:
        i = stack.pop()
        for j in adj[i]:
            if j not in visited:
                visited.add(j)
                stack.append(j)

    return [feats[i] for i in sorted(visited)]


def _make_geojson(feats):
    return {"type": "FeatureCollection", "features": feats}


# ---------- lista piste per selectbox ----------

def _build_piste_options(geojson, resort_hint: str | None = None):
    feats = geojson.get("features", []) if geojson else []
    opts = []
    for f in feats:
        props = f.get("properties", {}) or {}
        pid = props.get("id")
        name = props.get("name", "") or ""
        length = props.get("length_km", 0.0)
        dist_km = props.get("center_dist_km", None)

        label_core = name if name else f"{pid}"
        if dist_km is not None:
            label = f"{label_core} · {length:.1f} km · {dist_km:.1f} km"
        else:
            label = f"{label_core} · {length:.1f} km"

        opts.append((pid, label, f))

    # se abbiamo un hint (nome località) mettiamo in alto le piste che lo contengono
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

    show_pistes = st.checkbox(
        "Mostra piste sulla mappa",
        value=True,
        key="show_pistes",
    )

    geojson = None
    piste_opts = []

    if show_pistes:
        try:
            raw_feats = _fetch_pistes_raw(lat, lon, dist_km=22)
            cluster = _cluster_same_resort(raw_feats, lat, lon,
                                           seed_radius_km=5.0,
                                           link_radius_km=5.0)
            geojson = _make_geojson(cluster)
            piste_opts = _build_piste_options(geojson, resort_hint=resort_hint)
        except Exception as e:
            st.error(f"Errore caricando le piste (OSM/Overpass): {e}")

    selected_feat = None

    # ---------- Ricerca & selectbox ----------
    if piste_opts:
        name_query = st.text_input("Cerca pista per nome", key="piste_name_query")

        if name_query:
            q = name_query.lower().strip()
            filtered = [
                (pid, lbl, f)
                for (pid, lbl, f) in piste_opts
                if q in (f.get("properties", {}).get("name", "").lower())
            ]
            piste_opts_view = filtered or piste_opts
        else:
            piste_opts_view = piste_opts

        labels = [lbl for (_, lbl, _) in piste_opts_view]
        ids = [pid for (pid, _, _) in piste_opts_view]

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
            chosen_id, _, chosen_feat = piste_opts_view[chosen_idx]
            selected_feat = chosen_feat

            if chosen_id != prev_id:
                _set_selected_piste(chosen_feat, chosen_id, place_label)
                return  # _set_selected_piste fa st.rerun()
    else:
        st.info("Nessuna pista trovata in questo comprensorio (OSM/Overpass).")

    # ---------- Mappa interattiva ----------
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

    if show_pistes and geojson and geojson.get("features"):
        def _style(f):
            pid = f.get("properties", {}).get("id")
            if selected_feat and pid == selected_feat.get("properties", {}).get("id"):
                return {"color": "#ff9900", "weight": 5, "opacity": 0.96}
        # default style
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

    out = st_folium(
        m,
        height=420,
        use_container_width=True,
        key=f"map_{round(lat, 5)}_{round(lon, 5)}",
        returned_objects=["last_clicked"],
    )
    click = (out or {}).get("last_clicked") or {}

    # ---------- Selezione pista via click ----------
    if click and show_pistes and piste_opts:
        click_lat = float(click.get("lat"))
        click_lon = float(click.get("lng"))
        nearest_id, nearest_feat = _nearest_piste_to_point(
            click_lat, click_lon, piste_opts
        )
        if nearest_feat is not None:
            prev_id = st.session_state.get("selected_piste_id")
            if nearest_id != prev_id:
                _set_selected_piste(nearest_feat, nearest_id, place_label)
                return  # _set_selected_piste fa st.rerun()


def _nearest_piste_to_point(lat, lon, piste_opts):
    best_id = None
    best_feat = None
    best_d = 9999.0
    for pid, _lbl, feat in piste_opts:
        props = feat.get("properties", {}) or {}
        cy = props.get("center_lat")
        cx = props.get("center_lon")
        if cy is None or cx is None:
            continue
        d = _haversine_km(lat, lon, cy, cx)
        if d < best_d:
            best_d = d
            best_id = pid
            best_feat = feat
    return best_id, best_feat


def _set_selected_piste(feat, piste_id, old_place_label):
    """
    Aggiorna lat/lon/label/session_state quando cambia la pista selezionata,
    poi fa st.rerun().
    """
    cy = feat["properties"].get("center_lat")
    cx = feat["properties"].get("center_lon")
    pname = feat["properties"].get("name") or f"Pista {piste_id}"

    # estrai solo la parte 'località' dall'etichetta precedente, se possibile
    base_loc = old_place_label.split("—")[-1].strip() if "—" in old_place_label else old_place_label

    st.session_state["lat"] = float(cy)
    st.session_state["lon"] = float(cx)
    st.session_state["place_label"] = f"{pname} — {base_loc}"
    st.session_state["selected_piste_id"] = piste_id
    # forza ricalcolo DEM collegato ad altitudine/esposizione
    st.session_state.pop("_alt_sync_key", None)
    st.rerun()
