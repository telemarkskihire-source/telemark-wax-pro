@st.cache_resource
def get_calendar_service() -> RaceCalendarService:
    def http_client_neve(url: str, params: dict | None) -> str:
        # params non usati ma tenuti per compatibilità
        if params is None:
            params = {}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.text

    fisi_committee_slugs = {}

    return RaceCalendarService(
        fis_provider=FISCalendarProvider(http_client=http_client_neve),
        fisi_provider=FISICalendarProvider(
            http_client=http_client_neve,
            committee_slugs=fisi_committee_slugs,
        ),
    )
