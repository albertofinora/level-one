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


# ---------------------------------------------------------------- generi
#
# I risultati di ricerca non contengono i generi: stanno nella pagina del singolo
# gioco. Qui la pagina viene scaricata e letta "al meglio": prima i dati
# strutturati che la pagina incorpora (__NEXT_DATA__), poi il testo visibile
# ("Genres: …"). Se HowLongToBeat cambia la pagina, la funzione restituisce []
# e l'app continua a funzionare: i generi si aggiungono a mano.

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Generi di HowLongToBeat → etichette usate dal club. Quelli non in elenco restano in inglese.
GENERI = {
    "action": "Action", "adventure": "Avventura", "roleplaying": "RPG", "rpg": "RPG",
    "strategy": "Strategico", "tactical": "Tattico", "turnbased": "A turni",
    "roguelike": "Roguelike", "roguelite": "Roguelike", "platform": "Platform", "platformer": "Platform",
    "puzzle": "Puzzle", "horror": "Horror", "survival": "Survival", "shooter": "Sparatutto",
    "simulation": "Simulazione", "sports": "Sport", "racing": "Guida", "driving": "Guida",
    "racingdriving": "Guida", "fighting": "Picchiaduro", "pointandclick": "Punta e clicca",
    "visualnovel": "Visual novel", "metroidvania": "Metroidvania", "openworld": "Open world",
    "sandbox": "Sandbox", "stealth": "Stealth", "hackandslash": "Hack and slash",
    "management": "Gestionale", "citybuilding": "Gestionale", "music": "Ritmo", "rhythm": "Ritmo",
    "musicrhythm": "Ritmo", "card": "Carte", "cardgame": "Carte", "party": "Party",
    "beatemup": "Picchiaduro", "interactivestory": "Narrativo", "narrative": "Narrativo",
}
# Prospettive e stili di visuale: non sono generi, vengono scartati.
PROSPETTIVE = ("person", "topdown", "isometric", "scrolling", "side", "vertical", "2d", "3d", "overhead")


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def map_genres(raw: list[str]) -> list[str]:
    """Converte i generi HLTB nelle etichette del club, senza doppioni."""
    norm = [_norm(g) for g in raw]
    out: list[str] = []
    fps = any(n == "firstperson" for n in norm) and any(n == "shooter" for n in norm)
    for original, n in zip(raw, norm):
        if not n or any(p == n or n.endswith(p) for p in PROSPETTIVE):
            continue
        if fps and n == "shooter":
            label = "FPS"
        else:
            label = GENERI.get(n, original.strip())
        if label not in out:
            out.append(label)
    return out


def _split_genres(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [g.strip() for g in str(value or "").replace("/", ",").split(",") if g.strip()]


def _find_genre_field(obj, depth: int = 0):
    """Cerca ricorsivamente un campo che contenga i generi (es. 'profile_genre')."""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if "genre" in str(key).lower() and value and isinstance(value, (str, list)):
                return value
        for value in obj.values():
            found = _find_genre_field(value, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_genre_field(value, depth + 1)
            if found:
                return found
    return None


def parse_genres(html: str) -> list[str]:
    """Estrae i generi (grezzi, in inglese) dall'HTML della pagina di un gioco."""
    import json
    import re

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            found = _find_genre_field(json.loads(script.string))
        except ValueError:
            found = None
        if found:
            return _split_genres(found)
    text = soup.get_text("\n")
    match = re.search(r"Genres?\s*:\s*\n?\s*([^\n]+)", text)
    return _split_genres(match.group(1)) if match else []


def fetch_genres(hltb_id: str) -> list[str] | None:
    """Generi del gioco, già convertiti. [] se la pagina non li contiene, None se non raggiungibile."""
    if not str(hltb_id).strip():
        return []
    import requests

    try:
        resp = requests.get(game_url(hltb_id), headers={"User-Agent": USER_AGENT, "Referer": "https://howlongtobeat.com/"},
                            timeout=TIMEOUT_SECONDI)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return None
    try:
        return map_genres(parse_genres(resp.text))
    except Exception:  # noqa: BLE001 - pagina inattesa: nessun genere
        return []
