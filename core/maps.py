# core/maps.py
from __future__ import annotations
import math, requests
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

# ---------- Overpass: fetch piste (robusto) ----------
_OVERPASS_EP = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

@st.cache_data(ttl=3*3600, show_spinner=False)
def fetch_pistes_geojson(lat: float, lon: float, dist_km: int = 30):
    """
    Cerca piste alpine (piste:type=downhill) entro dist_km.
    Ritorna FeatureCollection o {} se fallisce.
    """
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
    );
    out geom;
    """
    last_err = None
    for ep in _OVERPASS_EP:
        try:
            r = requests.post(ep, data=query.strip(), headers=UA, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                last_err = f"{ep} → {r.status_code}"
                continue
            r.raise_for_status()
            data = r.json().get("elements", [])
            feats = []
            for el in data:
                props = {
                    "id": el.get("id"),
                    "piste:type": (el.get("tags") or {}).get("piste:type", ""),
                    "name": (el.get("tags") or {}).get("name", ""),
                }
                if "geometry" in el:
                    coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
                    feats.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": props,
                    })
            return {"type": "FeatureCollection", "features": feats}
        except Exception as e:
            last_err = f"{ep} → {e}"
            continue
    # Se tutti gli endpoint falliscono:
    st.info(f"Overpass temporaneamente non disponibile. ({last_err})")
    return {"type": "FeatureCollection", "features": []}

# ---------- OSM tile singolo (fallback senza folium) ----------
@st.cache_data(ttl=6*3600, show_spinner=False)
def osm_tile(lat, lon, z=9):
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8); r.raise_for_status()
    return r.content

# ---------- Render panel ----------
def render_map(ctx: dict):
    lat = float(ctx["lat"]); lon = float(ctx["lon"])
    iso2 = ctx.get("iso2") or ""
    place_label = ctx.get("place_label", "")

    st.markdown("##### 5) Mappa (selezione) — clicca sulla mappa per selezionare")

    if HAS_FOLIUM:
        # chiave dipendente dalla posizione → forza reinit quando cambi località
        map_key = f"map_{round(lat,5)}_{round(lon,5)}_{iso2}"
        m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None,
                       control_scale=True, prefer_canvas=True, zoom_control=True)
        TileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            name="Strade", attr="© OpenStreetMap", overlay=False, control=True
        ).add_to(m)

        # Piste
        try:
            gj = fetch_pistes_geojson(lat, lon, dist_km=30)
            if gj.get("features"):
                folium.GeoJson(
                    data=gj,
                    name="Piste alpine (OSM)",
                    tooltip=folium.GeoJsonTooltip(fields=["name","piste:type"], aliases=["Nome","Tipo"]),
                    style_function=lambda f: {"color":"#3388ff","weight":3,"opacity":0.95}
                ).add_to(m)
        except Exception as e:
            st.info(f"Piste non disponibili ora: {e}")

        Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)
        MousePosition().add_to(m)
        LayerControl(position="bottomleft", collapsed=True).add_to(m)

        out = st_folium(m, height=420, use_container_width=True, key=map_key, returned_objects=["last_clicked"])
        click = (out or {}).get("last_clicked") or {}

        # Aggiorna coordinate se clicchi la mappa
        if click:
            new_lat, new_lon = float(click.get("lat")), float(click.get("lng"))
            new_pair = (round(new_lat, 5), round(new_lon, 5))
            if st.session_state.get("_last_click") != new_pair:
                st.session_state["_last_click"] = new_pair
                st.session_state["lat"] = new_lat
                st.session_state["lon"] = new_lon
                # etichetta verrà aggiornata dal reverse geocode del tuo modulo search (se lo usi)
                st.success("Posizione aggiornata dalla mappa.")
                st.rerun()
    else:
        try:
            tile = osm_tile(lat, lon, z=9)
            st.image(tile, caption="Mappa (base)", width=260)
        except Exception:
            st.info("Mappa base non disponibile al momento.")

# alias compatibili con l’orchestratore
render = render_map
show_map = render_map
map_panel = render_map
