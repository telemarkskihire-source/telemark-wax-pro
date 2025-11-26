# core/dem_tools.py
# DEM locale tramite Open-Meteo:
# - pendenza (° e %)
# - esposizione (bussola + gradi)
# - stima ombreggiatura
# - altitudine con possibilità di override manuale (per ogni punto selezionato)

import math
import requests
import numpy as np
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/2.0"}


def dem_patch(lat: float, lon: float, spacing_m: int = 30, size: int = 3):
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
    r = requests.get(
        "https://api.open-meteo.com/v1/elevation",
        params=params,
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    js = r.json()
    elevs = js.get("elevation")
    if not elevs or len(elevs) != size * size:
        return None
    Z = np.array(elevs, dtype=float).reshape(size, size)
    return {"Z": Z, "spacing_m": spacing_m}


def slope_aspect_from_dem(Z, spacing_m):
    dzdx = (
        (Z[0, 2] + 2 * Z[1, 2] + Z[2, 2])
        - (Z[0, 0] + 2 * Z[1, 0] + Z[2, 0])
    ) / (8.0 * spacing_m)
    dzdy = (
        (Z[2, 0] + 2 * Z[2, 1] + Z[2, 2])
        - (Z[0, 0] + 2 * Z[0, 1] + Z[0, 2])
    ) / (8.0 * spacing_m)

    slope_rad = math.atan(math.hypot(dzdx, dzdy))
    slope_deg = math.degrees(slope_rad)
    slope_pct = math.tan(slope_rad) * 100.0

    aspect_rad = math.atan2(dzdx, dzdy)  # convenzione N=0
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0
    return float(slope_deg), float(slope_pct), float(aspect_deg)


def aspect_to_compass(deg: float):
    dirs = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]


def classify_shade(aspect_deg: float) -> str:
    """
    Stima molto qualitativa dell'ombreggiatura:
    - Nord, NNE, NNW -> molto ombreggiata
    - NW, NE, W, E  -> parzialmente
    - Sud, SE, SW   -> molto soleggiata
    """
    d = aspect_deg % 360
    if (315 <= d <= 360) or (0 <= d <= 45):
        return "molto ombreggiata"
    if 45 < d < 135 or 225 < d < 315:
        return "parzialmente in ombra"
    return "molto soleggiata"


def render_slope_shade_panel(T, ctx):
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))

    hdr = T.get("dem_hdr", "Esposizione & pendenza (DEM locale)")
    err_msg = T.get("dem_err", "DEM non disponibile ora. Riprova tra poco.")

    with st.expander(hdr, expanded=False):
        try:
            dem = dem_patch(lat, lon)
        except Exception:
            dem = None

        if not dem:
            st.warning(err_msg)
            return

        Z = dem["Z"]
        spacing_m = dem["spacing_m"]

        sdeg, spct, adeg = slope_aspect_from_dem(Z, spacing_m)
        compass = aspect_to_compass(adeg)
        shade_txt = classify_shade(adeg)

        # altitudine DEM al centro patch
        center_alt = float(Z[Z.shape[0] // 2, Z.shape[1] // 2])

        # chiave per override legata a lat/lon -> cambia quando cambi pista/punto
        alt_key = f"altitude_override_m_{round(lat,5)}_{round(lon,5)}"
        default_alt = float(st.session_state.get(alt_key, center_alt))

        alt = st.number_input(
            T.get("altitude_m", "Altitudine punto selezionato (m)"),
            min_value=-100.0,
            max_value=6000.0,
            value=float(round(default_alt, 1)),
            step=10.0,
        )
        st.session_state[alt_key] = alt
        ctx["altitude_m"] = alt

        c1, c2, c3 = st.columns(3)
        c1.metric(T.get("slope_deg", "Pendenza (°)"), f"{sdeg:.1f}°")
        c2.metric(T.get("slope_pct", "Pendenza (%)"), f"{int(round(spct))}%")
        c3.metric(
            T.get("aspect_dir", "Esposizione (bussola)"),
            f"{compass} ({adeg:.0f}°)",
        )

        st.caption(
            T.get("shade_txt", "Stima ombreggiatura: ") + shade_txt
        )
        st.caption(f"Altitudine DEM di riferimento (centro patch): {center_alt:.0f} m")


# alias per compatibilità
render_dem = render_slope_shade_panel
dem_panel = render_slope_shade_panel
show_dem = render_slope_shade_panel
app = render = render_slope_shade_panel
