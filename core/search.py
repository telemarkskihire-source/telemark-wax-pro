# core/search.py
# Ricerca località per Telemark · Pro Wax & Tune
# - Open-Meteo geocoding (con quota)
# - filtro quota > 1000 m
# - alias Telemark (Champoluc, Zermatt)
# - niente lat/lon nelle label

import time
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

VERSION = "telemark-search-v3"

# ---------- Paesi (prefiltro) ----------
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

UA = {"User-Agent": "telemark-wax-pro/2.0"}

# Località al di sotto di questa quota vengono scartate
MIN_ELEVATION_M = 1000.0

# ---------- Alias interni Telemark ----------
ALIASES = [
    {
        "aliases": ["cham", "champo", "champol", "champolu", "champoluc"],
        "label": "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT",
        "lat": 45.83333,
        "lon": 7.73333,
        "source": "alias",
    },
    {
        "aliases": ["zerm", "zermat", "zermatt"],
        "label": "🇨🇭  Zermatt, Vallese — CH",
        "lat": 46.02072,
        "lon": 7.74912,
        "source": "alias",
    },
]


# ---------- Utilità ----------
def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"


def _retry(func, attempts=3, sleep=0.5):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.6 ** i))


# ---------- Open-Meteo geocoding ----------
@st.cache_data(ttl=60 * 60, show_spinner=False)
def openmeteo_geocode_api(q: str, iso2: str | None):
    params = {
        "name": q,
        "language": "it",
        "count": 20,
        "format": "json",
    }
    if iso2:
        params["country"] = iso2.upper()
        params["filter"] = "country"

    r = _retry(
        lambda: requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
            headers=UA,
            timeout=8,
        )
    )
    r.raise_for_status()
    return r.json()


def _options_from_openmeteo(js):
    out = []
    for it in (js or {}).get("results", []) or []:
        elev = it.get("elevation")

        # scarta risultati senza quota o sotto soglia
        drop = False
        if elev is None:
            drop = True
        else:
            try:
                if float(elev) < MIN_ELEVATION_M:
                    drop = True
            except Exception:
                drop = True

        if drop:
            continue

        cc = (it.get("country_code") or "").upper()
        name = it.get("name") or ""
        admin1 = it.get("admin1") or it.get("admin2") or ""
        base = f"{name}, {admin1}".strip().replace(" ,", ",")
        emoji = flag(cc)
        label = f"{emoji}  {base} — {cc}"

        lat = float(it.get("latitude", 0.0))
        lon = float(it.get("longitude", 0.0))

        out.append(
            {
                "label": label,
                "lat": lat,
                "lon": lon,
                "source": "om",
                "elevation": elev,
            }
        )
    return out


# ---------- UI helpers ----------
def country_selectbox(T):
    sel = st.selectbox(
        T["country"],
        list(COUNTRIES.keys()),
        index=0,
        key="country_sel",
    )
    return COUNTRIES[sel]


def _alias_match(query: str):
    q = (query or "").strip().lower()
    if not q:
        return None

    for place in ALIASES:
        for alias in place["aliases"]:
            a = alias.lower()
            if q.startswith(a) or a.startswith(q) or a in q:
                return {
                    "label": place["label"],
                    "lat": place["lat"],
                    "lon": place["lon"],
                    "source": place["source"],
                }
    return None


def location_searchbox(T, iso2: str | None):
    """
    Renderizza lo searchbox e salva la selezione in st.session_state:
      - lat, lon
      - place_label, place_source
    Ritorna il dict della selezione (o None).
    """
    st.session_state.setdefault("_search_options", {})

    def provider(query: str):
        query = (query or "").strip()
        if len(query) < 2:
            return []

        # blocco città inutili (Roma & co.)
        blacklist = {
            "roma",
            "rome",
            "milano",
            "napoli",
            "genova",
            "paris",
            "london",
        }
        if query.lower() in blacklist:
            return []

        # 0) Alias Telemark
        alias_hit = _alias_match(query)
        if alias_hit is not None:
            label = alias_hit["label"]
            st.session_state["_search_options"] = {label: alias_hit}
            return [label]

        # 1) Open-Meteo (solo località con quota >= MIN_ELEVATION_M)
        try:
            js = openmeteo_geocode_api(query, iso2 or "")
            opts = _options_from_openmeteo(js)
        except Exception:
            opts = []

        st.session_state["_search_options"] = {it["label"]: it for it in opts}
        return [it["label"] for it in opts]

    default_label = st.session_state.get("place_label")

    selected_label = st_searchbox(
        provider,
        key="place",
        placeholder=T["search_ph"],
        clear_on_submit=False,
        default=default_label,
    )

    if selected_label and selected_label in st.session_state["_search_options"]:
        info = st.session_state["_search_options"][selected_label]
        st.session_state["lat"] = info["lat"]
        st.session_state["lon"] = info["lon"]
        st.session_state["place_label"] = selected_label
        st.session_state["place_source"] = info["source"]
        return info

    # default (Champoluc) la prima volta
    if "lat" not in st.session_state:
        st.session_state["lat"] = 45.83333
        st.session_state["lon"] = 7.73333
        st.session_state[
            "place_label"
        ] = "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT"
        st.session_state["place_source"] = "default"
        return {
            "lat": st.session_state["lat"],
            "lon": st.session_state["lon"],
            "label": st.session_state["place_label"],
            "source": st.session_state["place_source"],
        }

    return None


def get_current_selection():
    if "lat" in st.session_state and "place_label" in st.session_state:
        return {
            "lat": float(st.session_state["lat"]),
            "lon": float(st.session_state["lon"]),
            "label": st.session_state["place_label"],
            "source": st.session_state.get("place_source", "state"),
        }
    return None
