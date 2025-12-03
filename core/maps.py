def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comportamento:
      - Usa base_lat/base_lon come centro fisso per caricare le piste (5 km).
      - base_lat/base_lon vengono impostate solo alla prima volta dalla località selezionata.
      - marker_lat/lon si muovono con:
          · click sulla mappa (snap alla pista più vicina entro MAX_SNAP_M)
          · selezione dal toogle (punto interno della pista)
      - Dopo la PRIMA selezione (click o lista), "nessuna" sparisce.
    """
    map_context = str(ctx.get("map_context", "default"))
    map_key = f"map_{map_context}"

    # layout: mappa sopra, controlli sotto
    map_container = st.container()
    controls_container = st.container()

    # -----------------------------
    # 1) Località base / centro piste (FISSO)
    # -----------------------------
    default_lat = 45.83333
    default_lon = 7.73333

    # se abbiamo già base_lat/base_lon li usiamo, altrimenti li inizializziamo da ctx["lat"/"lon"]
    base_lat = float(ctx.get("base_lat", ctx.get("lat", default_lat)))
    base_lon = float(ctx.get("base_lon", ctx.get("lon", default_lon)))

    # memorizzo nel contesto (ma NON li aggiorno più dopo)
    ctx["base_lat"] = base_lat
    ctx["base_lon"] = base_lon

    # marker corrente (fallback: località base)
    marker_lat = float(ctx.get("marker_lat", base_lat))
    marker_lon = float(ctx.get("marker_lon", base_lon))

    # stato selezione persistente
    selected_name: Optional[str] = ctx.get("selected_piste_name")
    if not isinstance(selected_name, str):
        selected_name = None

    has_selection: bool = bool(ctx.get("has_piste_selection", False))

    # -----------------------------
    # 2) Carico piste raggruppate per nome entro 5 km dal centro fisso
    # -----------------------------
    segment_count, pistes = load_pistes_grouped_by_name(base_lat, base_lon, radius_km=5.0)
    pistes_sorted = sorted(pistes, key=lambda p: p["name"].lower()) if pistes else []
    all_names = [p["name"] for p in pistes_sorted]

    # -----------------------------
    # 3) CLICK DEL RUN PRECEDENTE → selezione pista (senza cambiare centro piste)
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
                    selected_name = best_name
                    marker_lat = best_lat
                    marker_lon = best_lon
                    has_selection = True  # da ora niente più "nessuna"
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
    # 5) DISEGNO MAPPA
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

        if show_pistes and pistes_sorted:
            for piste in pistes_sorted:
                name = piste["name"]
                is_selected = (selected_name == name)

                for seg in piste["segments"]:
                    folium.PolyLine(
                        seg,
                        color="red" if is_selected else "blue",
                        weight=6 if is_selected else 3,
                        opacity=1.0 if is_selected else 0.6,
                    ).add_to(m)

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

        folium.Marker(
            [marker_lat, marker_lon],
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

        st_folium(m, height=450, key=map_key)

    st.caption(f"Segmenti piste downhill trovati: {segment_count}")

    # -----------------------------
    # 6) TOGGLE PISTE (come prima, ma senza più poter resettare dopo la prima scelta)
    # -----------------------------
    if pistes_sorted:
        if not has_selection and selected_name is None:
            option_values: List[str] = ["__NONE__"] + all_names
            label_map = {"__NONE__": "— Nessuna —"}
            label_map.update({n: n for n in all_names})
            current_val = "__NONE__"
        else:
            option_values = all_names
            label_map = {n: n for n in all_names}
            if selected_name and selected_name in all_names:
                current_val = selected_name
            else:
                current_val = all_names[0]

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

        if chosen_val != "__NONE__":
            if chosen_val in all_names:
                selected_name = chosen_val
                has_selection = True
                chosen_piste = next(
                    (p for p in pistes_sorted if p["name"] == selected_name),
                    None,
                )
                if chosen_piste:
                    marker_lat = chosen_piste["any_lat"]
                    marker_lon = chosen_piste["any_lon"]
        else:
            selected_name = None  # valido SOLO finché non hai mai selezionato nulla

    # -----------------------------
    # 7) Salvataggio stato in ctx
    # -----------------------------
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    # QUI: lat/lon per DEM = marker, ma NON toccano base_lat/base_lon (piste)
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["selected_piste_name"] = selected_name
    ctx["has_piste_selection"] = has_selection

    if selected_name:
        st.markdown(f"**Pista selezionata:** {selected_name}")
    else:
        st.markdown("**Pista selezionata:** nessuna")

    return ctx
