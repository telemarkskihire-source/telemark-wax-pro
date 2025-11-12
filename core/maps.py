# core/maps.py
# Mappa Folium + click che aggiorna lat/lon/label e rimette alt_sync in AUTO

from __future__ import annotations

import math
import requests
import streamlit as st

# Folium opzionale
HAS_FOLIUM = False
try:
    from streamlit_folium import st_folium
    import folium
    from folium import TileLayer, LayerControl, Marker
    from folium.plugins import MousePosition
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False


UA = {"User-Agent": "telemark-wax-pro/1.0"}


def _retry(func, attempts: int = 2, sleep: float = 0.8):
    import time

    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.5**i))


def reverse_geocode(lat: float, lon: float) -> str:
    try:
        def go():
            return requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lon, "zoom": 12, "addressdetails": 1},
                headers=UA,
                timeout=8,
            )

        r = _retry(go)
        r.raise_for_status()
        j = r.json()
        addr = j.get("address", {}) or {}
        # etichetta concisa
        name = (
            addr.get("neighbourhood")
            or addr.get("hamlet")
            or addr.get("village")
            or addr.get("town")
            or addr.get("city")
            or j.get("display_name", "")
        )
        admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
        cc = (addr.get("country_code") or "").upper()
        core = ", ".join([p for p in [name, admin1] if p])
        flag = chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1])) if len(cc) == 2 else "🏳️"
        return f"{flag}  {core} — {cc}" if cc else core
    except Exception:
        return f"{lat:.5f}, {lon:.5f}"


def osm_tile(lat: float, lon: float, z: int = 9) -> bytes | None:
    try:
        n = 2**z
        xtile = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
        url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
        r = requests.get(url, headers=UA, timeout=8)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def render_map(T: dict, ctx: dict):
    lat = float(ctx["lat"])
    lon = float(ctx["lon"])
    iso2 = ctx.get("iso2", "IT")
    place_label = ctx.get("place_label", f"📍 {lat:.5f}, {lon:.5f}")

    if HAS_FOLIUM:
        with st.expander(T["map"] + " — clicca sulla mappa per selezionare", expanded=True):
            map_key = f"map_{round(lat, 5)}_{round(lon, 5)}_{iso2}"
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
                attr="© OSM",
                overlay=False,
                control=True,
            ).add_to(m)

            Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)
            MousePosition().add_to(m)
            LayerControl(position="bottomleft", collapsed=True).add_to(m)

            out = st_folium(m, height=420, use_container_width=True, key=map_key, returned_objects=["last_clicked"])
            click = (out or {}).get("last_clicked") or {}

            if click:
                new_lat = float(click.get("lat"))
                new_lon = float(click.get("lng"))
                new_pair = (round(new_lat, 5), round(new_lon, 5))
                if st.session_state.get("_last_click") != new_pair:
                    st.session_state["_last_click"] = new_pair
                    st.session_state["lat"] = new_lat
                    st.session_state["lon"] = new_lon
                    st.session_state["place_label"] = reverse_geocode(new_lat, new_lon)

                    # IMPORTANTE: ritorna in modalità AUTO quando si clicca sulla mappa
                    st.session_state["alt_sync_mode"] = "auto"

                    st.success(f"Posizione aggiornata: {st.session_state['place_label']}")
                    st.rerun()
    else:
        try:
            tile = osm_tile(lat, lon, z=9)
            if tile:
                st.image(tile, caption=T["map"], width=220)
        except Exception:
            pass


# alias
render = render_map
