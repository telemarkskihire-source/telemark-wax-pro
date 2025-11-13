class FISCalendarProvider(BaseCalendarProvider):
    """
    Provider per i calendari FIS (WC, EC, FIS, ENL, ecc.)
    usando direttamente la pagina DB 'calendar-results.html'.
    """

    federation = Federation.FIS

    BASE_URL = "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"

    def __init__(
        self,
        http_client: Optional[Callable[[str, dict], str]] = None,
    ) -> None:
        """
        http_client: callable opzionale per effettuare richieste.
        Firma attesa: (url: str, params: dict) -> str (HTML).
        """
        self.http_client = http_client

    def fetch_events(
        self,
        season: int,
        discipline: Optional[Discipline] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,  # non usato per FIS
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        Chiamata real-time al calendario FIS.

        Nota: FIS richiede almeno un filtro (category/place/nation/codex),
        quindi qui imponiamo SEMPRE un categorycode:

        - se 'level' passato → usiamo quello (es. 'WC', 'EC', 'FIS')
        - altrimenti default 'WC' (World Cup)
        """
        if self.http_client is None:
            raise NotImplementedError(
                "FISCalendarProvider.fetch_events: manca http_client."
            )

        # mapping level -> categorycode FIS
        if level:
            categorycode = level.upper()
        elif category:
            categorycode = category.upper()
        else:
            categorycode = "WC"  # default: World Cup

        disciplinecode = "" if discipline is None else discipline.value

        params = {
            "categorycode": categorycode,
            "disciplinecode": disciplinecode,
            "eventselection": "",         # tutte
            "gendercode": "",
            "nationcode": "" if nation is None else nation,
            "place": "",
            "racecodex": "",
            "racedate": "",
            "saveselection": "-1",
            "seasoncode": str(season),
            "seasonmonth": f"X-{season}",  # "all months" pattern usato da FIS
            "seasonselection": "",
            "sectorcode": "AL",           # Sci alpino
        }

        html = self.http_client(self.BASE_URL, params)

        return self._parse_fis_calendar_html(
            html=html,
            season=season,
            discipline=discipline,
            category=categorycode,
        )

    # ---------- PARSER HTML FIS ----------

    def _parse_fis_calendar_html(
        self,
        html: str,
        season: int,
        discipline: Optional[Discipline],
        category: Optional[str],
    ) -> List[RaceEvent]:
        """
        Parser per la tabella 'Calendar & Results' FIS.

        Colonne (tipico):
        - Date
        - Place
        - Place, Category, Event
        - NSA
        - Disc.
        - Category & Event
        - Gender
        - ...
        (e a volte Codex)
        """
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        table = soup.find("table")
        if table is None:
            return events

        header_row = table.find("tr")
        if not header_row:
            return events

        headers = [
            h.get_text(strip=True).lower()
            for h in header_row.find_all(["th", "td"])
        ]

        def col_index(name_substring: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substring.lower() in h:
                    return i
            return None

        idx_date = col_index("date")
        idx_place = col_index("place")
        idx_nsa = col_index("nsa")
        idx_cat_evt = (
            col_index("category & event")
            or col_index("place, category, event")
            or col_index("category")
        )
        idx_gender = col_index("gender")
        idx_codex = col_index("codex")

        if idx_date is None or idx_place is None:
            return events

        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date]
            raw_place = cells[idx_place]
            raw_nsa = cells[idx_nsa] if idx_nsa is not None else ""
            raw_cat_evt = cells[idx_cat_evt] if idx_cat_evt is not None else ""
            raw_gender = cells[idx_gender] if idx_gender is not None else ""
            raw_codex = cells[idx_codex] if idx_codex is not None else ""

            # --- parse data: es. "26-27 Oct 2024" → prendo il primo giorno ---
            parts = raw_date.split()
            if len(parts) >= 3:
                day_token = parts[0].split("-")[0]  # "26-27" → "26"
                month_token = parts[1]
                year_token = parts[2]
                try:
                    d = datetime.strptime(
                        f"{day_token} {month_token} {year_token}", "%d %b %Y"
                    ).date()
                except ValueError:
                    continue
            else:
                continue

            # --- disciplina da 'cat_evt' (es. "WC 2xSL", "FIS GS", ecc.) ---
            disc_enum: Optional[Discipline] = None
            up_evt = raw_cat_evt.upper()

            if " SL" in up_evt or up_evt.endswith("SL"):
                disc_enum = Discipline.SL
            elif " GS" in up_evt or "G.S" in up_evt or up_evt.endswith("GS"):
                disc_enum = Discipline.GS
            elif " SG" in up_evt or up_evt.endswith("SG"):
                disc_enum = Discipline.SG
            elif " DH" in up_evt or "DOWNHILL" in up_evt or up_evt.endswith("DH"):
                disc_enum = Discipline.DH

            # filtro per disciplina richiesta
            if discipline is not None and disc_enum is not None and disc_enum != discipline:
                continue

            # livello/categoria (WC / EC / FIS / ENL / NJR / CIT ...)
            level = None
            for code in ["WC", "EC", "FIS", "ENL", "NJR", "CIT", "NC"]:
                if code in up_evt:
                    level = code
                    break

            # se non abbiamo codex, inventiamo un id stabile
            code = raw_codex or f"{season}-{raw_place}-{raw_cat_evt}-{raw_date}"

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc_enum,
                code=code,
                name=raw_cat_evt or raw_place,
                nation=raw_nsa or None,
                region=None,
                place=raw_place,
                resort=None,
                start_date=d,
                end_date=d,
                category=category or level,
                level=level,
                gender=raw_gender or None,
                source_url=self.BASE_URL,
            )
            events.append(ev)

        return events
