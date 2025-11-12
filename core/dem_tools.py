import math, numpy as np, requests, streamlit as st
from .utils import UA

@st.cache_data(ttl=6*3600, show_spinner=False)
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
    r = requests.get("https://api.open-meteo.com/v1/elevation", params=params, headers=UA, timeout=10)
    r.raise_for_status()
    js = r.json()
    elevs = js.get("elevation")
    if not elevs or len(elevs) != size * size: return None
    Z = np.array(elevs, dtype=float).reshape(size, size)
    return {"Z": Z, "spacing_m": spacing_m}

def slope_aspect_from_dem(Z: np.ndarray, spacing_m: float):
    dzdx = ((Z[0,2] + 2*Z[1,2] + Z[2,2]) - (Z[0,0] + 2*Z[1,0] + Z[2,0])) / (8.0 * spacing_m)
    dzdy = ((Z[2,0] + 2*Z[2,1] + Z[2,2]) - (Z[0,0] + 2*Z[0,1] + Z[0,2])) / (8.0 * spacing_m)
    slope_rad = math.atan(math.hypot(dzdx, dzdy))
    slope_deg = math.degrees(slope_rad)
    slope_pct = math.tan(slope_rad) * 100.0
    aspect_rad = math.atan2(dzdx, dzdy)
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0
    return float(slope_deg), float(slope_pct), float(aspect_deg)

def aspect_to_compass(deg: float):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]
# --- EXPORT COMPAT ---
def render_dem(T, ctx):
    for name in ["dem_panel", "show_dem", "main", "render"]:
        fn = globals().get(name)
        if callable(fn):
            return fn(T, ctx)
    import streamlit as st
    st.markdown("**[dem]** pronto (stub).")

render = render_dem
