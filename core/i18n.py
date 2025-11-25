# core/i18n.py
# Testi e traduzioni per Telemark · Pro Wax & Tune

L = {
    "it": {
        # --- meta / app ---
        "app_title": "Telemark · Pro Wax & Tune",
        "lang": "Lingua",
        "unit": "Unità",
        "unit_c": "°C / m/s",
        "unit_f": "°F / km/h",

        # --- ricerca località ---
        "search_title": "1) Cerca località / stazione",
        "search_ph": "Cerca… es. Champoluc, Plateau Rosa",
        "country": "Nazione (prefiltro ricerca)",

        # --- calibrazione / offset ---
        "offset": "Calibrazione pista (offset termico °C)",

        # --- mappa / DEM ---
        "map": "Mappa (selezione)",
        "dem_hdr": "Esposizione & pendenza (DEM locale)",
        "slope_deg": "Pendenza (°)",
        "slope_pct": "Pendenza (%)",
        "aspect_deg": "Esposizione (° da N)",
        "aspect_dir": "Esposizione (bussola)",
        "dem_err": "DEM non disponibile ora. Riprova tra poco.",

        # --- meteo & finestre ---
        "ref_day": "Giorno di riferimento",
        "alt_lbl": "Altitudine pista/garà (m)",
        "blocks": "1) Finestre orarie A · B · C",
        "start": "Inizio",
        "end": "Fine",
        "horizon": "2) Orizzonte previsionale",
        "tip": "Suggerimento: < 48h → stime più affidabili",
        "fetch": "Scarica/aggiorna previsioni",
        "reset": "Reset",
        "status_title": "Download & calcolo",
        "last_upd": "Ultimo aggiornamento",
        "low_alt": "Quota pista molto bassa (< 300 m): controlla che sia corretta.",
        "invalid_win": "La finestra {lbl} ha orari invertiti (inizio ≥ fine). Correggi per continuare.",

        # --- grafici meteo ---
        "temp": "Temperature",
        "prec": "Precipitazione (mm/h)",
        "radhum": "Radiazione stimata & Umidità",
        "t_air": "T aria (°C)",
        "td": "Td (°C)",
        "rh": "UR (%)",
        "tw": "Tw (°C)",
        "we": "Vento eff (m/s)",
        "cloud": "Nuvolosità (%)",
        "sw": "SW↓ (W/m²)",
        "prp": "Prp (mm/h)",
        "ptype": "Tipo prp",
        "t_surf": "T neve surf (°C)",
        "t_top5": "T top5mm (°C)",
        "lw": "H₂O liquida (%)",
        "speed": "Indice scorrevolezza",
        "hour": "Ora",
        "lead": "⟲ lead time (h)",
        "download_csv": "Scarica CSV completo",
        "speed_chart": "Indice scorrevolezza (mini)",

        # --- sintesi blocchi ---
        "cond": "Condizioni previste:",
        "none": "—",
        "rain": "pioggia",
        "snow": "neve",
        "mixed": "mista",
        "nodata": "Nessun dato nella finestra scelta.",
        "struct": "Struttura consigliata:",
        "waxes": "Scioline suggerite:",
        "alert": "Attenzione: condizioni molto umide/calde in finestra {lbl}. Preferire forma liquida/topcoat.",
        "base_solid": "Base solida",
        "topcoat_lbl": "Topcoat",

        # --- debug ---
        "debug": "Mostra debug",
    },

    "en": {
        # --- meta / app ---
        "app_title": "Telemark · Pro Wax & Tune",
        "lang": "Language",
        "unit": "Units",
        "unit_c": "°C / m/s",
        "unit_f": "°F / km/h",

        # --- search ---
        "search_title": "1) Search resort / location",
        "search_ph": "Search… e.g. Champoluc, Plateau Rosa",
        "country": "Country (search prefilter)",

        # --- calibration / offset ---
        "offset": "Track calibration (thermal offset °C)",

        # --- map / DEM ---
        "map": "Map (selection)",
        "dem_hdr": "Aspect & slope (local DEM)",
        "slope_deg": "Slope (°)",
        "slope_pct": "Slope (%)",
        "aspect_deg": "Aspect (° from N)",
        "aspect_dir": "Aspect (compass)",
        "dem_err": "DEM unavailable now. Try again shortly.",

        # --- meteo & windows ---
        "ref_day": "Reference day",
        "alt_lbl": "Slope/race altitude (m)",
        "blocks": "1) Time windows A · B · C",
        "start": "Start",
        "end": "End",
        "horizon": "2) Forecast horizon",
        "tip": "Tip: < 48h → more reliable",
        "fetch": "Fetch/update forecast",
        "reset": "Reset",
        "status_title": "Download & compute",
        "last_upd": "Last update",
        "low_alt": "Very low slope altitude (< 300 m): double-check.",
        "invalid_win": "Window {lbl} has inverted times (start ≥ end). Fix to continue.",

        # --- charts ---
        "temp": "Temperatures",
        "prec": "Precipitation (mm/h)",
        "radhum": "Estimated radiation & Humidity",
        "t_air": "Air T (°C)",
        "td": "Td (°C)",
        "rh": "RH (%)",
        "tw": "Wet-bulb (°C)",
        "we": "Eff. wind (m/s)",
        "cloud": "Cloudiness (%)",
        "sw": "SW↓ (W/m²)",
        "prp": "Prp (mm/h)",
        "ptype": "Prp type",
        "t_surf": "Snow T surf (°C)",
        "t_top5": "Top 5mm (°C)",
        "lw": "Liquid water (%)",
        "speed": "Speed index",
        "hour": "Hour",
        "lead": "⟲ lead time (h)",
        "download_csv": "Download full CSV",
        "speed_chart": "Speed index (mini)",

        # --- block summaries ---
        "cond": "Expected conditions:",
        "none": "—",
        "rain": "rain",
        "snow": "snow",
        "mixed": "mixed",
        "nodata": "No data in selected window.",
        "struct": "Recommended structure:",
        "waxes": "Suggested waxes:",
        "alert": "Warning: very warm/humid conditions in {lbl}. Prefer liquid/topcoat.",
        "base_solid": "Base solid",
        "topcoat_lbl": "Topcoat",

        # --- debug ---
        "debug": "Show debug",
    }
}
