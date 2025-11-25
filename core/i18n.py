# core/i18n.py

L = {
    "it": {
        # --- blocco ricerca località ---
        "search_title": "1) Cerca… es. Champoluc, Plateau Rosa",
        "country": "Nazione (prefiltro ricerca)",
        "search_ph": "Cerca… es. Champoluc, Plateau Rosa",

        # --- parametri principali ---
        "ref_day": "Giorno di riferimento",
        "alt_lbl": "Altitudine pista/garà (m)",
        "blocks": "1) Finestre orarie A · B · C",
        "start": "Inizio",
        "end": "Fine",
        "horizon": "2) Orizzonte previsionale",
        "tip": "Suggerimento: < 48h → stime più affidabili",
        "fetch": "Scarica/aggiorna previsioni",

        # --- grafici meteo ---
        "temp": "Temperature",
        "prec": "Precipitazione (mm/h)",
        "radhum": "Radiazione stimata & Umidità",

        # --- sintesi blocchi ---
        "cond": "Condizioni previste:",
        "none": "—",
        "rain": "pioggia",
        "snow": "neve",
        "mixed": "mista",
        "struct": "Struttura consigliata:",
        "waxes": "Scioline suggerite:",
        "nodata": "Nessun dato nella finestra scelta.",

        # --- colonne tabella meteo ---
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

        # --- download / stato ---
        "download_csv": "Scarica CSV completo",
        "reset": "Reset",
        "last_upd": "Ultimo aggiornamento",
        "status_title": "Download & calcolo",

        # --- messaggi errore / warning ---
        "invalid_win": "La finestra {lbl} ha orari invertiti (inizio ≥ fine). Correggi per continuare.",
        "low_alt": "Quota pista molto bassa (< 300 m): controlla che sia corretta.",
        "alert": "Attenzione: condizioni molto umide/calde in finestra {lbl}. Preferire forma liquida/topcoat.",

        # --- controlli laterali ---
        "offset": "Calibrazione pista (offset termico °C)",
        "speed_chart": "Indice scorrevolezza (mini)",
        "lang": "Lingua",
        "unit": "Unità",
        "unit_c": "°C / m/s",
        "unit_f": "°F / km/h",
        "map": "Mappa (selezione)",
        "base_solid": "Base solida",
        "topcoat_lbl": "Topcoat",
        "debug": "Mostra debug",

        # --- DEM ---
        "dem_hdr": "Esposizione & pendenza (DEM locale)",
        "slope_deg": "Pendenza (°)",
        "slope_pct": "Pendenza (%)",
        "aspect_deg": "Esposizione (° da N)",
        "aspect_dir": "Esposizione (bussola)",
        "dem_err": "DEM non disponibile ora. Riprova tra poco.",
    },

    "en": {
        # --- search block ---
        "search_title": "1) Search… e.g. Champoluc, Plateau Rosa",
        "country": "Country (search prefilter)",
        "search_ph": "Search… e.g. Champoluc, Plateau Rosa",

        # --- main params ---
        "ref_day": "Reference day",
        "alt_lbl": "Slope/race altitude (m)",
        "blocks": "1) Time windows A · B · C",
        "start": "Start",
        "end": "End",
        "horizon": "2) Forecast horizon",
        "tip": "Tip: < 48h → more reliable",
        "fetch": "Fetch/update forecast",

        # --- charts ---
        "temp": "Temperatures",
        "prec": "Precipitation (mm/h)",
        "radhum": "Estimated radiation & Humidity",

        # --- blocks summary ---
        "cond": "Expected conditions:",
        "none": "—",
        "rain": "rain",
        "snow": "snow",
        "mixed": "mixed",
        "struct": "Recommended structure:",
        "waxes": "Suggested waxes:",
        "nodata": "No data in selected window.",

        # --- table columns ---
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

        # --- download / status ---
        "download_csv": "Download full CSV",
        "reset": "Reset",
        "last_upd": "Last update",
        "status_title": "Download & compute",

        # --- errors / warnings ---
        "invalid_win": "Window {lbl} has inverted times (start ≥ end). Fix to continue.",
        "low_alt": "Very low slope altitude (< 300 m): double-check.",
        "alert": "Warning: very warm/humid conditions in {lbl}. Prefer liquid/topcoat.",

        # --- sidebar controls ---
        "offset": "Track calibration (thermal offset °C)",
        "speed_chart": "Speed index (mini)",
        "lang": "Language",
        "unit": "Units",
        "unit_c": "°C / m/s",
        "unit_f": "°F / km/h",
        "map": "Map (selection)",
        "base_solid": "Base solid",
        "topcoat_lbl": "Topcoat",
        "debug": "Show debug",

        # --- DEM ---
        "dem_hdr": "Aspect & slope (local DEM)",
        "slope_deg": "Slope (°)",
        "slope_pct": "Slope (%)",
        "aspect_deg": "Aspect (° from N)",
        "aspect_dir": "Aspect (compass)",
        "dem_err": "DEM unavailable now. Try again shortly.",
    },
}
