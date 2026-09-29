"""Ricerca su HowLongToBeat.

Usa la libreria non ufficiale `howlongtobeatpy`. HowLongToBeat non offre un'API
pubblica: se cambia il sito, la ricerca può smettere di funzionare finché la
libreria non viene aggiornata. Per questo ogni errore restituisce None e l'app
lascia sempre la possibilità di compilare i dati a mano.
"""

from __future__ import annotations

import concurrent.futures
from urllib.parse import quote_plus

TIMEOUT_SECONDI = 15


def search_url(title: str) -> str:
    """Link di ricerca, utile quando il gioco non ha ancora una pagina HLTB collegata."""
    return "https://www.google.com/search?q=" + quote_plus(f"site:howlongtobeat.com {title}")


def game_url(hltb_id: str) -> str:
    return f"https://howlongtobeat.com/game/{hltb_id}"


def _hours(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 1) if v > 0 else None


def _to_dict(entry) -> dict:
    hltb_id = str(entry.game_id) if entry.game_id not in (None, -1) else ""
    return {
        "hltb_id": hltb_id,
        "nome": entry.game_name or "",
        "anno": str(entry.release_world or ""),
        "url": entry.game_web_link or (game_url(hltb_id) if hltb_id else ""),
        "piattaforme": [p.strip() for p in (entry.profile_platforms or []) if str(p).strip()],
        "ore_storia": _hours(entry.main_story),
        "ore_extra": _hours(entry.main_extra),
        "ore_completo": _hours(entry.completionist),
        "similarita": float(entry.similarity or 0),
    }


def _search(title: str):
    from howlongtobeatpy import HowLongToBeat

    return HowLongToBeat(0.3).search(title)


def search(title: str, limit: int = 5) -> list[dict] | None:
    """Restituisce fino a `limit` risultati, [] se non trova nulla, None in caso di errore."""
    title = (title or "").strip()
    if not title:
        return []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        results = pool.submit(_search, title).result(timeout=TIMEOUT_SECONDI)
    except Exception:  # noqa: BLE001 - libreria esterna, qualsiasi errore = ricerca fallita
        return None
    finally:
        pool.shutdown(wait=False)  # non restare bloccati se HLTB non risponde
    if results is None:
        return None
    games = [r for r in results if (r.game_type or "game") == "game"] or list(results)
    games.sort(key=lambda r: r.similarity or 0, reverse=True)
    return [_to_dict(r) for r in games[:limit]]


def label(result: dict) -> str:
    parts = [result["nome"]]
    if result["anno"]:
        parts[0] += f" ({result['anno']})"
    if result["ore_storia"]:
        parts.append(f"storia {result['ore_storia']:g} h")
    if result["ore_completo"]:
        parts.append(f"completo {result['ore_completo']:g} h")
    return " · ".join(parts)
