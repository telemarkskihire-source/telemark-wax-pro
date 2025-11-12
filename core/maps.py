# core/maps.py
import math, requests
import streamlit as st

UA = {"User-Agent":"telemark-wax-pro/1.0"}

def _osm_tile(lat, lon, z=9):
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    url = f"https://tile.openstreetmap.org/{z}/{xtile}/{ytile}.png"
    r = requests.get(url, headers=UA, timeout=8); r.raise_for_status()
    return r.content

def render_map(T, ctx):
    lat = float(ctx["lat"]); lon = float(ctx["lon"])
    iso2 = ctx.get("iso2",""); place_label = ctx.get("place_label","")
    # expander APERTO come nell’originale
    with st.expander(T.get("map","Mappa")+" — clicca sulla mappa per selezionare", expanded=True):
        HAS_FOLIUM = False
        try:
            from streamlit_folium import st_folium
            import folium
            from folium import TileLayer, LayerControl, Marker
            from folium.plugins import MousePosition
            HAS_FOLIUM = True
        except Exception:
            HAS_FOLIUM = False

        if HAS_FOLIUM:
            map_key = f"map_{round(lat,5)}_{round(lon,5)}_{iso2}"
            m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None,
                           control_scale=True, prefer_canvas=True, zoom_control=True)
            TileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                      name="Strade", attr="© OSM", overlay=False, control=True).add_to(m)
            try:
                gj = fetch_pistes_geojson(lat, lon, dist_km=30)
                if gj["features"]:
                    folium.GeoJson(
                        data=gj, name="Piste alpine (OSM)",
                        tooltip=folium.GeoJsonTooltip(fields=["name","piste:type"],
                                                      aliases=["Nome","Tipo"]),
                        style_function=lambda f: {"color":"#3388ff","weight":3,"opacity":0.95}
                    ).add_to(m)
            except Exception:
                pass
            Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)
            MousePosition().add_to(m); LayerControl(position="bottomleft", collapsed=True).add_to(m)

            out = st_folium(m, height=420, use_container_width=True, key=map_key,
                            returned_objects=["last_clicked"])
            click = (out or {}).get("last_clicked") or {}
            if click:
                new_lat = float(click.get("lat")); new_lon = float(click.get("lng"))
                new_pair = (round(new_lat,5), round(new_lon,5))
                if st.session_state.get("_last_click") != new_pair:
                    st.session_state["_last_click"] = new_pair
                    st.session_state["lat"] = new_lat
                    st.session_state["lon"] = new_lon
                    # etichetta aggiornata: la imposta il chiamante (reverse nel modulo meteo/orchestratore)
                    st.toast("Posizione aggiornata dalla mappa.", icon="✅")
        else:
            try:
                tile = _osm_tile(lat,lon, z=9)
                st.image(tile, caption=T.get("map","Mappa"), width=220)
            except Exception:
                st.info("Mappa di base non disponibile ora.")

def fetch_pistes_geojson(lat:float, lon:float, dist_km:int=30):
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
      relation(around:{int(dist_km*1000)},{lat},{lon})["piste:type"="downhill"];
    );
    out geom;
    """
    r = requests.post("https://overpass-api.de/api/interpreter", data=query, headers=UA, timeout=30)
    r.raise_for_status()
    data = r.json().get("elements", [])
    feats=[]
    for el in data:
        props = {
            "id": el.get("id"),
            "piste:type": (el.get("tags") or {}).get("piste:type",""),
            "name": (el.get("tags") or {}).get("name","")
        }
        if "geometry" in el:
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
            geom = {"type":"LineString","coordinates":coords}
            feats.append({"type":"Feature","geometry":geom,"properties":props})
    return {"type":"FeatureCollection","features":feats}

# alias per orchestratore
map_panel = render_map
show_map  = render_map
app = render = render_map
