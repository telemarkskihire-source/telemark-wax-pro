import streamlit as st
import requests
from streamlit_searchbox import st_searchbox
from .utils import UA, concise_label, flag

# ---------- Ricerca località (veloce, filtrata per country) ----------
def _nominatim_search_factory(iso2: str):
    def _search(q: str):
        if not q or len(q) < 2: return []
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format":"json", "limit": 12, "addressdetails": 1, "countrycodes": iso2.lower()},
                headers=UA, timeout=6
            )
            r.raise_for_status()
            opts = {}
            out = []
            for it in r.json():
                addr = it.get("address",{}) or {}
                lab  = concise_label(addr, it.get("display_name",""))
                cc   = addr.get("country_code","")
                label = f"{flag(cc)}  {lab}"
                lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
                key = f"{label}|||{lat:.6f},{lon:.6f}"
                opts[key] = {"lat":lat,"lon":lon,"label":label,"addr":addr}
                out.append(key)
            st.session_state._options = opts
            return out
        except Exception:
            return []
    return _search

def nominatim_searchbox(placeholder: str, iso2: str):
    search_fn = _nominatim_search_factory(iso2)
    selected = st_searchbox(search_fn, key="place", placeholder=placeholder, clear_on_submit=False, default=None, debounce=250)
    info = None
    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
    return selected, info

# ---------- Mappa Folium con SOLO piste di sci alpino ----------
def pistes_map(lat, lon, place_label):
    try:
        from streamlit_folium import st_folium
        import folium
        from folium import TileLayer, LayerControl, Marker
        from folium.plugins import MousePosition
    except Exception:
        st.info("Mappa non disponibile in questo ambiente.")
        return

    with st.expander("Mappa piste — clicca per selezionare", expanded=True):
        m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None, control_scale=True, prefer_canvas=True, zoom_control=True)
        TileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", name="Strade", attr="© OSM", overlay=False, control=True).add_to(m)
        # overlay piste (tiles)
        TileLayer("https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png", name="Piste overlay", attr="© OpenSnowMap.org", overlay=True, control=True, opacity=0.9).add_to(m)

        # Overpass: SOLO piste alpine
        try:
            query = f"""
            [out:json][timeout:25];
            (
              way(around:{int(30*1000)},{lat},{lon})["piste:type"="downhill"];
              relation(around:{int(30*1000)},{lat},{lon})["piste:type"="downhill"];
            );
            out geom;
            """
            r = requests.post("https://overpass-api.de/api/interpreter", data=query, headers=UA, timeout=25)
            r.raise_for_status()
            data = r.json().get("elements", [])
            if data:
                feats = []
                for el in data:
                    if "geometry" not in el: continue
                    coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
                    gj = {
                        "type":"Feature",
                        "geometry":{"type":"LineString","coordinates":coords},
                        "properties":{
                            "id": el.get("id"),
                            "name": (el.get("tags") or {}).get("name",""),
                            "piste:type":"downhill"
                        }
                    }
                    feats.append(gj)
                if feats:
                    folium.GeoJson(
                        data={"type":"FeatureCollection","features":feats},
                        name="Piste alpine (Overpass)",
                        style_function=lambda f: {"color":"#1e90ff","weight":3,"opacity":0.95},
                        tooltip=folium.GeoJsonTooltip(fields=["name","piste:type"], aliases=["Nome","Tipo"])
                    ).add_to(m)
        except Exception:
            pass

        Marker([lat, lon], tooltip=place_label, icon=folium.Icon(color="lightgray")).add_to(m)
        MousePosition().add_to(m)
        LayerControl(position="bottomleft", collapsed=True).add_to(m)

        out = st_folium(m, height=430, use_container_width=True, key="map_widget", returned_objects=["last_clicked"])
        click = (out or {}).get("last_clicked") or {}
        if click:
            st.session_state["lat"] = float(click.get("lat"))
            st.session_state["lon"] = float(click.get("lng"))
            # etichetta aggiornata lasciata al modulo principale (reverse se serve)
            st.success("Coordinate aggiornate.")
            st.rerun()
