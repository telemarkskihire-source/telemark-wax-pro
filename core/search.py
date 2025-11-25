# core/search.py
# Telemark Pro — Search v2 FIXED (quota > 1000 + alias Telemark + anti-Roma)

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

VERSION = "search-v2-2025-11-26"

UA = {"User-Agent": "telemark-wax-pro/2.0"}
MIN_ELEVATION = 1000  # metri

COUNTRIES = {
    "Italia": "IT",
    "Svizzera": "CH",
    "Francia": "FR",
    "Austria": "AT",
    "Germania": "DE",
    "Spagna": "ES",
    "Norvegia": "NO",
    "Svezia": "SE",
}

# Alias manuale per Telemark
ALIASES = [
    {
        "aliases": ["cham", "champo", "champoluc", "champ"],
        "label": "🇮🇹 Champoluc-Champlan, Valle d'Aosta — IT",
        "lat": 45.8333,
        "lon": 7.7333,
        "elevation": 1560,
    },
    {
        "aliases": ["zerm", "zermatt", "matz"],
        "label": "🇨🇭 Zermatt — CH",
        "lat": 46.0207,
        "lon": 7.7491,
        "elevation": 1600,
    },
]


def flag(cc):
    try:
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except:
        return ""


def _nominatim(query, country_code):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "countrycodes": country_code.lower(),
        "format": "json",
        "limit": 50,
        "extratags": 1
    }

    r = requests.get(url, params=params, headers=UA, timeout=10)
    if r.status_code != 200:
        return []

    results = r.json()

    filtered = []

    for r in results:
        if "lat" not in r or "lon" not in r:
            continue

        lat = float(r["lat"])
        lon = float(r["lon"])
        name = r.get("display_name", "")
        type_ = r.get("type", "")

        elev = None
        if "extratags" in r and "ele" in r["extratags"]:
            try:
                elev = float(r["extratags"]["ele"])
            except:
                elev = None

        if elev is None and any(w in name.lower() for w in ["roma", "paris", "milano", "torino", "london"]):
            continue

        if elev is not None and elev < MIN_ELEVATION:
            continue

        filtered.append({
            "label": f"{name}",
            "lat": lat,
            "lon": lon,
            "elevation": elev if elev else "n/a"
        })

    return filtered


def location_searchbox(country_choice="Italia"):

    cc = COUNTRIES.get(country_choice, "IT")

    def search_func(query):

        query = query.strip().lower()

        results = []

        for entry in ALIASES:
            if any(query.startswith(a) for a in entry["aliases"]):
                results.append({
                    "label": entry["label"],
                    "lat": entry["lat"],
                    "lon": entry["lon"],
                    "elevation": entry["elevation"],
                    "source": "alias"
                })

        if len(query) >= 3:
            places = _nominatim(query, cc)
            for p in places:
                results.append({**p, "source": "nominatim"})

        return [r["label"] for r in results[:15]]

    selected = st_searchbox(
        search_func,
        label="📍 Cerca località (quota > 1000m)",
        key="location_searchbox"
    )

    if not selected:
        return None

    for a in ALIASES:
        if selected == a["label"]:
            return a

    n = _nominatim(selected, cc)
    if n:
        return n[0]

    return None
