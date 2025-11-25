# core/maps.py
# Telemark Pro — Maps & Slopes v2 FIXED

import requests
import folium
from streamlit_folium import folium_static


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def get_ski_slopes(lat, lon, radius=15000):

    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius},{lat},{lon})["piste:type"];
      relation(around:{radius},{lat},{lon})["piste:type"];
    );
    out geom;
    """

    r = requests.post(OVERPASS_URL, data=query)
    if r.status_code != 200:
        return []

    data = r.json()
    elements = data.get("elements", [])
    slopes = []

    for el in elements:
        if "geometry" not in el:
            continue

        coords = [(p["lat"], p["lon"]) for p in el["geometry"]]

        slope = {
            "name": el.get("tags", {}).get("name", "pista"),
            "difficulty": el.get("tags", {}).get("piste:difficulty", "unknown"),
            "coords": coords
        }

        slopes.append(slope)

    return slopes


def build_map(lat, lon, slopes):

    m = folium.Map(location=[lat, lon], zoom_start=12, tiles="OpenStreetMap")

    folium.Marker(
        [lat, lon],
        tooltip="Località selezionata"
    ).add_to(m)

    color_map = {
        "easy": "green",
        "intermediate": "blue",
        "advanced": "red",
        "expert": "black",
        "unknown": "orange"
    }

    for s in slopes:
        color = color_map.get(s["difficulty"], "orange")

        folium.PolyLine(
            s["coords"],
            color=color,
            weight=4,
            tooltip=s["name"]
        ).add_to(m)

    return m
