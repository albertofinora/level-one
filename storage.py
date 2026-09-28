"""Salvataggio dei dati.

Due backend con la stessa interfaccia:
- SheetsStore: un foglio Google, un foglio di lavoro (tab) per tabella.
- LocalStore: file CSV in una cartella, per provare l'app sul proprio PC.

Le tabelle modificate dai membri (pin, voti_proposte, hype, valutazioni)
sono "solo aggiunta": ogni invio aggiunge una riga e vale l'ultima riga di
ciascun membro. In questo modo due persone che votano nello stesso momento
non si sovrascrivono a vicenda. Le altre tabelle le modifica solo l'admin.
"""

from __future__ import annotations

import csv
import time
import uuid
from pathlib import Path

import pandas as pd

SCHEMA: dict[str, list[str]] = {
    "membri": ["member_id", "nome", "attivo"],
    "giochi": ["game_id", "titolo", "tag", "anno", "piattaforme"],
    "periodi": ["period_id", "numero", "proponente_id", "data", "stato", "opzioni", "vincitore_id"],
    "pin": ["member_id", "pin_hash", "ts"],
    "voti_proposte": ["period_id", "member_id", "scelte", "ts"],
    "hype": ["period_id", "member_id", "voto", "ts"],
    "valutazioni": [
        "period_id", "member_id", "game_id", "stato", "ore",
        "storia", "ambientazione", "gameplay", "audio", "longevita", "final",
        "commento", "ts",
    ],
}

APPEND_ONLY = {"pin", "voti_proposte", "hype", "valutazioni"}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _frame(table: str, rows: list[list[str]]) -> pd.DataFrame:
    """Costruisce un DataFrame di stringhe con le colonne dello schema."""
    cols = SCHEMA[table]
    if not rows:
        return pd.DataFrame(columns=cols, dtype=str)
    header, body = rows[0], rows[1:]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body if any(str(c).strip() for c in r)]
    df = pd.DataFrame(body, columns=header, dtype=str)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols].fillna("")


def _row_values(table: str, row: dict) -> list[str]:
    return ["" if row.get(c) is None else str(row.get(c)) for c in SCHEMA[table]]


class LocalStore:
    mode = "locale"

    def __init__(self, folder: str | Path = "data"):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        for table, cols in SCHEMA.items():
            path = self._path(table)
            if not path.exists() or path.stat().st_size == 0:
                with path.open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(cols)

    def _path(self, table: str) -> Path:
        return self.folder / f"{table}.csv"

    def read_all(self) -> dict[str, pd.DataFrame]:
        out = {}
        for table in SCHEMA:
            with self._path(table).open(newline="", encoding="utf-8") as f:
                out[table] = _frame(table, list(csv.reader(f)))
        return out

    def append(self, table: str, row: dict) -> None:
        with self._path(table).open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_row_values(table, row))

    def overwrite(self, table: str, df: pd.DataFrame) -> None:
        cols = SCHEMA[table]
        tmp = self._path(table).with_suffix(".tmp")
        df.reindex(columns=cols).fillna("").astype(str).to_csv(tmp, index=False)
        tmp.replace(self._path(table))


class SheetsStore:
    mode = "google"

    def __init__(self, service_account_info: dict, sheet_id: str):
        import gspread  # importato qui: serve solo in produzione

        client = gspread.service_account_from_dict(service_account_info)
        self.sh = client.open_by_key(sheet_id)
        existing = {ws.title: ws for ws in self.sh.worksheets()}
        self.ws = {}
        for table, cols in SCHEMA.items():
            ws = existing.get(table)
            if ws is None:
                ws = self.sh.add_worksheet(title=table, rows=100, cols=len(cols))
            if not ws.row_values(1):
                ws.update(range_name="A1", values=[cols], value_input_option="RAW")
            self.ws[table] = ws

    def read_all(self) -> dict[str, pd.DataFrame]:
        # Una sola richiesta per leggere tutte le tabelle.
        tables = list(SCHEMA)
        res = self.sh.values_batch_get([f"'{t}'" for t in tables])
        ranges = res.get("valueRanges", [])
        return {t: _frame(t, r.get("values", [])) for t, r in zip(tables, ranges)}

    def append(self, table: str, row: dict) -> None:
        self.ws[table].append_row(_row_values(table, row), value_input_option="RAW")

    def overwrite(self, table: str, df: pd.DataFrame) -> None:
        cols = SCHEMA[table]
        values = [cols] + df.reindex(columns=cols).fillna("").astype(str).values.tolist()
        ws = self.ws[table]
        if len(values) > ws.row_count:
            ws.add_rows(len(values) - ws.row_count)
        ws.update(range_name="A1", values=values, value_input_option="RAW")
        # Elimina le righe vecchie rimaste sotto la tabella nuova.
        ws.resize(rows=max(len(values), 2))
        if len(values) < 2:
            ws.batch_clear(["A2:Z2"])
