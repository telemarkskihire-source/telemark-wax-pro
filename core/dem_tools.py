# core/dem_tools.py
# Telemark · Pro Wax & Tune — DEM locale 3×3 → pendenza & esposizione
# Espone: render_dem(T, ctx)  (alias: render)

import math
import numpy as np
import requests
import streamlit as st

UA = {"User-Agent":"telemark-wax-pro/1.0"}

# ---------- DEM 3×3 da Open-Meteo ----------
@st.cache_data(ttl=6*3600, show_spinner=False)
def dem_patch(lat: float, lon: float, spacing_m: int = 30, size: int = 3):
    """
    Scarica un mini DEM 3×3 attorno a (lat, lon).
    spacing_m ~ passo tra punti; size=3 -> griglia 3x3.
    Ritorna: {"Z": np.ndarray (size,size), "spacing_m": spacing_m} oppure None.
    """
    half = size // 2
    dlat = spacing_m / 111320.0
    dlon = spacing_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))

    lats, lons = [], []
    for j in range(size):
        for i in range(size):
            lats.append(lat + (j - half) * dlat)
            lons.append(lon + (i - half) * dlon)

    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
    }
    r = requests.get("https://api.open-meteo.com/v1/elevation", params=params, headers=UA, timeout=10)
    r.raise_for_status()
    js = r.json()
    elevs = js.get("elevation")
    if not elevs or len(elevs) != size * size:
        return None
    Z = np.array(elevs, dtype=float).reshape(size, size)
    return {"Z": Z, "spacing_m": spacing_m}

def slope_aspect_from_dem(Z: np.ndarray, spacing_m: float):
    """
    Metodo di Horn 3×3.
    Ritorna: slope_deg, slope_pct, aspect_deg (0° = Nord, senso orario).
    """
    dzdx = ((Z[0,2] + 2*Z[1,2] + Z[2,2]) - (Z[0,0] + 2*Z[1,0] + Z[2,0])) / (8.0 * spacing_m)
    dzdy = ((Z[2,0] + 2*Z[2,1] + Z[2,2]) - (Z[0,0] + 2*Z[0,1] + Z[0,2])) / (8.0 * spacing_m)

    slope_rad = math.atan(math.hypot(dzdx, dzdy))
    slope_deg = math.degrees(slope_rad)
    slope_pct = math.tan(slope_rad) * 100.0

    # aspect: 0° = Nord; positivo orario (N, NE, E, ...)
    aspect_rad = math.atan2(dzdx, dzdy)
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0

    return float(slope_deg), float(slope_pct), float(aspect_deg)

def aspect_to_compass(deg: float):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]

# ---------- UI ----------
def render_dem(T, ctx):
    """
    Pannello DEM.
    Usa ctx['lat'], ctx['lon'] se presenti; salva i risultati in session_state:
      slope_deg, slope_pct, aspect_deg, aspect_txt
    """
    lat = float(ctx.get("lat", st.session_state.get("lat", 45.831)))
    lon = float(ctx.get("lon", st.session_state.get("lon", 7.730)))

    hdr = T.get("dem_hdr", "Aspect & slope (local DEM)")
    lbl_sdeg = T.get("slope_deg", "Slope (°)")
    lbl_spct = T.get("slope_pct", "Slope (%)")
    lbl_asdir = T.get("aspect_dir", "Aspect (compass)")
    lbl_aerr = T.get("dem_err", "DEM unavailable now. Try again shortly.")

    with st.expander(hdr, expanded=False):
        left, mid, right = st.columns([1,1,1])
        with left:
            spacing = st.selectbox("Grid spacing", [20, 30, 40, 60], index=1, help="Passo tra i punti DEM (metri).")
        with mid:
            size = st.selectbox("Kernel", [3, 5], index=0, help="Dimensione griglia (3×3 o 5×5).")
        with right:
            if st.button("Aggiorna DEM", use_container_width=True):
                # forza ricalcolo invalidando la cache chiamando con param diversi (ci pensa cache ai parametri)
                pass

        try:
            dem = dem_patch(lat, lon, spacing_m=int(spacing), size=int(size))
        except Exception:
            dem = None

        if not dem:
            st.warning(lbl_aerr)
            return

        try:
            sdeg, spct, adeg = slope_aspect_from_dem(dem["Z"], dem["spacing_m"])
            atext = aspect_to_compass(adeg)

            # Persist in session_state (usato da altri moduli / badge orchestratore)
            st.session_state["slope_deg"]  = round(sdeg, 1)
            st.session_state["slope_pct"]  = int(round(spct))
            st.session_state["aspect_deg"] = int(round(adeg))
            st.session_state["aspect_txt"] = atext

            c1, c2, c3 = st.columns(3)
            c1.metric(lbl_sdeg, f"{st.session_state['slope_deg']}°")
            c2.metric(lbl_spct, f"{st.session_state['slope_pct']}%")
            c3.metric(lbl_asdir, f"{st.session_state['aspect_txt']} ({st.session_state['aspect_deg']}°)")

            with st.expander("Debug DEM", expanded=False):
                st.write("spacing_m:", dem["spacing_m"])
                st.dataframe(dem["Z"], use_container_width=True)

        except Exception as e:
            st.warning(f"{lbl_aerr}  \n\n{e}")

# alias per l’orchestratore
render = render_dem
