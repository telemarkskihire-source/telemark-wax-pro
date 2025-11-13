# dentro core/race_events.py
from bs4 import BeautifulSoup
from datetime import datetime

    def _parse_national_calendar_html(
        self,
        html: str,
        season: int,
        discipline: Optional[Discipline],
        category: Optional[str],
        level: Optional[str],
    ) -> List[RaceEvent]:
        """
        Parser indicativo per il calendario nazionale FISI.

        IPOTESI:
        - c'è una tabella con <table> ... <tr> ... <td>:
          [Data], [Località], [Regione/Comitato], [Disciplina], [Cat], [Livello], [Codice], [Genere], ...
        - le intestazioni potrebbero chiamarsi: "Data", "Località", "Disciplina", "Categoria", "Codice Gara", ecc.
        - dovrai adattare i nomi dei campi ai reali header della tabella FISI.
        """
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        table = soup.find("table")
        if table is None:
            return events

        # mappa nome colonna → indice
        header_row = table.find("tr")
        if not header_row:
            return events

        headers = [h.get_text(strip=True).lower() for h in header_row.find_all(["th", "td"])]

        def col_index(name_substring: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substring.lower() in h:
                    return i
            return None

        idx_date = col_index("data")
        idx_place = col_index("local")  # località
        idx_region = col_index("comit") or col_index("reg")  # comitato/regione
        idx_disc = col_index("disciplina")
        idx_cat = col_index("cat")
        idx_level = col_index("livello")
        idx_code = col_index("codice")
        idx_gender = col_index("genere")

        # se mancano le colonne base, esci
        if idx_date is None or idx_place is None or idx_code is None:
            return events

        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date]
            raw_place = cells[idx_place]
            raw_region = cells[idx_region] if idx_region is not None else ""
            raw_disc = cells[idx_disc] if idx_disc is not None else ""
            raw_cat = cells[idx_cat] if idx_cat is not None else ""
            raw_level = cells[idx_level] if idx_level is not None else ""
            raw_code = cells[idx_code]
            raw_gender = cells[idx_gender] if idx_gender is not None else ""

            # parse data: di solito formato "gg/mm/aaaa"
            try:
                d = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                # fallback: se non parse, salta
                continue

            # filtro disciplina se richiesto
            disc_enum: Optional[Discipline] = None
            if raw_disc:
                up = raw_disc.upper()
                if "SL" in up:
                    disc_enum = Discipline.SL
                elif "GS" in up or "GIG" in up:
                    disc_enum = Discipline.GS
                elif "SG" in up:
                    disc_enum = Discipline.SG
                elif "DH" in up or "DISCESA" in up:
                    disc_enum = Discipline.DH

            if discipline is not None and disc_enum is not None and disc_enum != discipline:
                continue

            # filtri cat/level se passati
            if category is not None and category.lower() not in raw_cat.lower():
                continue
            if level is not None and level.lower() not in raw_level.lower():
                continue

            # end_date = stessa data (gare 1 giorno); se trovi intervalli, puoi estenderlo
            start_date = d
            end_date = d

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc_enum,
                code=raw_code,
                name=f"{raw_disc} {raw_place}",
                nation="ITA",
                region=raw_region or None,
                place=raw_place,
                resort=None,
                start_date=start_date,
                end_date=end_date,
                category=raw_cat or None,
                level=raw_level or None,
                gender=raw_gender or None,
                source_url=self.NATIONAL_URL,
            )
            events.append(ev)

        return events

    def _parse_committee_calendar_html(
        self,
        html: str,
        season: int,
        region: Optional[str],
        discipline: Optional[Discipline],
        category: Optional[str],
        level: Optional[str],
    ) -> List[RaceEvent]:
        """
        Parser per i calendari dei comitati FISI.
        Molti comitati usano strutture simili al nazionale (tabella con Data/Località/Disciplina ecc.)
        quindi riutilizziamo la stessa logica, ma con region impostata.
        """
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        table = soup.find("table")
        if table is None:
            return events

        header_row = table.find("tr")
        if not header_row:
            return events

        headers = [h.get_text(strip=True).lower() for h in header_row.find_all(["th", "td"])]

        def col_index(name_substring: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substring.lower() in h:
                    return i
            return None

        idx_date = col_index("data")
        idx_place = col_index("local")
        idx_disc = col_index("disciplina")
        idx_cat = col_index("cat")
        idx_level = col_index("livello")
        idx_code = col_index("codice")
        idx_gender = col_index("genere")

        if idx_date is None or idx_place is None or idx_code is None:
            return events

        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date]
            raw_place = cells[idx_place]
            raw_disc = cells[idx_disc] if idx_disc is not None else ""
            raw_cat = cells[idx_cat] if idx_cat is not None else ""
            raw_level = cells[idx_level] if idx_level is not None else ""
            raw_code = cells[idx_code]
            raw_gender = cells[idx_gender] if idx_gender is not None else ""

            try:
                d = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                continue

            disc_enum: Optional[Discipline] = None
            if raw_disc:
                up = raw_disc.upper()
                if "SL" in up:
                    disc_enum = Discipline.SL
                elif "GS" in up or "GIG" in up:
                    disc_enum = Discipline.GS
                elif "SG" in up:
                    disc_enum = Discipline.SG
                elif "DH" in up or "DISCESA" in up:
                    disc_enum = Discipline.DH

            if discipline is not None and disc_enum is not None and disc_enum != discipline:
                continue

            if category is not None and category.lower() not in raw_cat.lower():
                continue
            if level is not None and level.lower() not in raw_level.lower():
                continue

            start_date = d
            end_date = d

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc_enum,
                code=raw_code,
                name=f"{raw_disc} {raw_place}",
                nation="ITA",
                region=region,
                place=raw_place,
                resort=None,
                start_date=start_date,
                end_date=end_date,
                category=raw_cat or None,
                level=raw_level or None,
                gender=raw_gender or None,
                source_url=None,  # puoi costruire l'URL del comitato se vuoi
            )
            events.append(ev)

        return events
