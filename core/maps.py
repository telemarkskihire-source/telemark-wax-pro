# core/maps.py
# Mappa interattiva + lista piste da Overpass (solo piste downhill)
import math
import requests
import streamlit as st

BASE_UA = "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"

# Proviamo ad usare folium, altrimenti semplice fallback
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    from folium import TileLayer, LayerControl, Marker
    from folium.plugins import MousePosition
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False


# --------------------------------------------------------------------
# Overpass: piste downhill vicino alla località
# --------------------------------------------------------------------
@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 30):
    """
    Scarica piste alpine (piste:type=downhill) entro dist_km km dalla località.
    Ritorna un GeoJSON {type:'FeatureCollection', features:[…]}
    """
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
    );
    out geom;
    """

    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query,
            headers={"User-Agent": BASE_UA},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json().get("elements", [])
    except Exception:
        return {"type": "FeatureCollection", "features": []}

    feats = []
    for el in data:
        tags = el.get("tags", {}) or {}
        props = {
            "id": el.get("id"),
            "piste:type": tags.get("piste:type", ""),
            "name": tags.get("name", ""),
        }

        geom = el.get("geometry")
        if not geom:
            continue

        coords = [(g["lon"], g["lat"]) for g in geom]
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": feats}


# --------------------------------------------------------------------
# UI: selezione pista a partire dai features di Overpass
# --------------------------------------------------------------------
def _piste_select_ui(features):
    """
    Mostra la selectbox delle piste trovate e salva la scelta in session_state.

    Logica:
    - Se ci sono nomi OSM → un'opzione per ogni nome distinto.
    - Se tutte le piste sono senza nome ma >1 → generiamo Pista #1, Pista #2, ...
    """

    if not features:
        st.info("Nessun comprensorio sciistico trovato entro 30 km dalla località.")
        return

    # 1) raggruppa per nome
    by_name = {}
    unnamed = []

    for f in features:
        props = f.get("properties", {}) or {}
        pid = props.get("id")
        if pid is None:
            continue
        name = (props.get("name") or "").strip()
        if name:
            by_name.setdefault(name, []).append(pid)
        else:
            unnamed.append(pid)

    piste_labels = []
    piste_ids = []

    if by_name:
        # Abbiamo nomi veri: usiamo quelli
        for name in sorted(by_name.keys()):
            piste_labels.append(name)
            # come id associamo il primo della lista, ci basta un rappresentante
            piste_ids.append(by_name[name][0])
    else:
        # Tutto senza nome: creiamo nomi sintetici se ce n'è più di una
        if len(unnamed) == 1:
            piste_labels = [f"Pista ID {unnamed[0]}"]
            piste_ids = [unnamed[0]]
        else:
            for i, pid in enumerate(unnamed, start=1):
                piste_labels.append(f"Pista #{i} (ID {pid})")
                piste_ids.append(pid)

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


# --------------------------------------------------------------------
# UI: mappa interattiva (folium)
# --------------------------------------------------------------------
def _render_folium_map(lat, lon, place_label, features):
    # chiave dinamica per reinit quando cambia località
    map_key = f"map_{round(lat,5)}_{round(lon,5)}"

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
        attr="© OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(m)

    # layer piste
    if features:
        folium.GeoJson(
            data={"type": "FeatureCollection", "features": features},
            name="Piste alpine (OSM)",
            tooltip=folium.GeoJsonTooltip(
                fields=["name", "piste:type"],
                aliases=["Nome", "Tipo"],
            ),
            style_function=lambda f: {"color": "#3388ff", "weight": 3, "opacity": 0.95},
        ).add_to(m)

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
    if click:
        new_lat = float(click.get("lat"))
        new_lon = float(click.get("lng"))
        new_pair = (round(new_lat, 5), round(new_lon, 5))

        if st.session_state.get("_last_click") != new_pair:
            st.session_state["_last_click"] = new_pair
            st.session_state["lat"] = new_lat
            st.session_state["lon"] = new_lon
            # il label viene aggiornato altrove (site_meta o search); qui ci limitiamo al cambio coordinate
            st.success("Posizione aggiornata dal click sulla mappa. Rilancia il meteo per usare le nuove coordinate.")


# --------------------------------------------------------------------
# Entrypoint pubblico per il modulo
# --------------------------------------------------------------------
def render_map(T, ctx):
    """
    Punto di ingresso chiamato da streamlit_app.py
    ctx: dict con lat, lon, place_label, iso2, lang, T
    """
    lat = ctx.get("lat", 45.831)
    lon = ctx.get("lon", 7.730)
    place_label = ctx.get("place_label", "Località")
    lang = ctx.get("lang", "IT")

    # Titolo sezione
    st.markdown("### Mappa & piste")

    # 1) Fetch piste (solo downhill) una volta per località
    with st.spinner("Carico piste da OpenStreetMap…"):
        gj = fetch_pistes_geojson(lat, lon, dist_km=30)
    features = gj.get("features", []) or []

    # 2) Selettore piste
    st.markdown("#### Piste nella zona selezionata")
    _piste_select_ui(features)

    # 3) Mappa interattiva opzionale
    if HAS_FOLIUM:
        with st.expander("Mostra mappa interattiva (sperimentale)", expanded=False):
            _render_folium_map(lat, lon, place_label, features)
    else:
        st.info(
            "Modulo mappa interattiva non disponibile (dipendenza folium mancante). "
            "Le piste sono comunque elencate sopra."
        )

    # Hint finale (in italiano/inglese)
    if lang == "IT":
        st.caption(
            "Suggerimento: dopo aver scelto una pista qui, imposta la quota di partenza nel modulo altitudine "
            "e poi esegui il meteo/wax per quella configurazione."
        )
    else:
        st.caption(
            "Tip: after choosing a run here, set the start altitude in the altitude module, "
            "then run the meteo/wax computation for that configuration."
        )
