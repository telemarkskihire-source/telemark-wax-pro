def render_map(T: Dict[str, str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Disegna la mappa basata su ctx:
      - ctx["lat"], ctx["lon"]  → centro iniziale
      - ctx["marker_lat"], ["marker_lon"] → puntatore (fallback = lat/lon)
      - ctx["map_context"] → usato per separare lo stato fra pagine

    Ritorna ctx aggiornato con eventuale click sulla mappa.
    """
    # --- contesto per separare il marker fra varie pagine ---
    map_context = str(ctx.get("map_context", "default"))
    marker_lat_key = f"marker_lat_{map_context}"
    marker_lon_key = f"marker_lon_{map_context}"
    map_key = f"map_{map_context}"
    selected_piste_idx_key = f"selected_piste_idx_{map_context}"

    # --- posizione base ---
    default_lat = float(ctx.get("lat", 45.83333))
    default_lon = float(ctx.get("lon", 7.73333))

    marker_lat = float(
        st.session_state.get(marker_lat_key, ctx.get("marker_lat", default_lat))
    )
    marker_lon = float(
        st.session_state.get(marker_lon_key, ctx.get("marker_lon", default_lon))
    )

    # aggiorno subito ctx con la posizione corrente del marker
    ctx["lat"] = marker_lat
    ctx["lon"] = marker_lon
    ctx["marker_lat"] = marker_lat
    ctx["marker_lon"] = marker_lon
    st.session_state[marker_lat_key] = marker_lat
    st.session_state[marker_lon_key] = marker_lon

    # selected piste (persistente fra i rerun della stessa pagina)
    selected_idx: Optional[int] = st.session_state.get(selected_piste_idx_key, None)
    selected_dist_m: Optional[float] = ctx.get("selected_piste_distance_m")

    # ------------------------------------------------------------------
    # Checkbox per piste & fetch piste
    # ------------------------------------------------------------------
    show_pistes = st.checkbox(
        T.get("show_pistes_label", "Mostra piste sci alpino sulla mappa"),
        value=True,
        key=f"show_pistes_{map_context}",
    )

    piste_count = 0
    polylines: List[List[Tuple[float, float]]] = []
    piste_names: List[Optional[str]] = []

    if show_pistes:
        piste_count, polylines, piste_names = _fetch_downhill_pistes(
            marker_lat,
            marker_lon,
            radius_km=10.0,
        )

    st.caption(f"Piste downhill trovate: {piste_count}")

    # ------------------------------------------------------------------
    # Se ho un click salvato nello stato della mappa, lo elaboro ORA
    # prima di disegnare la mappa, così marker e highlight sono aggiornati.
    # ------------------------------------------------------------------
    prev_state = st.session_state.get(map_key)
    if isinstance(prev_state, dict):
        last_clicked = prev_state.get("last_clicked")
        if last_clicked not in (None, {}):
            try:
                click_lat = float(last_clicked.get("lat"))
                click_lon = float(last_clicked.get("lng"))
            except Exception:
                click_lat = marker_lat
                click_lon = marker_lon

            if show_pistes and polylines:
                snapped_lat, snapped_lon, idx, dist_m = _snap_to_nearest_piste_point(
                    click_lat,
                    click_lon,
                    polylines,
                    max_snap_m=400.0,
                )
            else:
                snapped_lat, snapped_lon, idx, dist_m = click_lat, click_lon, None, None

            # aggiorno marker + ctx con posizione snappata
            marker_lat = snapped_lat
            marker_lon = snapped_lon
            ctx["lat"] = marker_lat
            ctx["lon"] = marker_lon
            ctx["marker_lat"] = marker_lat
            ctx["marker_lon"] = marker_lon
            st.session_state[marker_lat_key] = marker_lat
            st.session_state[marker_lon_key] = marker_lon

            # salvo pista selezionata
            if idx is not None:
                selected_idx = idx
                st.session_state[selected_piste_idx_key] = idx
                selected_dist_m = dist_m
                ctx["selected_piste_distance_m"] = dist_m
            else:
                selected_idx = None
                st.session_state[selected_piste_idx_key] = None
                ctx["selected_piste_distance_m"] = None

    # ------------------------------------------------------------------
    # Costruisco la mappa Folium con marker e pista selezionata aggiornati
    # ------------------------------------------------------------------
    m = folium.Map(
        location=[marker_lat, marker_lon],
        zoom_start=13,
        tiles=None,
        control_scale=True,
    )

    # Base OSM
    folium.TileLayer("OpenStreetMap", name="Strade", control=True).add_to(m)

    # Satellite (Esri World Imagery)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        control=True,
    ).add_to(m)

    # piste con tooltip nome + LABEL SEMPRE VISIBILE + highlight pista selezionata
    if show_pistes and polylines:
        for i, (coords, name) in enumerate(zip(polylines, piste_names)):
            tooltip = name if name else None
            is_selected = selected_idx is not None and i == selected_idx

            line_kwargs = {
                "locations": coords,
                "weight": 5 if is_selected else 3,
                "opacity": 1.0 if is_selected else 0.9,
            }
            if is_selected:
                line_kwargs["color"] = "yellow"

            folium.PolyLine(
                tooltip=tooltip,
                **line_kwargs,
            ).add_to(m)

            # LABEL fissa al centro pista
            if name:
                mid_idx = len(coords) // 2
                label_lat, label_lon = coords[mid_idx]

                text_color = "#fde047" if is_selected else "#e5e7eb"
                font_weight = "bold" if is_selected else "normal"

                html = (
                    f'<div style="font-size:10px; color:{text_color}; '
                    f'font-weight:{font_weight}; '
                    f'text-shadow:0 0 3px #000, 0 0 5px #000;">'
                    f"{name}</div>"
                )

                folium.Marker(
                    location=[label_lat, label_lon],
                    icon=folium.DivIcon(html=html),
                ).add_to(m)

    # marker puntatore
    folium.Marker(
        location=[marker_lat, marker_lon],
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    # Render folium (il click verrà salvato in session_state[map_key]
    # e usato al prossimo rerun)
    st_folium(
        m,
        height=450,
        width=None,
        key=map_key,
    )

    # ------------------------------------------------------------------
    # Info pista selezionata sotto la mappa
    # ------------------------------------------------------------------
    if (
        show_pistes
        and polylines
        and selected_idx is not None
        and 0 <= selected_idx < len(piste_names)
    ):
        selected_name = piste_names[selected_idx] or "pista senza nome"
        ctx["selected_piste_name"] = selected_name

        if selected_dist_m is not None:
            st.markdown(
                f"**Pista selezionata:** {selected_name} "
                f"(~{selected_dist_m:.0f} m dal punto cliccato)"
            )
        else:
            st.markdown(f"**Pista selezionata:** {selected_name}")

    return ctx
