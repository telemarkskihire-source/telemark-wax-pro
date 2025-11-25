# streamlit_app.py
# Telemark · Pro Wax & Tune — versione monofile con ricerca pulita

import time
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ================== TEXTS MINIMALI (finché non rimettiamo i18n) ==================
T = {
    "lang": "Italiano",
    "country": "Paese",
    "search_ph": "Cerca località (es. Champoluc, Zermatt…) 🔍",
}

# ================== COSTANTI ==================
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

UA = {"User-Agent": "telemark-wax-pro/1.1"}

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

# ================== STILE ==================
st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

st.markdown(
    """
<style>
html, body, .stApp {
  background:#0b0f13;
  color:#e5e7eb;
}
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: 0.6rem; }
.card {
  background:#121821;
  border-radius:12px;
  border:1px solid #1f2937;
  padding: .9rem .95rem;
}
.small { font-size:.85rem; color:#9ca3af; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("Telemark · Pro Wax & Tune")
st.caption("🔍 Search: VERSIONE MONOFILE")

# ================== FUNZIONI DI SUPPORTO ==================
def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"


def concise_label(addr: dict, fallback: str) -> str:
    name = (
        addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or fallback
    )
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s


def _retry(func, attempts=3, sleep=0.5):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.6 ** i))


@st.cache_data(ttl=3600, show_spinner=False)
def nominatim_search_api(q: str, iso2: str):
    r = _retry(
        lambda: requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "json",
                "limit": 8,
                "addressdetails": 1,
                "countrycodes": iso2.lower() if iso2 else None,
            },
            headers=UA,
            timeout=8,
        )
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600, show_spinner=False)
def openmeteo_geocode_api(q: str, iso2: str):
    r = _retry(
        lambda: requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": q,
                "language": "it",
                "count": 8,
                "format": "json",
                "filter": "country",
                "country": iso2.upper() if iso2 else None,
            },
            headers=UA,
            timeout=8,
        )
    )
    r.raise_for_status()
    return r.json()


def _options_from_nominatim(js):
    out = []
    for it in js or []:
        addr = it.get("address", {}) or {}
        base = concise_label(addr, it.get("display_name", ""))

        cc = (addr.get("country_code") or "").upper()
        emoji = flag(cc)
        label = f"{emoji}  {base}"  # SOLO TESTO, niente lat/lon

        lat = float(it.get("lat", 0.0))
        lon = float(it.get("lon", 0.0))

        out.append(
            {
                "label": label,
                "lat": lat,
                "lon": lon,
                "source": "osm",
            }
        )
    return out


def _options_from_openmeteo(js):
    out = []
    for it in (js or {}).get("results", []) or []:
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
            }
        )
    return out


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


# ================== UI: PAESE + SEARCHBOX ==================
st.markdown("#### 🌍 Località")

country_name = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0)
iso2 = COUNTRIES[country_name]

st.session_state.setdefault("_search_options_monofile", {})

def provider(query: str):
    query = (query or "").strip()
    if len(query) < 2:
        return []

    # 0) alias interni (Champoluc, Zermatt)
    alias_hit = _alias_match(query)
    if alias_hit is not None:
        label = alias_hit["label"]
        st.session_state["_search_options_monofile"] = {label: alias_hit}
        return [label]

    # 1) Nominatim + 2) OpenMeteo
    try:
        js1 = nominatim_search_api(query, iso2)
        opts1 = _options_from_nominatim(js1)
    except Exception:
        opts1 = []

    try:
        js2 = openmeteo_geocode_api(query, iso2)
        opts2 = _options_from_openmeteo(js2)
    except Exception:
        opts2 = []

    merged = []
    seen_labels = set()
    for src in (opts1 + opts2):
        lbl = src["label"]
        if lbl in seen_labels:
            continue
        seen_labels.add(lbl)
        merged.append(src)

    st.session_state["_search_options_monofile"] = {it["label"]: it for it in merged}
    return [it["label"] for it in merged]

selected_label = st_searchbox(
    provider,
    key="place_monofile",  # chiave nuova ⇒ nessuna cache vecchia
    placeholder=T["search_ph"],
    clear_on_submit=False,
    default=None,
)

selected_info = None
if selected_label and selected_label in st.session_state["_search_options_monofile"]:
    selected_info = st.session_state["_search_options_monofile"][selected_label]
    st.session_state["lat"] = selected_info["lat"]
    st.session_state["lon"] = selected_info["lon"]
    st.session_state["place_label"] = selected_label
    st.session_state["place_source"] = selected_info["source"]

# Default Champoluc se nessuna selezione
if selected_info is None and "lat" not in st.session_state:
    st.session_state["lat"] = 45.83333
    st.session_state["lon"] = 7.73333
    st.session_state["place_label"] = "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT"
    st.session_state["place_source"] = "default"

# ================== RIEPILOGO LOCALITÀ ==================
if "lat" in st.session_state:
    st.markdown(
        f"""
<div class="card">
  <div class="small">Località selezionata</div>
  <strong>{st.session_state['place_label']}</strong>
</div>
""",
        unsafe_allow_html=True,
    )
