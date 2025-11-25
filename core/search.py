# core/search.py
# Ricerca località con Nominatim + streamlit_searchbox

import time
import math
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

UA = {"User-Agent": "telemark-wax-pro/1.0"}

# ---------- utility locali (duplicate di quelle nel main, ma va benissimo) ----------

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
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s


# ---------- funzione interna: chiama Nominatim ----------

def _nominatim_search(q: str, country_code: str | None, limit: int = 12):
    """
    Ritorna lista di dict {key, lat, lon, label, addr} oppure [].
    Se non trova nulla con il filtro paese, prova una volta senza filtro.
    """
    if not q or len(q.strip()) < 2:
        return []

    def _call(cc: str | None):
        params = {
            "q": q.strip(),
            "format": "json",
            "limit": limit,
            "addressdetails": 1,
        }
        if cc:
            params["countrycodes"] = cc.lower()
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=UA,
            timeout=8,
        )
        r.raise_for_status()
        return r.json()

    try:
        # prima prova con filtro paese (se presente)
        js = _call(country_code)
        if (not js) and country_code and len(q.strip()) >= 4:
            # fallback: senza filtro paese
            time.sleep(1.0)  # piccolo rispetto per Nominatim
            js = _call(None)

        out = []
        for it in js or []:
            addr = it.get("address", {}) or {}
            lab = concise_label(addr, it.get("display_name", ""))
            cc = addr.get("country_code", "")
            lab = f"{flag(cc)}  {lab}"
            lat = float(it.get("lat", 0.0))
            lon = float(it.get("lon", 0.0))
            key = f"{lab}|||{lat:.6f},{lon:.6f}"
            out.append(
                {
                    "key": key,
                    "lat": lat,
                    "lon": lon,
                    "label": lab,
                    "addr": addr,
                }
            )
        return out
    except Exception:
        return []


# ---------- API principale usata dal main ----------

def location_searchbox(
    T: dict,
    iso2: str | None = None,
    key_prefix: str = "loc",
):
    """
    Mostra una searchbox Streamlit e ritorna (lat, lon, label, addr) se l'utente
    sceglie una voce, altrimenti (None, None, None, None).

    - T: dizionario i18n (quello che usi nel main)
    - iso2: codice paese a 2 lettere (es. 'IT', 'FR', 'CH') per il pre-filtro
    - key_prefix: per non far scontrare le chiavi in session_state
    """
    options_key = f"{key_prefix}_options"

    def _search_callback(q: str):
        results = _nominatim_search(q, iso2)
        # salva le opzioni in session_state così possiamo recuperare lat/lon dopo
        st.session_state[options_key] = {r["key"]: r for r in results}
        return [r["key"] for r in results]

    selected_key = st_searchbox(
        _search_callback,
        key=f"{key_prefix}_searchbox",
        placeholder=T["search_ph"],
        clear_on_submit=False,
        default=None,
    )

    if selected_key and options_key in st.session_state:
        info = st.session_state[options_key].get(selected_key)
        if info:
            return info["lat"], info["lon"], info["label"], info["addr"]

    return None, None, None, None
