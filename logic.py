"""Logica dell'app: PIN, voti e statistiche. Nessuna dipendenza da Streamlit."""

from __future__ import annotations

import hashlib
import hmac
import itertools
import os

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
    """I dati come li vedono i membri: senza valutazioni e hype dei periodi non ancora rivelati."""
    hidden = hidden_period_ids(data)
    out = dict(data)
    for table in ("valutazioni", "hype"):
        out[table] = data[table][~data[table]["period_id"].isin(hidden)].reset_index(drop=True)
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
    """Ultima valutazione di ciascun membro per ciascun periodo, con i numeri convertiti."""
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
    return r.reset_index(drop=True)


def my_rating(data, period_id: str, member_id: str) -> pd.Series | None:
    v = data["valutazioni"]
    v = v[(v["period_id"] == period_id) & (v["member_id"] == member_id)]
    return None if v.empty else v.iloc[-1]


def hype_table(data) -> pd.DataFrame:
    h = latest(data["hype"], ["period_id", "member_id"]).copy()
    h["voto"] = h["voto"].map(to_num).astype(float)
    return h


def my_hype(data, period_id: str, member_id: str) -> float | None:
    h = data["hype"]
    h = h[(h["period_id"] == period_id) & (h["member_id"] == member_id)]
    return None if h.empty else to_num(h.iloc[-1]["voto"])


# ---------------------------------------------------------------- statistiche

def game_summary(data) -> pd.DataFrame:
    r = ratings(data)
    if r.empty:
        return pd.DataFrame()
    g = r.groupby(["game_id", "gioco"])
    out = pd.DataFrame(
        {
            "valutazioni": g["member_id"].count(),
            "final_medio": g["final"].mean(),
            "media_categorie": g["media_categorie"].mean(),
            "divisivita": g["final"].std(ddof=0),
            "gradimento_normalizzato": g["scarto_personale"].mean(),
            "abbandoni": g["stato"].apply(lambda s: int((s == "abbandonato").sum())),
            "ore_medie": g["ore"].mean(),
        }
    ).reset_index()
    for c in CATEGORIE:
        out[c] = g[c].mean().values
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


def tag_summary(data) -> pd.DataFrame:
    r = ratings(data)
    if r.empty:
        return pd.DataFrame()
    tags = game_tags(data)
    r = r.assign(tag=r["game_id"].map(lambda g: tags.get(g) or ["(senza tag)"])).explode("tag")
    g = r.groupby("tag")
    out = pd.DataFrame(
        {
            "final_medio": g["final"].mean(),
            "giochi": g["game_id"].nunique(),
            "abbandoni": g["stato"].apply(lambda s: int((s == "abbandonato").sum())),
        }
    )
    return out.reset_index().sort_values("final_medio", ascending=False)


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


def proposer_stats(data) -> pd.DataFrame:
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
        fin = r.loc[r["period_id"] == per["period_id"], "final"].mean() if not r.empty else np.nan
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


def games_catalog(data) -> pd.DataFrame:
    """Tutti i giochi con generi, piattaforme, durate e storico nel club."""
    g = data["giochi"].copy()
    g["tags"] = g["tag"].map(split_list)
    g["platforms"] = g["piattaforme"].map(split_multi)
    for c in DURATE:
        g[c] = g[c].map(to_num).astype(float)
    gs = game_summary(data)
    fin = dict(zip(gs["game_id"], gs["final_medio"])) if not gs.empty else {}
    g["final_medio"] = g["game_id"].map(fin).astype(float)
    p = data["periodi"]
    played = p[p["stato"].isin(["in_gioco", "chiuso"])]
    g["giocato"] = g["game_id"].isin(set(played["vincitore_id"]))
    shown = p[p["stato"] != "bozza"]["opzioni"].map(split_list)
    g["proposto"] = g["game_id"].map(lambda gid: int(sum(gid in opts for opts in shown)))
    return g
