from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import math
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# raggio massimo per lo snap dalla mappa alla pista (in metri)
MAX_SNAP_M = 150.0


# ------------------------------------------------------------
# Overpass – carica piste UNA VOLTA per località di partenza
# ------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def load_pistes_for_location(
    base_lat: float,
    base_lon: float,
    radius_km: float = 5.0,  # raggio ridotto a 5 km
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Scarica le piste downhill (piste:type=downhill) intorno a (base_lat, base_lon)
    entro radius_km. Raggruppa i segmenti con lo stesso nome.

    Ritorna:
      - numero di segmenti originali trovati
      - lista di piste raggruppate, ciascuna come:
        {
          "name": str,
          "segments": List[List[Tuple[lat, lon]]],
          "any_lat": float,  # un punto della pista (per centrare il marker)
          "any_lon": float,
        }
    """
    radius_m = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way["piste:type"="downhill"](around:{radius_m},{base_lat},{base_lon});
      relation["piste:type"="downhill"](around:{radius_m},{base_lat},{base_lon});
    );
    (._;>;);
    out body;
    """

    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data=query.encode("utf-8"),
            headers=UA,
            timeout=25,
        )
        r.raise_for_status()
        js = r.json()
    except Exception:
        return 0, []

    elements = js.get("elements", [])
    nodes = {el["id"]: el for el in elements if el.get("type") == "node"}

    # segmenti grezzi
    raw_segments: List[Tuple[Optional[str], List[Tuple[float, float]]]] = []

    def get_name(tags: Dict[str, Any]) -> Optional[str]:
        if not tags:
            return None
        for k in ("name", "piste:name", "ref"):
            if k in tags:
                val = str(tags[k]).strip()
                if val:
                    return val
        return None

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags") or {}
        if tags.get("piste:type") != "downhill":
            continue

        seg_coords: List[Tuple[float, float]] = []

        if el["type"] == "way":
            for nid in el.get("nodes", []):
                nd = nodes.get(nid)
                if nd:
                    seg_coords.append((nd["lat"], nd["lon"]))
        else:  # relation
            for mem in el.get("members", []):
                if mem.get("type") != "way":
                    continue
                wid = mem.get("ref")
                way = next(
                    (e for e in elements if e.get("type") == "way" and e.get("id") == wid),
                    None,
                )
                if not way:
                    continue
                for nid in way.get("nodes", []):
                    nd = nodes.get(nid)
                    if nd:
                        seg_coords.append((nd["lat"], nd["lon"]))

        if len(seg_coords) >= 2:
            nm = get_name(tags)
            raw_segments.append((nm, seg_coords))

    segment_count = len(raw_segments)

    # ----------------------------------------
    # Raggruppo per nome:
    # - se nome presente -> gruppo per quel nome
    # - se nome mancante -> ogni segmento è una pista separata "Pista senza nome N"
    # ----------------------------------------
    grouped: Dict[str, List[List[Tuple[float, float]]]] = {}
    unnamed_counter = 1

    for name, coords in raw_segments:
        if name is None or not name.strip():
            key = f"Pista senza nome {unnamed_counter}"
            unnamed_counter += 1
        else:
            key = name.strip()
        grouped.setdefault(key, []).append(coords)

    pistes: List[Dict[str, Any]] = []
    for name, segs in grouped.items():
        any_lat, any_lon = segs[0][0]
        pistes.append(
            {
                "name": name,
                "segments": segs,
                "any_lat": any_lat,
                "any_lon": any_lon,
            }
        )

    return segment_count, pistes


# ------------------------------------------------------------
# Distanza per trovare la pista più vicina al click
# ------------------------------------------------------------
def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ------------------------------------------------------------
# RENDER MAP – selezione da lista + selezione da click (che aggiorna il toggle)
# ------------------------------------------------------------
def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comportamento:
      - Usa ctx["lat"], ctx["lon"] come località base.
      - Mostra mappa Folium con piste downhill in un raggio di 5 km (raggruppate per nome).
      - Selezione pista:
          · da lista (selectbox, con "__NONE__" solo prima scelta globale)
          · da click sulla mappa (snap alla pista più vicina entro MAX_SNAP_M).
      - Dopo la PRIMA selezione (da lista o da click), l'opzione "nessuna" sparisce.
      - Pista selezionata:
          · tutti i segmenti con quel nome sono evidenziati in rosso
          · il marker è posizionato su un punto della pista
    """
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"

    # --- layout: mappa sopra, controlli sotto ---
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base (dal contesto app)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    base_lat = float(ctx.get("lat", default_lat))
    base_lon = float(ctx.get("lon", default_lon))
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker:
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # pista selezionata (per nome)
    selected_name: Optional[str] = ctx.get("selected_piste_name")
    if not isinstance(selected_name, str):
        selected_name = None

    # -----------------------------
    # 2) Carico piste (raggruppate per nome) entro 5 km
    # -----------------------------
    segment_count, pistes = load_pistes_for_location(base_lat, base_lon, radius_km=5.0)
    pistes_sorted = sorted(pistes, key=lambda p: p["name"].lower()) if pistes else []
    all_names = [p["name"] for p in pistes_sorted]

    # -----------------------------
    # 3) GESTIONE CLICK del run PRECEDENTE
    #    (Se hai cliccato sulla mappa, qui decidiamo se agganciare a una pista)
    # -----------------------------
    prev_state = st.session_state.get(map_key)
    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked and pistes_sorted:
            try:
                c_lat = float(last_clicked["lat"])
                c_lon = float(last_clicked["lng"])

                best_name = None
                best_lat = c_lat
                best_lon = c_lon
                best_d = float("inf")

                for piste in pistes_sorted:
                    for seg in piste["segments"]:
                        for lat, lon in seg:
                            d = _dist_m(c_lat, c_lon, lat, lon)
                            if d < best_d:
                                best_d = d
                                best_name = piste["name"]
                                best_lat = lat
                                best_lon = lon

                if best_name is not None and best_d <= MAX_SNAP_M:
                    # Click valido: seleziono la pista e sposto marker
                    selected_name = best_name
                    marker_lat = best_lat
                    marker_lon = best_lon
            except Exception:
                pass

    # -----------------------------
    # 4) Checkbox mostra piste
    # -----------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    # -----------------------------
    # 5) DISEGNO MAPPA con stato (selected_name + marker)
    # -----------------------------
    with map_container:
        m = folium.Map(
            location=[marker_lat, marker_lon],
            zoom_start=13,
            tiles=None,
            control_scale=True,
        )
        folium.TileLayer("OpenStreetMap", name="Strade", control=True).add_to(m)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
            control=True,
        ).add_to(m)

        # piste + nomi
        if show_pistes and pistes_sorted:
            for piste in pistes_sorted:
                name = piste["name"]
                is_selected = (selected_name == name)

                # tutti i segmenti della stessa pista
                for seg in piste["segments"]:
                    folium.PolyLine(
                        seg,
                        color="red" if is_selected else "blue",
                        weight=6 if is_selected else 3,
                        opacity=1.0 if is_selected else 0.6,
                    ).add_to(m)

                # etichetta al centro del primo segmento
                if piste["segments"]:
                    seg0 = piste["segments"][0]
                    mid_idx = len(seg0) // 2
                    label_lat, label_lon = seg0[mid_idx]
                    folium.Marker(
                        location=[label_lat, label_lon],
                        icon=folium.DivIcon(
                            html=(
                                f"<div style='"
                                "font-size:10px;"
                                "color:white;"
                                "text-shadow:0 0 3px black;"
                                "white-space:nowrap;"
                                "background:rgba(0,0,0,0.3);"
                                "padding:1px 3px;"
                                "border-radius:3px;"
                                f"'>{name}</div>"
                            )
                        ),
                    ).add_to(m)

        # marker (località base o pista selezionata / click)
        folium.Marker(
            [marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        # mappa interattiva (pan/zoom + click per selezione pista)
        st_folium(m, height=450, key=map_key)

    st.caption(f"Segmenti piste downhill trovati: {segment_count}")

    # -----------------------------
    # 6) TOGGLE PISTE (selectbox in expander)
    #    - se selected_name è None: "__NONE__" + lista piste
    #    - se selected_name esiste: SOLO piste, niente "__NONE__"
    #    E se la selezione è avvenuta da click, QUI il toggle si aggiorna
    # -----------------------------
    if pistes_sorted:
        if selected_name is None:
            option_values: List[str] = ["__NONE__"] + all_names
            label_map = {"__NONE__": "— Nessuna —"}
            label_map.update({n: n for n in all_names})
            current_val = "__NONE__"
        else:
            option_values = all_names
            label_map = {n: n for n in all_names}
            current_val = selected_name if selected_name in all_names else all_names[0]

        def _fmt(val: str) -> str:
            return label_map.get(val, val)

        try:
            default_index = option_values.index(current_val)
        except ValueError:
            default_index = 0

        with controls_container:
            with st.expander(
                T.get("piste_select_label", "Seleziona pista dalla lista"),
                expanded=False,
            ):
                chosen_val: str = st.selectbox(
                    "Pista",
                    options=option_values,
                    index=default_index,
                    format_func=_fmt,
                    key=f"piste_select_{map_context}",
                )

        # aggiorno selezione SOLO se non è "__NONE__"
        if chosen_val != "__NONE__":
            if chosen_val in all_names:
                selected_name = chosen_val
                # posiziono il marker su un punto della pista (any_lat/lon)
                chosen_piste = next(
                    (p for p in pistes_sorted if p["name"] == selected_name),
                    None,
                )
                if chosen_piste:
                    marker_lat = chosen_piste["any_lat"]
                    marker_lon = chosen_piste["any_lon"]
        else:
            # "__NONE__" solo finché non si sceglie una pista
            selected_name = None

    # -----------------------------
    # 7) Salvo stato in ctx
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected_name

    # testo esplicito pista selezionata
    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
    else:
        st.markdown("**Pista selezionata:** nessuna")

    return ctx
