"""Logica dell'app: PIN, voti e statistiche. Nessuna dipendenza da Streamlit."""

from __future__ import annotations

import hashlib
import hmac
import base64
import itertools
import os
import time
from urllib.parse import quote_plus

import numpy as np
import pandas as pd

CATEGORIE = ["storia", "ambientazione", "gameplay", "audio", "longevita"]
ETICHETTE = {
    "storia": "Storia",
    "ambientazione": "Ambientazione",
    "gameplay": "Gameplay",
    "audio": "Audio",
    "longevita": "Longevità",
    "final": "FINAL",
    "ore": "Ore",
}
STATI_PERIODO = ["bozza", "votazione", "in_gioco", "chiuso"]
ETICHETTE_STATO = {
    "bozza": "Bozza",
    "votazione": "Votazione aperta",
    "in_gioco": "In gioco",
    "chiuso": "Chiuso",
}
STATI_GIOCO = ["finito", "abbandonato", "non giocato"]


# ---------------------------------------------------------------- utilità

def split_list(value: str) -> list[str]:
    return [v.strip() for v in str(value or "").split(";") if v.strip()]


def split_multi(value: str) -> list[str]:
    """Come split_list, ma accetta anche la virgola (piattaforme scritte a mano nella prima versione)."""
    return [v.strip() for v in str(value or "").replace(",", ";").split(";") if v.strip()]


def join_list(values) -> str:
    return ";".join(v.strip() for v in values if str(v).strip())


def to_num(value) -> float:
    s = str(value if value is not None else "").strip().replace(",", ".")
    if s in ("", "-", "–", "nan", "None"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def is_true(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "si", "sì", "yes")


# ---------------------------------------------------------------- PIN

def hash_pin(pin: str, pepper: str = "") -> str:
    salt = os.urandom(8)
    digest = hashlib.pbkdf2_hmac("sha256", (pepper + pin).encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def check_pin(pin: str, stored: str, pepper: str = "") -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", (pepper + pin).encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def valid_pin(pin: str) -> bool:
    return len(pin) == 4 and pin.isdigit()


# ---------------------------------------------------------------- sessione (cookie)
# Il cookie contiene: chi sei, se sei entrato come admin e la scadenza, più una firma.
# La firma dipende anche dal PIN attuale (e dalla password admin): se l'admin azzera
# un PIN, i cookie di quella persona smettono di valere.

def _session_sig(member_id: str, admin: bool, exp: int, key: str, bind: str) -> str:
    msg = f"{member_id}|{int(admin)}|{exp}|{bind}".encode()
    return hmac.new(("levelone-session|" + key).encode(), msg, hashlib.sha256).hexdigest()[:40]


def make_session_token(member_id: str, admin: bool, exp: int, key: str, bind: str) -> str:
    payload = base64.urlsafe_b64encode(f"{member_id}|{int(admin)}|{exp}".encode()).decode().rstrip("=")
    return f"{payload}.{_session_sig(member_id, admin, exp, key, bind)}"


def parse_session_token(token: str) -> tuple[str, bool, int, str] | None:
    """(member_id, admin, scadenza, firma) senza verificare nulla: la verifica la fa check_session_token."""
    try:
        payload, sig = str(token).split(".")
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        member_id, admin, exp = raw.split("|")
        return member_id, admin == "1", int(exp), sig
    except Exception:  # noqa: BLE001
        return None


def check_session_token(parsed, key: str, bind: str, now: float | None = None) -> bool:
    member_id, admin, exp, sig = parsed
    if exp < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(sig, _session_sig(member_id, admin, exp, key, bind))


def admin_bind(password: str) -> str:
    return hashlib.sha256(("admin|" + str(password)).encode()).hexdigest()


# ---------------------------------------------------------------- tabelle base

def latest(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per le tabelle 'solo aggiunta': tiene l'ultima riga per chiave."""
    if df.empty:
        return df
    return df.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)


def members(data) -> pd.DataFrame:
    m = data["membri"].copy()
    m["attivo"] = m["attivo"].map(is_true)
    pins = latest(data["pin"], ["member_id"]).set_index("member_id")["pin_hash"] if not data["pin"].empty else pd.Series(dtype=str)
    m["pin_hash"] = m["member_id"].map(pins).fillna("")
    m["pin_impostato"] = m["pin_hash"] != ""
    return m


def name_map(data) -> dict[str, str]:
    return dict(zip(data["membri"]["member_id"], data["membri"]["nome"]))


def game_map(data) -> dict[str, str]:
    return dict(zip(data["giochi"]["game_id"], data["giochi"]["titolo"]))


def game_tags(data) -> dict[str, list[str]]:
    return {g: split_list(t) for g, t in zip(data["giochi"]["game_id"], data["giochi"]["tag"])}


def all_tags(data) -> list[str]:
    tags = set()
    for t in data["giochi"]["tag"]:
        tags.update(split_list(t))
    return sorted(tags, key=str.lower)


PIATTAFORME_BASE = ["PC", "PlayStation 5", "PlayStation 4", "Xbox Series X/S", "Xbox One",
                    "Nintendo Switch", "Nintendo Switch 2", "Mobile"]
DURATE = {"ore_storia": "Storia principale", "ore_extra": "Storia + extra", "ore_completo": "Completista"}


def all_platforms(data) -> list[str]:
    plats = set()
    for p in data["giochi"]["piattaforme"]:
        plats.update(split_multi(p))
    return sorted(plats, key=str.lower)


def durations(data) -> dict[str, float]:
    """Ore della storia principale per gioco (solo quelle note)."""
    g = data["giochi"]
    out = {gid: to_num(h) for gid, h in zip(g["game_id"], g["ore_storia"])}
    return {k: v for k, v in out.items() if not np.isnan(v)}


def game_links(title: str, hltb_url: str = "", platforms: list[str] | None = None) -> list[tuple[str, str]]:
    """Link utili per farsi un'idea di un gioco, senza spoiler: HLTB, Steam (se esce su PC), trailer."""
    links = []
    if str(hltb_url or "").strip():
        links.append(("HowLongToBeat", str(hltb_url).strip()))
    else:
        links.append(("HowLongToBeat", "https://www.google.com/search?q=" + quote_plus(f"site:howlongtobeat.com {title}")))
    if not platforms or "PC" in platforms:
        links.append(("Steam", "https://store.steampowered.com/search/?term=" + quote_plus(title)))
    links.append(("Trailer su YouTube", "https://www.youtube.com/results?search_query=" + quote_plus(f"{title} trailer")))
    return links


def periods(data) -> pd.DataFrame:
    p = data["periodi"].copy()
    p["numero_n"] = p["numero"].map(to_num).astype(float)
    return p.sort_values("numero_n").reset_index(drop=True)


def period_row(data, period_id: str) -> pd.Series | None:
    p = data["periodi"]
    rows = p[p["period_id"] == period_id]
    return None if rows.empty else rows.iloc[0]


def is_revealed(period) -> bool:
    return is_true(period.get("rivelato", ""))


def hidden_period_ids(data) -> set[str]:
    p = data["periodi"]
    return set(p.loc[~p["rivelato"].map(is_true), "period_id"])


def visible_data(data) -> dict:
    """I dati come li vedono i membri.

    Le valutazioni restano nascoste finché l'admin non le rivela alla serata. L'hype invece
    è visibile a tutti appena il periodo ha un vincitore (cioè da "In gioco" in poi).
    """
    hidden = hidden_period_ids(data)
    p = data["periodi"]
    with_winner = set(p.loc[p["stato"].isin(["in_gioco", "chiuso"]), "period_id"])
    out = dict(data)
    v = data["valutazioni"]
    out["valutazioni"] = v[~v["period_id"].isin(hidden)].reset_index(drop=True)
    h = data["hype"]
    out["hype"] = h[h["period_id"].isin(with_winner)].reset_index(drop=True)
    return out


def hidden_with_ratings(data) -> int:
    """Quanti periodi hanno valutazioni ancora nascoste."""
    hidden = hidden_period_ids(data)
    return len(set(data["valutazioni"]["period_id"]) & hidden)


# ---------------------------------------------------------------- votazione proposte

def eligible_voters(data, period) -> list[str]:
    m = members(data)
    return [mid for mid in m.loc[m["attivo"], "member_id"] if mid != period["proponente_id"]]


def period_votes(data, period) -> pd.DataFrame:
    """Ultimo voto valido di ciascun membro per il periodo (il proponente è escluso)."""
    v = data["voti_proposte"]
    v = v[v["period_id"] == period["period_id"]]
    v = latest(v, ["period_id", "member_id"])
    return v[v["member_id"] != period["proponente_id"]]


def my_vote(data, period_id: str, member_id: str) -> list[str] | None:
    v = data["voti_proposte"]
    v = v[(v["period_id"] == period_id) & (v["member_id"] == member_id)]
    return None if v.empty else split_list(v.iloc[-1]["scelte"])


def vote_counts(data, period) -> pd.DataFrame:
    options = split_list(period["opzioni"])
    votes = period_votes(data, period)
    counts = {g: 0 for g in options}
    for scelte in votes["scelte"]:
        for g in split_list(scelte):
            if g in counts:
                counts[g] += 1
    n_voters = len(votes)
    gm = game_map(data)
    df = pd.DataFrame(
        {"game_id": list(counts), "gioco": [gm.get(g, g) for g in counts], "voti": list(counts.values())}
    )
    df["percentuale"] = (df["voti"] / n_voters * 100).round(0) if n_voters else 0
    return df.sort_values("voti", ascending=False).reset_index(drop=True)


def leaders(counts: pd.DataFrame) -> list[str]:
    if counts.empty or counts["voti"].max() == 0:
        return []
    top = counts["voti"].max()
    return counts.loc[counts["voti"] == top, "game_id"].tolist()


# ---------------------------------------------------------------- valutazioni

def ratings(data) -> pd.DataFrame:
    """Ultima valutazione di ciascun membro per ciascun periodo, con i numeri convertiti.

    Aggiunge anche:
    - ore_rif: ore della storia principale usate come riferimento per chi abbandona
      (quelle salvate al momento del voto, altrimenti quelle HLTB attuali, altrimenti la
      media delle ore di chi nel club l'ha finito);
    - peso: 1 per chi l'ha finito; per chi l'ha abbandonato, ore giocate ÷ ore_rif (massimo 1).
    """
    r = latest(data["valutazioni"], ["period_id", "member_id"]).copy()
    for c in CATEGORIE + ["final", "ore"]:
        r[c] = r[c].map(to_num).astype(float)
    r = r[r["stato"] != "non giocato"]
    r["media_categorie"] = r[CATEGORIE].mean(axis=1, skipna=True)
    nm, gm = name_map(data), game_map(data)
    r["membro"] = r["member_id"].map(nm)
    r["gioco"] = r["game_id"].map(gm)
    # Scarto dalla media personale: quanto un voto è sopra/sotto il solito di quella persona.
    r["scarto_personale"] = r["final"] - r.groupby("member_id")["final"].transform("mean")

    hltb_hours = durations(data)
    snap = r["ore_rif"].map(to_num).astype(float) if "ore_rif" in r else pd.Series(np.nan, index=r.index)
    ref = snap.where(snap > 0, r["game_id"].map(hltb_hours).astype(float))
    finishers = r[(r["stato"] == "finito") & (r["ore"] > 0)].groupby("period_id")["ore"].mean()
    ref = ref.where(ref > 0, r["period_id"].map(finishers).astype(float))
    r["ore_rif"] = ref
    ratio = (r["ore"] / ref).clip(upper=1)
    r["peso"] = np.where((r["stato"] == "abbandonato") & ratio.notna(), ratio, 1.0)
    return r.reset_index(drop=True)


def game_ratings(data, pesati: bool = True) -> pd.DataFrame:
    """Valutazioni per le medie dei giochi: con gli abbandoni pesati, oppure solo chi l'ha finito."""
    r = ratings(data)
    if not pesati:
        r = r[r["stato"] != "abbandonato"].copy()
        r["peso"] = 1.0
    return r


def wmean(values: pd.Series, weights: pd.Series) -> float:
    ok = values.notna() & weights.notna() & (weights > 0)
    return float(np.average(values[ok], weights=weights[ok])) if ok.any() else np.nan


def wstd(values: pd.Series, weights: pd.Series) -> float:
    ok = values.notna() & weights.notna() & (weights > 0)
    if not ok.any():
        return np.nan
    m = np.average(values[ok], weights=weights[ok])
    return float(np.sqrt(np.average((values[ok] - m) ** 2, weights=weights[ok])))


def final_average(r: pd.DataFrame, pesati: bool = True) -> float:
    """FINAL medio di un insieme di valutazioni (di solito un periodo)."""
    if r.empty:
        return np.nan
    if not pesati:
        r = r[r["stato"] != "abbandonato"]
        return float(r["final"].mean()) if not r.empty else np.nan
    return wmean(r["final"], r["peso"])


def my_rating(data, period_id: str, member_id: str) -> pd.Series | None:
    v = data["valutazioni"]
    v = v[(v["period_id"] == period_id) & (v["member_id"] == member_id)]
    return None if v.empty else v.iloc[-1]


def hype_table(data) -> pd.DataFrame:
    h = latest(data["hype"], ["period_id", "member_id"]).copy()
    h["voto"] = h["voto"].map(to_num).astype(float)
    return h


def period_hype(data, period_id: str) -> pd.DataFrame:
    """Hype di ciascun membro per un periodo (membro, voto), dal più alto."""
    h = hype_table(data)
    h = h[(h["period_id"] == period_id) & h["voto"].notna()].copy()
    h["membro"] = h["member_id"].map(name_map(data))
    return h[["membro", "voto"]].sort_values("voto", ascending=False).reset_index(drop=True)


def my_hype(data, period_id: str, member_id: str) -> float | None:
    h = data["hype"]
    h = h[(h["period_id"] == period_id) & (h["member_id"] == member_id)]
    return None if h.empty else to_num(h.iloc[-1]["voto"])


# ---------------------------------------------------------------- statistiche

def game_summary(data, pesati: bool = True) -> pd.DataFrame:
    """Medie per gioco. pesati=True: chi ha abbandonato conta in proporzione alle ore giocate."""
    all_r = ratings(data)
    if all_r.empty:
        return pd.DataFrame()
    drops = all_r[all_r["stato"] == "abbandonato"].groupby("game_id").size()
    r = game_ratings(data, pesati)
    rows = []
    for (gid, gioco), grp in r.groupby(["game_id", "gioco"]):
        w = grp["peso"]
        row = {
            "game_id": gid,
            "gioco": gioco,
            "valutazioni": int(grp["final"].notna().sum()),
            "final_medio": wmean(grp["final"], w),
            "media_categorie": wmean(grp["media_categorie"], w),
            "divisivita": wstd(grp["final"], w),
            "gradimento_normalizzato": wmean(grp["scarto_personale"], w),
            "abbandoni": int(drops.get(gid, 0)),
            "ore_medie": grp["ore"].mean(),
        }
        for c in CATEGORIE:
            row[c] = wmean(grp[c], w)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values("final_medio", ascending=False).reset_index(drop=True)


def member_summary(data) -> pd.DataFrame:
    r = ratings(data)
    if r.empty:
        return pd.DataFrame()
    g = r.groupby(["member_id", "membro"])
    out = g[CATEGORIE + ["final"]].mean()
    out["giochi_valutati"] = g["game_id"].count()
    out["ore_totali"] = g["ore"].sum()
    out["abbandoni"] = g["stato"].apply(lambda s: int((s == "abbandonato").sum()))
    return out.reset_index()


def tag_member_matrix(data) -> pd.DataFrame:
    """FINAL medio per tag e membro (lungo: tag, membro, final, n)."""
    r = ratings(data)
    if r.empty:
        return pd.DataFrame(columns=["tag", "membro", "final", "n"])
    tags = game_tags(data)
    r = r.assign(tag=r["game_id"].map(lambda g: tags.get(g) or ["(senza tag)"])).explode("tag")
    out = r.groupby(["tag", "membro"])["final"].agg(["mean", "count"]).reset_index()
    return out.rename(columns={"mean": "final", "count": "n"})


def tag_summary(data, pesati: bool = True) -> pd.DataFrame:
    all_r = ratings(data)
    if all_r.empty:
        return pd.DataFrame()
    tags = game_tags(data)

    def explode(df):
        return df.assign(tag=df["game_id"].map(lambda g: tags.get(g) or ["(senza tag)"])).explode("tag")

    drops = explode(all_r[all_r["stato"] == "abbandonato"]).groupby("tag").size()
    r = explode(game_ratings(data, pesati))
    rows = [{"tag": t, "final_medio": wmean(grp["final"], grp["peso"]), "giochi": grp["game_id"].nunique(),
             "abbandoni": int(drops.get(t, 0))} for t, grp in r.groupby("tag")]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("final_medio", ascending=False)


def hype_vs_reality(data) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restituisce (per periodo, per membro)."""
    h = hype_table(data)
    r = ratings(data)
    if h.empty or r.empty:
        return pd.DataFrame(), pd.DataFrame()
    both = h.merge(r[["period_id", "member_id", "final", "gioco", "membro"]], on=["period_id", "member_id"])
    both = both.dropna(subset=["voto", "final"])
    if both.empty:
        return pd.DataFrame(), pd.DataFrame()
    both["delta"] = both["final"] - both["voto"]
    per_game = both.groupby(["period_id", "gioco"]).agg(
        hype_medio=("voto", "mean"), final_medio=("final", "mean"), delta=("delta", "mean"), n=("delta", "count")
    ).reset_index()
    per_member = both.groupby("membro").agg(
        hype_medio=("voto", "mean"), final_medio=("final", "mean"), delta=("delta", "mean"), n=("delta", "count")
    ).reset_index()
    return per_game, per_member


def affinity(data, min_common: int = 2) -> pd.DataFrame:
    """Somiglianza di gusti tra coppie di membri sui giochi valutati da entrambi.

    affinita = 100 × (1 − differenza media assoluta dei FINAL / 9).
    100 = voti identici, 0 = sempre agli estremi opposti della scala 1–10.
    """
    r = ratings(data).dropna(subset=["final"])
    if r.empty:
        return pd.DataFrame(columns=["membro_a", "membro_b", "affinita", "giochi_in_comune"])
    pivot = r.pivot_table(index="game_id", columns="membro", values="final", aggfunc="last")
    rows = []
    for a, b in itertools.combinations(pivot.columns, 2):
        pair = pivot[[a, b]].dropna()
        if len(pair) < min_common:
            continue
        mad = (pair[a] - pair[b]).abs().mean()
        rows.append({"membro_a": a, "membro_b": b, "affinita": 100 * (1 - mad / 9), "giochi_in_comune": len(pair)})
    return pd.DataFrame(rows, columns=["membro_a", "membro_b", "affinita", "giochi_in_comune"])


def proposer_stats(data, pesati: bool = True) -> pd.DataFrame:
    p = periods(data)
    p = p[p["stato"].isin(["in_gioco", "chiuso"])]
    if p.empty:
        return pd.DataFrame()
    r = ratings(data)
    nm = name_map(data)
    rows = []
    for _, per in p.iterrows():
        counts = vote_counts(data, per)
        n_voters = len(period_votes(data, per))
        approval = counts["voti"].mean() / n_voters * 100 if n_voters else np.nan
        fin = final_average(r[r["period_id"] == per["period_id"]], pesati) if not r.empty else np.nan
        rows.append({"proponente": nm.get(per["proponente_id"], "?"), "approvazione": approval, "final_vincitore": fin})
    df = pd.DataFrame(rows)
    return (
        df.groupby("proponente")
        .agg(periodi=("approvazione", "size"), approvazione_media=("approvazione", "mean"), final_medio_vincitori=("final_vincitore", "mean"))
        .reset_index()
        .sort_values("final_medio_vincitori", ascending=False)
    )


def wishlist(data) -> pd.DataFrame:
    """Giochi proposti e quanto sono stati votati, anche quando hanno perso."""
    p = periods(data)
    p = p[p["stato"].isin(["in_gioco", "chiuso"])]
    rows = []
    for _, per in p.iterrows():
        counts = vote_counts(data, per)
        n_voters = len(period_votes(data, per))
        for _, c in counts.iterrows():
            rows.append(
                {
                    "game_id": c["game_id"],
                    "gioco": c["gioco"],
                    "voti": c["voti"],
                    "votanti": n_voters,
                    "vinto": c["game_id"] == per["vincitore_id"],
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = df.groupby(["game_id", "gioco"]).agg(
        proposto=("voti", "size"), vinto=("vinto", "sum"), voti=("voti", "sum"), votanti=("votanti", "sum")
    ).reset_index()
    out["approvazione"] = np.where(out["votanti"] > 0, out["voti"] / out["votanti"] * 100, np.nan)
    out = out[out["vinto"] == 0]
    return out.sort_values(["approvazione", "proposto"], ascending=False).reset_index(drop=True)


def predict(data, game_id: str, member_id: str | None = None) -> tuple[float, str]:
    """Stima del FINAL per un gioco proposto.

    Se il gioco è già stato valutato usa quei voti. Altrimenti fa la media dei
    FINAL passati dei giochi con gli stessi tag. Restituisce (stima, spiegazione).
    """
    r = ratings(data).dropna(subset=["final"])
    if member_id:
        r = r[r["member_id"] == member_id]
    if r.empty:
        return np.nan, "nessuno storico"
    same = r[r["game_id"] == game_id]
    if not same.empty:
        return same["final"].mean(), "già giocato"
    tags = game_tags(data)
    mine = tags.get(game_id, [])
    if not mine:
        return np.nan, "gioco senza tag"
    r = r.assign(tag=r["game_id"].map(lambda g: tags.get(g, []))).explode("tag")
    by_tag = r[r["tag"].isin(mine)].groupby("tag")["final"].mean()
    if by_tag.empty:
        return np.nan, "nessun gioco simile valutato"
    return by_tag.mean(), "in base a: " + ", ".join(by_tag.index)


def games_catalog(data, pesati: bool = True) -> pd.DataFrame:
    """Tutti i giochi con generi, piattaforme, durate e storico nel club."""
    g = data["giochi"].copy()
    g["tags"] = g["tag"].map(split_list)
    g["sinossi"] = g["sinossi"].fillna("") if "sinossi" in g else ""
    g["platforms"] = g["piattaforme"].map(split_multi)
    for c in DURATE:
        g[c] = g[c].map(to_num).astype(float)
    gs = game_summary(data, pesati)
    fin = dict(zip(gs["game_id"], gs["final_medio"])) if not gs.empty else {}
    g["final_medio"] = g["game_id"].map(fin).astype(float)
    p = data["periodi"]
    played = p[p["stato"].isin(["in_gioco", "chiuso"])]
    g["giocato"] = g["game_id"].isin(set(played["vincitore_id"]))
    shown = p[p["stato"] != "bozza"]["opzioni"].map(split_list)
    g["proposto"] = g["game_id"].map(lambda gid: int(sum(gid in opts for opts in shown)))
    return g


def tag_counts(data, column: str) -> dict[str, int]:
    """Quanti giochi usano ciascun tag. column: 'tag' (generi) o 'piattaforme'."""
    splitter = split_list if column == "tag" else split_multi
    counts: dict[str, int] = {}
    for value in data["giochi"][column]:
        for t in splitter(value):
            counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[0].lower()))


def replace_tag(giochi: pd.DataFrame, column: str, old: str, new: str | None) -> pd.DataFrame:
    """Rinomina (o unisce, se `new` esiste già) oppure elimina (`new` = None) un tag in tutti i giochi."""
    splitter = split_list if column == "tag" else split_multi
    new = (new or "").strip() or None

    def fix(value):
        out = []
        for t in splitter(value):
            t = new if t == old else t
            if t and t not in out:
                out.append(t)
        return join_list(out)

    df = giochi.copy()
    df[column] = df[column].map(fix)
    return df


def game_club_history(data, game_id: str, pesati: bool = True) -> list[dict]:
    """Periodi in cui il gioco è stato proposto, con esito e (se visibili) i voti."""
    p = periods(data)
    p = p[(p["stato"] != "bozza") & p["opzioni"].map(lambda o: game_id in split_list(o))]
    nm = name_map(data)
    r = ratings(data)
    out = []
    for _, per in p.iterrows():
        item = {"numero": per["numero"], "proponente": nm.get(per["proponente_id"], "?"), "stato": per["stato"],
                "vinto": per["vincitore_id"] == game_id, "voti": None, "votanti": None, "valutazioni": None,
                "final_medio": np.nan,
                "rivelato": is_revealed(per)}
        if per["stato"] != "votazione":
            counts = vote_counts(data, per)
            row = counts[counts["game_id"] == game_id]
            item["voti"] = int(row["voti"].iloc[0]) if not row.empty else 0
            item["votanti"] = len(period_votes(data, per))
        if item["vinto"] and not r.empty:
            pr = r[r["period_id"] == per["period_id"]]
            if not pr.empty:
                item["valutazioni"] = pr[["membro", "stato", "final", "ore", "peso", "commento"]].sort_values("final", ascending=False)
                item["final_medio"] = final_average(pr, pesati)
        out.append(item)
    return out
