# core/fis_calendar.py
# Lettura calendario FIS tramite proxy Telemark

import requests

PROXY_URL = "https://www.telemarkskihire.com/api/fis_proxy.php"

def get_fis_calendar(season: int, discipline=None, gender=None):
    params = {
        "season": season,
        "discipline": discipline or "",
        "gender": gender or "",
    }

    r = requests.get(PROXY_URL, params=params, timeout=10)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, list):
        return []

    return data
