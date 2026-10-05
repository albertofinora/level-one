"""Level One – Club del Videogioco."""

from __future__ import annotations

import io
import os
import time
import zipfile
from datetime import date
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import hltb
import logic as L
import seed
from storage import SCHEMA, LocalStore, SheetsStore, new_id, now_ts

st.set_page_config(page_title="Level One", page_icon="🎮", layout="centered")
st.markdown(
    """<style>
    [data-testid="stMainBlockContainer"] {padding-top: 2.5rem; padding-bottom: 3rem;}
    [data-testid="stElementContainer"]:has(.lo-cookie) {display: none;}
    </style>""",
    unsafe_allow_html=True,
)

HERE = Path(__file__).parent
SCALA = ["–"] + [f"{x / 2:g}" for x in range(2, 21)]  # –, 1, 1.5, … 10
MAX_TENTATIVI = 5
BLOCCO_SECONDI = 120
SESSIONE_MINUTI = 30          # dopo quanto tempo di inattività bisogna rientrare col PIN
COOKIE = "levelone_sessione"


# ================================================================ dati

def secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default


@st.cache_resource(show_spinner=False)
def get_store():
    info, sheet_id = secret("gcp_service_account"), secret("sheet_id")
    if info and sheet_id:
        return SheetsStore(dict(info), str(sheet_id))
    return LocalStore(os.environ.get("LEVEL_ONE_DATA", HERE / "data"))


@st.cache_data(ttl=60, show_spinner=False)
def load_data():
    return get_store().read_all()


def save_append(table: str, row: dict) -> bool:
    try:
        get_store().append(table, row)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Salvataggio non riuscito, riprova tra poco. Dettaglio: {exc}")
        return False
    load_data.clear()
    return True


def save_table(table: str, df: pd.DataFrame) -> bool:
    try:
        get_store().overwrite(table, df)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Salvataggio non riuscito, riprova tra poco. Dettaglio: {exc}")
        return False
    load_data.clear()
    return True


def pepper() -> str:
    return str(secret("pin_pepper", ""))


# ================================================================ formattazione

def fmt(x, dec: int = 1) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:.{dec}f}".replace(".", ",")


def fmt_date(iso: str) -> str:
    parts = str(iso).split("-")
    return "/".join(reversed(parts)) if len(parts) == 3 else str(iso)


def ms(*args, **kwargs):
    """st.multiselect con il testo segnaposto in italiano."""
    kwargs.setdefault("placeholder", "Scegli…")
    return st.multiselect(*args, **kwargs)


def num_cols(cols, dec: int = 1) -> dict:
    return {c: st.column_config.NumberColumn(format=f"%.{dec}f") for c in cols}


def empty_ratings_note():
    st.info("Le statistiche compaiono appena qualcuno valuta il primo gioco nella sezione **In gioco**.")


def drops_toggle(where: str) -> bool:
    """Interruttore "abbandoni pesati / solo chi l'ha finito", per tutti.

    Compare in più schede: ogni copia ha la sua chiave, ma la scelta è una sola e resta
    uguale ovunque (chiave condivisa "abbandoni_pesati")."""
    key = f"abb_{where}"
    st.session_state.setdefault("abbandoni_pesati", True)
    st.session_state[key] = st.session_state["abbandoni_pesati"]

    def sync():
        st.session_state["abbandoni_pesati"] = st.session_state[key]

    return st.toggle("Conta anche chi l'ha abbandonato", key=key, on_change=sync,
                     help="Acceso: chi ha abbandonato conta in proporzione alle ore giocate rispetto alla storia "
                          "principale. Spento: medie solo di chi l'ha finito.")


def comments_list(df: pd.DataFrame, name_col: str = "membro"):
    """Commenti in chiaro sotto le tabelle: su telefono le celle lunghe vengono tagliate."""
    rows = df[df["commento"].fillna("").str.strip() != ""]
    if rows.empty:
        return
    st.markdown("**Commenti**")
    for _, r in rows.iterrows():
        st.markdown(f"💬 **{r[name_col]}**: {r['commento'].strip()}")


def weight_label(r) -> str:
    if r["stato"] != "abbandonato" or np.isnan(r["final"]):
        return ""
    return f"{r['peso'] * 100:.0f}%"


# ================================================================ sessione persistente
# Streamlit dimentica tutto quando si ricarica la pagina. Per restare dentro salviamo
# nel browser un cookie firmato (vedi logic.make_session_token) che vale SESSIONE_MINUTI
# dall'ultima azione. Lo scriviamo con un pezzetto di JavaScript e lo rileggiamo con
# st.context.cookies quando la pagina viene riaperta.

def admin_expected() -> str | None:
    expected = secret("admin_password")
    if not expected and isinstance(get_store(), LocalStore):
        return "admin"
    return str(expected) if expected else None


def session_key() -> str:
    return pepper() or "solo-locale"


def member_bind(data, member_id: str) -> str | None:
    m = L.members(data)
    row = m[(m["member_id"] == member_id) & m["attivo"]]
    if row.empty or not row.iloc[0]["pin_impostato"]:
        return None
    return row.iloc[0]["pin_hash"]


def session_bind(data, member_id: str, admin: bool) -> str | None:
    parts = []
    if member_id:
        b = member_bind(data, member_id)
        if b is None:
            return None
        parts.append(b)
    if admin:
        expected = admin_expected()
        if not expected:
            return None
        parts.append(L.admin_bind(expected))
    return "|".join(parts) if parts else None


def read_cookie() -> str | None:
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:  # noqa: BLE001
        return None


def restore_session(data):
    """Alla prima esecuzione dopo un ricaricamento: se c'è un cookie valido, rientra in automatico."""
    if st.session_state.get("cookie_checked"):
        return
    st.session_state["cookie_checked"] = True
    token = read_cookie()
    if not token:
        return
    st.session_state["cookie_seen"] = True
    parsed = L.parse_session_token(token)
    if parsed is None:
        return
    member_id, admin, _, _ = parsed
    bind = session_bind(data, member_id, admin)
    if bind is None or not L.check_session_token(parsed, session_key(), bind):
        return
    if member_id:
        st.session_state["member_id"] = member_id
    if admin:
        st.session_state["admin_ok"] = True


def write_cookie(value: str, expires: str):
    js = f"""<div class="lo-cookie"></div><script>
    (function() {{
      var secure = location.protocol === 'https:' ? '; Secure' : '';
      document.cookie = '{COOKIE}={value}; Expires={expires}; Path=/; SameSite=Lax' + secure;
    }})();
    </script>"""
    st.html(js, unsafe_allow_javascript=True)


def sync_cookie(data):
    """A ogni azione rinnova la scadenza del cookie; quando si esce lo cancella."""
    member_id = st.session_state.get("member_id") or ""
    admin = bool(st.session_state.get("admin_ok"))
    bind = session_bind(data, member_id, admin) if (member_id or admin) else None
    if bind is not None:
        # Scadenza arrotondata al minuto: il cookie viene riscritto al massimo una volta al minuto.
        exp = (int(time.time()) // 60 + SESSIONE_MINUTI + 1) * 60
        token = L.make_session_token(member_id, admin, exp, session_key(), bind)
        write_cookie(token, time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(exp)))
        st.session_state["cookie_seen"] = True
    elif st.session_state.get("cookie_seen"):
        write_cookie("", "Thu, 01 Jan 1970 00:00:00 GMT")


# ================================================================ accesso

def login_view(data):
    st.title("🎮 Level One")
    st.caption("Club del Videogioco")

    m = L.members(data)
    active = m[m["attivo"]]
    if active.empty:
        st.info("L'app non ha ancora membri. Se sei l'admin, apri l'area admin qui sotto per configurarla.")
    else:
        names = dict(zip(active["member_id"], active["nome"]))
        mid = st.selectbox(
            "Chi sei?", options=list(names), format_func=names.get, index=None, placeholder="Scegli il tuo nome"
        )
        if mid:
            row = active[active["member_id"] == mid].iloc[0]
            if row["pin_impostato"]:
                pin_form(mid, row["pin_hash"])
            else:
                first_access_form(mid, names[mid])

    with st.expander("📖 Come funziona"):
        show_guide()
    with st.expander("🔧 Area admin"):
        admin_gate(data)


def locked() -> bool:
    until = st.session_state.get("lock_until", 0)
    if time.time() < until:
        st.error(f"Troppi PIN sbagliati. Riprova tra {int(until - time.time()) + 1} secondi.")
        return True
    return False


def pin_form(member_id: str, pin_hash: str):
    if locked():
        return
    with st.form("login"):
        pin = st.text_input("PIN", type="password", max_chars=4, placeholder="4 cifre")
        ok = st.form_submit_button("Entra", type="primary", width="stretch")
    if ok:
        if L.check_pin(pin, pin_hash, pepper()):
            st.session_state.update(member_id=member_id, fails=0)
            st.rerun()
        fails = st.session_state.get("fails", 0) + 1
        st.session_state["fails"] = fails
        if fails >= MAX_TENTATIVI:
            st.session_state.update(lock_until=time.time() + BLOCCO_SECONDI, fails=0)
            st.rerun()
        st.error(f"PIN sbagliato. Tentativi rimasti: {MAX_TENTATIVI - fails}. Se non lo ricordi, chiedi all'admin di azzerarlo.")


def first_access_form(member_id: str, name: str):
    st.write(f"Ciao {name}, è il tuo primo accesso: scegli un PIN di 4 cifre. Ti servirà ogni volta che entri.")
    with st.form("nuovo_pin"):
        p1 = st.text_input("Nuovo PIN", type="password", max_chars=4)
        p2 = st.text_input("Ripeti il PIN", type="password", max_chars=4)
        ok = st.form_submit_button("Salva PIN ed entra", type="primary", width="stretch")
    if ok:
        if not L.valid_pin(p1):
            st.error("Il PIN deve essere di 4 cifre, solo numeri.")
        elif p1 != p2:
            st.error("I due PIN non coincidono.")
        elif save_append("pin", {"member_id": member_id, "pin_hash": L.hash_pin(p1, pepper()), "ts": now_ts()}):
            st.session_state["member_id"] = member_id
            st.rerun()


# ================================================================ proposte

def proposals_tab(data, me: str):
    open_periods = L.periods(data)
    open_periods = open_periods[open_periods["stato"] == "votazione"]
    if open_periods.empty:
        st.info("Nessuna votazione aperta al momento. Quando il prossimo proponente presenta i suoi giochi, li trovi qui.")
        return

    nm, gm = L.name_map(data), L.game_map(data)
    durs = L.durations(data)
    for _, per in open_periods.iterrows():
        st.subheader(f"Periodo {per['numero']} · proposte di {nm.get(per['proponente_id'], '?')}")
        options = L.split_list(per["opzioni"])
        voters = L.eligible_voters(data, per)
        n_voted = len(L.period_votes(data, per))
        st.caption(f"Hanno votato {n_voted} su {len(voters)}. I risultati si vedono quando l'admin chiude la votazione.")

        games_intro(data, options)
        if per["proponente_id"] == me:
            st.info("Sei tu il proponente di questo periodo, quindi non voti.")
            continue

        previous = L.my_vote(data, per["period_id"], me)
        if previous is not None:
            st.success("Hai già votato. Puoi cambiare le tue scelte finché la votazione è aperta.")

        with st.form(f"voto_{per['period_id']}"):
            st.write("Spunta **tutti** i giochi che ti andrebbe di giocare.")
            picks = []
            for g in options:
                label = gm.get(g, g) + (f" · ⏱ {fmt(durs[g], 0)} h" if g in durs else "")
                if st.checkbox(label, value=bool(previous and g in previous), key=f"v_{per['period_id']}_{g}"):
                    picks.append(g)
            ok = st.form_submit_button("Salva il mio voto", type="primary", width="stretch")
        if ok and save_append(
            "voti_proposte",
            {"period_id": per["period_id"], "member_id": me, "scelte": L.join_list(picks), "ts": now_ts()},
        ):
            st.toast("Voto salvato")
            st.rerun()


def games_intro(data, options: list[str]):
    """Un riquadro apribile per ogni gioco proposto: sinossi, generi, durata e link."""
    cat = L.games_catalog(data).set_index("game_id")
    st.markdown("**Di cosa parlano?**")
    for g in options:
        if g not in cat.index:
            continue
        row = cat.loc[g]
        hours = f" · ⏱ {fmt(row['ore_storia'], 0)} h" if not np.isnan(row["ore_storia"]) else ""
        with st.expander(row["titolo"] + hours):
            if row["sinossi"].strip():
                st.write(row["sinossi"].strip())
            details = [x for x in [", ".join(row["tags"]), ", ".join(row["platforms"]), str(row["anno"] or "")] if x]
            if details:
                st.caption(" · ".join(details))
            st.markdown("🔗 " + links_line(row["titolo"], row["hltb_url"], row["platforms"]))


# ================================================================ gioco in corso

def playing_tab(data, me: str):
    playing = L.periods(data)
    playing = playing[playing["stato"] == "in_gioco"]
    if playing.empty:
        st.info("Nessun gioco in corso. Appena l'admin chiude una votazione, il gioco scelto compare qui.")
        return

    gm, nm = L.game_map(data), L.name_map(data)
    for _, per in playing.iterrows():
        pid, gid = per["period_id"], per["vincitore_id"]
        st.subheader(f"🎮 {gm.get(gid, '?')}")
        st.caption(f"Periodo {per['numero']} · proposto da {nm.get(per['proponente_id'], '?')}")

        rated = L.my_rating(data, pid, me)
        n_rated = len(L.latest(data["valutazioni"], ["period_id", "member_id"]).query("period_id == @pid"))
        n_active = int(L.members(data)["attivo"].sum())
        st.caption(f"Hanno valutato {n_rated} su {n_active}. I voti di tutti si vedranno alla serata, quando l'admin li rivela.")
        hype_section(data, pid, me)
        group_hype(data, pid)
        st.divider()
        rating_section(data, per, me, rated)


def hype_section(data, pid: str, me: str):
    current = L.my_hype(data, pid, me)
    st.markdown("**Hype: quanto ti ispira?**")
    st.caption("Meglio darlo prima di iniziare, ma puoi metterlo o cambiarlo quando vuoi finché il gioco è in corso."
               + ("" if current is None or np.isnan(current) else f" Il tuo hype attuale: {fmt(current)}."))
    with st.form(f"hype_{pid}"):
        value = st.select_slider(
            "Hype (1–10)", options=SCALA[1:], value=SCALA[1:][9] if current is None or np.isnan(current) else f"{current:g}"
        )
        ok = st.form_submit_button("Salva hype", width="stretch")
    if ok and save_append("hype", {"period_id": pid, "member_id": me, "voto": value, "ts": now_ts()}):
        st.toast("Hype salvato")
        st.rerun()


def group_hype(data, pid: str):
    """L'hype di tutti: visibile appena il gioco è stato scelto."""
    h = L.period_hype(data, pid)
    if h.empty:
        return
    st.caption(f"Hype del club: media {fmt(h['voto'].mean())} su {len(h)} · "
               + " · ".join(f"{m} {fmt(v)}" for m, v in zip(h["membro"], h["voto"])))


def rating_section(data, per, me: str, prev):
    pid, gid = per["period_id"], per["vincitore_id"]
    st.markdown("**A fine gioco: la tua valutazione**")
    if prev is not None:
        st.success("Hai già valutato questo gioco. Puoi modificarlo finché l'admin non chiude il periodo.")

    def prev_val(col: str) -> str:
        if prev is None:
            return "–"
        v = L.to_num(prev[col])
        return "–" if np.isnan(v) else f"{v:g}"

    # Fuori dal modulo, così il resto della pagina si adatta subito alla scelta.
    stato_prev = prev["stato"] if prev is not None and prev["stato"] in L.STATI_GIOCO else "finito"
    stato = st.radio("Come è andata?", L.STATI_GIOCO, index=L.STATI_GIOCO.index(stato_prev), horizontal=True,
                     format_func=str.capitalize, key=f"stato_{pid}")
    vota = stato == "finito"
    ref = L.durations(data).get(gid)
    if stato == "abbandonato":
        no_vote_before = prev is not None and prev["stato"] == "abbandonato" and np.isnan(L.to_num(prev["final"]))
        vota = st.toggle("Voglio dare comunque il mio voto", value=not no_vote_before, key=f"vota_{pid}")
        if vota:
            base = (f"le {fmt(ref, 0)} ore della storia principale (HowLongToBeat)" if ref
                    else "la media delle ore di chi nel club l'ha finito")
            st.caption(f"Il tuo voto conterà nelle medie del gioco in proporzione alle ore giocate rispetto a {base}. "
                       "Esempio: metà delle ore = voto che pesa la metà.")
        else:
            st.caption("Salviamo solo le ore giocate: il tuo voto non entra nelle medie.")

    with st.form(f"val_{pid}"):
        ore = None
        if stato != "non giocato":
            ore_prev = L.to_num(prev["ore"]) if prev is not None else np.nan
            ore = st.number_input("Ore giocate" + (" (obbligatorio)" if stato == "abbandonato" else ""),
                                  min_value=0.0, max_value=1000.0, step=0.5,
                                  value=None if np.isnan(ore_prev) else ore_prev, placeholder="Circa quante?")
        scores = {k: "–" for k in L.CATEGORIE + ["final"]}
        if vota:
            st.caption("Voti da 1 a 10. Lascia “–” per le categorie che non vuoi o non puoi valutare.")
            for c in L.CATEGORIE:
                scores[c] = st.select_slider(L.ETICHETTE[c], options=SCALA, value=prev_val(c), key=f"{pid}_{c}")
            scores["final"] = st.select_slider("FINAL: il tuo voto complessivo, di pancia", options=SCALA,
                                               value=prev_val("final"), key=f"{pid}_final")
        commento = st.text_area("Commento (facoltativo)", value=prev["commento"] if prev is not None else "",
                                max_chars=500, height=90)
        ok = st.form_submit_button("Salva valutazione", type="primary", width="stretch")

    if not ok:
        return
    if stato == "finito" and "–" in scores.values():
        st.error("Se l'hai finito, dai un voto a tutte le categorie e al FINAL.")
        return
    if stato == "abbandonato" and ore is None:
        st.error("Se l'hai abbandonato, scrivi circa quante ore hai giocato: servono per pesare il voto.")
        return
    if stato == "abbandonato" and vota and scores["final"] == "–":
        st.error("Se vuoi votare, serve almeno il FINAL.")
        return
    row = {"period_id": pid, "member_id": me, "game_id": gid, "stato": stato,
           "ore": "" if ore is None else f"{ore:g}", "commento": commento.strip(), "ts": now_ts(),
           "ore_rif": "" if not ref else f"{ref:g}"}
    row.update({k: "" if v == "–" else v for k, v in scores.items()})
    if save_append("valutazioni", row):
        st.toast("Valutazione salvata")
        st.rerun()


# ================================================================ statistiche

SEZIONI = ["Classifica", "Membri", "Generi", "Hype", "Affinità", "Proponenti", "Desiderati"]


def stats_tab(full_data, me: str):
    section = st.segmented_control("Sezione", SEZIONI, default="Classifica", label_visibility="collapsed") or "Classifica"
    n_hidden = L.hidden_with_ratings(full_data)
    include_hidden = False
    if n_hidden and st.session_state.get("admin_ok"):
        include_hidden = st.toggle("Includi i voti nascosti (lo vedi solo tu, come admin)")
    if n_hidden and not include_hidden:
        st.caption(f"🔒 I voti di {n_hidden} periodo{'' if n_hidden == 1 else 'i'} non sono ancora stati rivelati e non sono inclusi.")
    data = full_data if include_hidden else L.visible_data(full_data)
    if L.ratings(data).empty and section not in ("Desiderati", "Proponenti"):
        empty_ratings_note()
        return
    if section in ("Classifica", "Generi", "Proponenti"):
        st.session_state["_pesati"] = drops_toggle("stats")
    {
        "Classifica": stats_ranking,
        "Membri": stats_members,
        "Generi": stats_tags,
        "Hype": stats_hype,
        "Affinità": stats_affinity,
        "Proponenti": stats_proposers,
        "Desiderati": stats_wishlist,
    }[section](data, me)


def stats_ranking(data, me):
    gs = L.game_summary(data, st.session_state.get("_pesati", True))
    if gs.empty:
        st.info("Nessun gioco ha valutazioni con questo filtro.")
        return
    order = st.radio("Ordina per", ["FINAL medio", "Più divisivi", "Gradimento normalizzato"], horizontal=True)
    key = {"FINAL medio": "final_medio", "Più divisivi": "divisivita", "Gradimento normalizzato": "gradimento_normalizzato"}[order]
    gs = gs.sort_values(key, ascending=False)
    x_scale = alt.Scale(domain=[0, 10]) if key == "final_medio" else alt.Undefined
    chart = alt.Chart(gs).mark_bar().encode(
        x=alt.X(f"{key}:Q", title=order, scale=x_scale),
        y=alt.Y("gioco:N", sort="-x", title=None),
        tooltip=["gioco", alt.Tooltip(f"{key}:Q", format=".1f"), "valutazioni"],
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        gs[["gioco", "final_medio", "divisivita", "valutazioni"]],
        hide_index=True,
        column_config={
            "gioco": "Gioco",
            "final_medio": st.column_config.NumberColumn("FINAL", format="%.1f"),
            "divisivita": st.column_config.NumberColumn("Divis.", format="%.1f", help="Deviazione standard dei FINAL: più è alta, più il gruppo è spaccato."),
            "valutazioni": "Voti",
        },
    )
    with st.expander("Tutti i dettagli"):
        st.dataframe(
        gs[["gioco", "final_medio", "media_categorie", "divisivita", "gradimento_normalizzato", "valutazioni", "abbandoni", "ore_medie"]],
        hide_index=True,
        column_config={
            "gioco": "Gioco",
            "final_medio": st.column_config.NumberColumn("FINAL medio", format="%.1f"),
            "media_categorie": st.column_config.NumberColumn("Media categorie", format="%.1f"),
            "divisivita": st.column_config.NumberColumn("Divisività", format="%.1f", help="Deviazione standard dei FINAL: più è alta, più il gruppo è spaccato."),
            "gradimento_normalizzato": st.column_config.NumberColumn("Normalizzato", format="%+.1f", help="Di quanto il gioco sta sopra (+) o sotto (−) la media personale di chi l'ha votato."),
            "valutazioni": "Voti",
            "abbandoni": "Abbandoni",
            "ore_medie": st.column_config.NumberColumn("Ore medie", format="%.0f"),
        },
        )
    with st.expander("Medie per categoria"):
        cat = gs[["gioco"] + L.CATEGORIE].rename(columns=L.ETICHETTE)
        st.dataframe(cat, hide_index=True, column_config=num_cols(cat.columns[1:]))


def stats_members(data, me):
    ms = L.member_summary(data)
    table = ms[["membro", "final"] + L.CATEGORIE + ["giochi_valutati", "ore_totali", "abbandoni"]].rename(
        columns={**L.ETICHETTE, "membro": "Membro", "giochi_valutati": "Giochi", "ore_totali": "Ore totali", "abbandoni": "Abbandoni"}
    )
    st.dataframe(table, hide_index=True, column_config={**num_cols(["FINAL"] + [L.ETICHETTE[c] for c in L.CATEGORIE]),
                                                        "Ore totali": st.column_config.NumberColumn(format="%.0f")})

    st.markdown("**Profilo di un membro rispetto al gruppo**")
    nm = L.name_map(data)
    choices = ms["member_id"].tolist()
    who = st.selectbox("Membro", choices, format_func=nm.get, index=choices.index(me) if me in choices else 0)
    r = L.ratings(data)
    group = r[L.CATEGORIE + ["final"]].mean()
    mine = r.loc[r["member_id"] == who, L.CATEGORIE + ["final"]].mean()
    order = [L.ETICHETTE[c] for c in L.CATEGORIE + ["final"]]
    comp = pd.DataFrame(
        {"categoria": order * 2,
         "tipo": [nm.get(who)] * len(order) + ["Gruppo"] * len(order),
         "voto": list(mine.values) + list(group.values)}
    ).dropna()
    st.altair_chart(dumbbell(comp, "categoria", ["Gruppo", nm.get(who)], y_sort=order), width="stretch",
                    height=dumbbell_height(comp, "categoria"))


def dumbbell(df, y: str, order: list[str], y_sort=None):
    """Due punti per riga (es. hype e FINAL) uniti da una linea: leggibile anche su schermi stretti."""
    colors = alt.Scale(domain=order, range=["#9DB0FF", "#3D5AFE"])
    base = alt.Chart(df).encode(y=alt.Y(f"{y}:N", title=None, sort=y_sort, axis=alt.Axis(labelLimit=150, labelOverlap=False)))
    rule = base.mark_rule(color="#9AA3C0", strokeWidth=2).encode(
        x=alt.X("min(voto):Q", scale=alt.Scale(domain=[0, 10]), title=None), x2="max(voto):Q")
    pts = base.mark_circle(size=140, opacity=1).encode(
        x="voto:Q", color=alt.Color("tipo:N", scale=colors, legend=alt.Legend(title=None, orient="top")),
        tooltip=[y, "tipo", alt.Tooltip("voto:Q", format=".1f")])
    return rule + pts


def dumbbell_height(df, y: str) -> int:
    return max(140, 44 * df[y].nunique() + 60)


def heatmap(df, x, y, value, domain=(1, 10), fmt_str=".1f"):
    base = alt.Chart(df).encode(
        x=alt.X(f"{x}:N", title=None, axis=alt.Axis(labelAngle=-60, labelOverlap=False, labelFontSize=10)),
        y=alt.Y(f"{y}:N", title=None, axis=alt.Axis(labelOverlap=False)),
    )
    rect = base.mark_rect().encode(
        color=alt.Color(f"{value}:Q", scale=alt.Scale(domain=list(domain), scheme="blues"), legend=None),
        tooltip=[x, y, alt.Tooltip(f"{value}:Q", format=fmt_str)],
    )
    text = base.mark_text(fontSize=11).encode(
        text=alt.Text(f"{value}:Q", format=fmt_str),
        color=alt.condition(f"datum.{value} > {(domain[0] + domain[1]) / 2}", alt.value("white"), alt.value("black")),
    )
    return rect + text


def stats_tags(data, me):
    ts = L.tag_summary(data, st.session_state.get("_pesati", True))
    st.dataframe(ts, hide_index=True, column_config={
        "tag": "Genere", "final_medio": st.column_config.NumberColumn("FINAL medio", format="%.1f"),
        "giochi": "Giochi", "abbandoni": "Abbandoni"})
    st.markdown("**FINAL medio per genere e membro**")
    st.caption("Un gioco con più tag conta in ciascun genere.")
    st.altair_chart(heatmap(L.tag_member_matrix(data), "membro", "tag", "final"), width="stretch")


def stats_hype(data, me):
    per_game, per_member = L.hype_vs_reality(data)
    if per_game.empty:
        st.info("Servono sia l'hype sia la valutazione della stessa persona sullo stesso gioco.")
        return
    st.markdown("**Aspettativa contro voto finale, per gioco**")
    long = per_game.melt(id_vars=["gioco"], value_vars=["hype_medio", "final_medio"], var_name="tipo", value_name="voto")
    long["tipo"] = long["tipo"].map({"hype_medio": "Hype", "final_medio": "FINAL"})
    st.altair_chart(dumbbell(long, "gioco", ["Hype", "FINAL"]), width="stretch", height=dumbbell_height(long, "gioco"))

    st.markdown("**Chi si esalta e chi si sottovaluta**")
    st.caption("Differenza media tra FINAL e hype: positiva = i giochi ti piacciono più del previsto.")
    chart = alt.Chart(per_member).mark_bar().encode(
        x=alt.X("delta:Q", title="FINAL − hype"),
        y=alt.Y("membro:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
        color=alt.condition("datum.delta >= 0", alt.value("#3D5AFE"), alt.value("#E8833A")),
        tooltip=["membro", alt.Tooltip("delta:Q", format="+.1f"), "n"],
    )
    st.altair_chart(chart, width="stretch", height=max(140, 30 * len(per_member) + 50))


def stats_affinity(data, me):
    aff = L.affinity(data)
    if aff.empty:
        st.info("Servono almeno 2 giochi valutati da entrambe le persone per confrontarle.")
        return
    st.caption("100% = voti identici. Si basa sui FINAL dei giochi valutati da entrambi (almeno 2).")
    my_name = L.name_map(data).get(me)
    mine = aff[(aff["membro_a"] == my_name) | (aff["membro_b"] == my_name)]
    if not mine.empty:
        best = mine.sort_values("affinita", ascending=False).iloc[0]
        twin = best["membro_b"] if best["membro_a"] == my_name else best["membro_a"]
        st.metric("Il tuo gemello di gusto", twin, f"{fmt(best['affinita'], 0)}% su {best['giochi_in_comune']} giochi",
                  delta_color="off", delta_arrow="off")
    sym = pd.concat([aff, aff.rename(columns={"membro_a": "membro_b", "membro_b": "membro_a"})])
    low = max(0, int(sym["affinita"].min() // 5 * 5) - 5)
    st.caption(f"Colori da {low}% (chiaro) a 100% (scuro).")
    st.altair_chart(heatmap(sym, "membro_a", "membro_b", "affinita", domain=(low, 100), fmt_str=".0f"), width="stretch")


def stats_proposers(data, me):
    ps = L.proposer_stats(data, st.session_state.get("_pesati", True))
    if ps.empty:
        st.info("Le statistiche dei proponenti compaiono dopo la prima votazione chiusa.")
        return
    st.dataframe(ps, hide_index=True, column_config={
        "proponente": "Proponente", "periodi": "Periodi",
        "approvazione_media": st.column_config.NumberColumn("Approvazione media", format="%.0f%%", help="In media, quanta parte dei votanti ha scelto ciascuna delle sue opzioni."),
        "final_medio_vincitori": st.column_config.NumberColumn("FINAL medio vincitori", format="%.1f")})


def stats_wishlist(data, me):
    wl = L.wishlist(data)
    if wl.empty:
        st.info("Qui compaiono i giochi proposti che non hanno mai vinto, dopo la prima votazione chiusa.")
        return
    st.caption("Giochi proposti e mai scelti, ordinati per quanto piacevano.")
    st.dataframe(wl[["gioco", "approvazione", "proposto", "voti"]], hide_index=True, column_config={
        "gioco": "Gioco", "approvazione": st.column_config.NumberColumn("Approvazione", format="%.0f%%"),
        "proposto": "Volte proposto", "voti": "Voti totali"})


# ================================================================ catalogo giochi

def filter_games(cat: pd.DataFrame, key: str) -> pd.DataFrame:
    """Filtri sempre visibili: titolo, generi, piattaforme, durata massima. Restituisce i giochi filtrati."""
    all_genres = sorted({t for tags in cat["tags"] for t in tags}, key=str.lower)
    all_plats = sorted({p for plats in cat["platforms"] for p in plats}, key=str.lower)
    with st.container(border=True):
        query = st.text_input("Cerca per titolo", placeholder="Titolo…", key=f"{key}_q")
        genres = ms("Generi", all_genres, key=f"{key}_gen", help="Mostra i giochi che hanno tutti i generi scelti.")
        plats = ms("Piattaforme", all_plats, key=f"{key}_plat", help="Mostra i giochi disponibili su almeno una delle piattaforme scelte.")
        known = cat["ore_storia"].dropna()
        max_hours, keep_unknown, top = None, True, 0
        if not known.empty:
            top = max(int(np.ceil(known.max())), 1)
            max_hours = st.slider("Durata massima (ore, storia principale)", 0, top, top, key=f"{key}_ore",
                                  help="Mostra i giochi che si finiscono in al massimo queste ore.")
            if max_hours < top:
                keep_unknown = st.checkbox("Mostra anche i giochi senza durata", value=False, key=f"{key}_unk")

    res = cat
    if query.strip():
        res = res[res["titolo"].str.contains(query.strip(), case=False, regex=False)]
    if genres:
        res = res[res["tags"].map(lambda t: set(genres) <= set(t))]
    if plats:
        res = res[res["platforms"].map(lambda p: bool(set(plats) & set(p)))]
    if max_hours is not None and max_hours < top:
        res = res[(res["ore_storia"] <= max_hours) | (res["ore_storia"].isna() & keep_unknown)]
    return res


def games_table(res: pd.DataFrame):
    view = pd.DataFrame({
        "Gioco": res["titolo"],
        "Generi": res["tags"].map(", ".join),
        "Piattaforme": res["platforms"].map(", ".join),
        "Ore": res["ore_storia"],
        "HLTB": [u or hltb.search_url(t) for u, t in zip(res["hltb_url"], res["titolo"])],
    }).sort_values("Gioco", key=lambda s: s.str.lower())
    st.dataframe(view, hide_index=True, column_config={
        "Gioco": st.column_config.TextColumn("Gioco", pinned=True),
        "Ore": st.column_config.NumberColumn("⏱ Ore", format="%.0f", help="Storia principale, da HowLongToBeat"),
        "HLTB": st.column_config.LinkColumn("HLTB", display_text="apri"),
    })


def links_line(title: str, hltb_url: str, platforms) -> str:
    return " · ".join(f"[{lbl}]({url})" for lbl, url in L.game_links(title, hltb_url, list(platforms or [])))


def game_card(g, data, pesati: bool = True):
    """Scheda di un gioco: si apre toccando il titolo e ha tre sottoschede."""
    label = g["titolo"] + (f" · ⏱ {fmt(g['ore_storia'], 0)} h" if not np.isnan(g["ore_storia"]) else "")
    with st.expander(label):
        info, durata, club = st.tabs(["📋 Info", "⏱ Durata", "🎮 Nel club"])
        with info:
            if g["sinossi"].strip():
                st.write(g["sinossi"].strip())
            st.markdown(f"**Generi:** {', '.join(g['tags']) or '–'}")
            st.markdown(f"**Piattaforme:** {', '.join(g['platforms']) or '–'}")
            st.markdown(f"**Anno di uscita:** {g['anno'] or '–'}")
            st.markdown("🔗 " + links_line(g["titolo"], g["hltb_url"], g["platforms"]))
        with durata:
            rows = [(lbl, g[c]) for c, lbl in L.DURATE.items()]
            if all(np.isnan(v) for _, v in rows):
                st.write("Durata non disponibile.")
            else:
                for lbl, v in rows:
                    st.markdown(f"**{lbl}:** {fmt(v, 0) + ' h' if not np.isnan(v) else '–'}")
            link = g["hltb_url"] or hltb.search_url(g["titolo"])
            st.markdown(f"[Apri su HowLongToBeat]({link})")
        with club:
            history = L.game_club_history(data, g["game_id"], pesati)
            if not history:
                st.write("Non è ancora stato proposto.")
            for h in history:
                line = f"**Periodo {h['numero']}** · proposto da {h['proponente']}"
                if h["stato"] == "votazione":
                    line += " · votazione in corso"
                elif h["votanti"]:
                    line += f" · {h['voti']} voti su {h['votanti']}"
                line += " · ✅ scelto" if h["vinto"] else ""
                st.markdown(line)
                if h["vinto"]:
                    v = h["valutazioni"]
                    if v is None:
                        st.caption("Nessuna valutazione ancora." if h["rivelato"] else "🔒 Valutazioni non ancora rivelate.")
                    else:
                        st.caption(f"FINAL medio {fmt(h['final_medio'])} su {int(v['final'].notna().sum())} voti"
                                   + ("" if pesati else " (solo chi l'ha finito)"))
                        show = v.assign(peso=v.apply(weight_label, axis=1))
                        st.dataframe(show[["membro", "stato", "final", "ore", "peso"]], hide_index=True, column_config={
                            "membro": "Membro", "stato": "Stato",
                            "final": st.column_config.NumberColumn("FINAL", format="%.1f"),
                            "ore": st.column_config.NumberColumn("Ore", format="%.0f"),
                            "peso": st.column_config.TextColumn("Peso", help="Solo per chi ha abbandonato")})
                        comments_list(v)


def games_view(res: pd.DataFrame, data, key: str, pesati: bool = True):
    """Elenco a schede (predefinito) oppure tabella."""
    mode = st.segmented_control("Vista", ["Schede", "Tabella"], default="Schede", key=f"{key}_view",
                                label_visibility="collapsed") or "Schede"
    if mode == "Tabella":
        st.caption("Tocca l'intestazione di una colonna per ordinare.")
        games_table(res)
        return
    st.caption("Tocca un titolo per aprire la scheda del gioco.")
    for _, g in res.sort_values("titolo", key=lambda s: s.str.lower()).iterrows():
        game_card(g, data, pesati)


def games_tab(full_data, me):
    data = L.visible_data(full_data)
    pesati = drops_toggle("games")
    cat = L.games_catalog(data, pesati)
    if cat.empty:
        st.info("Il database dei giochi è ancora vuoto.")
        return
    res = filter_games(cat, "cat")
    only = st.segmented_control("Mostra", ["Tutti", "Già giocati", "Mai giocati"], default="Tutti",
                                label_visibility="collapsed", key="cat_only") or "Tutti"
    if only != "Tutti":
        res = res[res["giocato"] == (only == "Già giocati")]
    st.caption(f"{len(res)} giochi su {len(cat)}")
    games_view(res, data, "cat", pesati)


# ================================================================ storico

def history_tab(data, me):
    p = L.periods(data)
    p = p[p["stato"] != "bozza"].iloc[::-1]
    if p.empty:
        st.info("Lo storico si riempie man mano che i periodi vengono votati.")
        return
    gm, nm = L.game_map(data), L.name_map(data)
    vis = L.visible_data(data)
    r = L.ratings(vis)
    pesati = drops_toggle("history") if not r.empty else True
    for _, per in p.iterrows():
        winner = gm.get(per["vincitore_id"], "da decidere")
        pr = r[r["period_id"] == per["period_id"]]
        revealed = L.is_revealed(per)
        avg = fmt(L.final_average(pr, pesati)) if not pr.empty else "–"
        if per["stato"] == "votazione":
            title = f"#{per['numero']} · votazione in corso"
        else:
            title = f"#{per['numero']} · {winner} · " + (f"FINAL {avg}" if revealed else "🔒 voti nascosti")
        with st.expander(title):
            st.caption(f"{L.ETICHETTE_STATO.get(per['stato'], per['stato'])} · proposto da {nm.get(per['proponente_id'], '?')}"
                       + (f" · {fmt_date(per['data'])}" if per["data"] else ""))
            ph = L.period_hype(vis, per["period_id"])
            if not ph.empty:
                st.caption(f"Hype medio {fmt(ph['voto'].mean())} su {len(ph)} · "
                           + " · ".join(f"{m} {fmt(v)}" for m, v in zip(ph["membro"], ph["voto"])))
            if per["stato"] == "votazione":
                st.write("Votazione in corso: i risultati si vedono alla chiusura.")
            else:
                counts = L.vote_counts(data, per)
                st.dataframe(counts[["gioco", "voti"]], hide_index=True, column_config={"gioco": "Opzione", "voti": "Voti"})
            if per["stato"] in ("in_gioco", "chiuso") and not revealed:
                st.write("🔒 Le valutazioni verranno rivelate dall'admin alla serata.")
            if not pr.empty:
                show = pr.assign(peso=pr.apply(weight_label, axis=1)).sort_values("final", ascending=False)
                st.dataframe(show[["membro", "stato", "final", "ore", "peso"]], hide_index=True, column_config={
                    "membro": "Membro", "stato": "Stato", "final": st.column_config.NumberColumn("FINAL", format="%.1f"),
                    "ore": st.column_config.NumberColumn("Ore", format="%.0f"),
                    "peso": st.column_config.TextColumn("Peso", help="Solo per chi ha abbandonato")})
                comments_list(show)


# ================================================================ guida

def show_guide():
    path = HERE / "GUIDA_MEMBRI.md"
    st.markdown(path.read_text(encoding="utf-8") if path.exists() else "Guida non trovata.")


# ================================================================ admin

def admin_gate(data):
    if st.session_state.get("admin_ok"):
        if st.button("Esci dall'area admin"):
            st.session_state["admin_ok"] = False
            st.rerun()
        admin_panel(data)
        return
    expected = admin_expected()
    if not expected:
        st.error("Manca `admin_password` nei secrets dell'app.")
        return
    if not secret("admin_password"):
        st.caption("Modalità locale: la password admin è “admin”.")
    if locked():
        return
    with st.form("admin_login"):
        pw = st.text_input("Password admin", type="password")
        ok = st.form_submit_button("Entra come admin")
    if ok:
        import hmac
        if hmac.compare_digest(pw, str(expected)):
            st.session_state.update(admin_ok=True, fails=0)
            st.rerun()
        fails = st.session_state.get("fails", 0) + 1
        st.session_state["fails"] = fails
        if fails >= MAX_TENTATIVI:
            st.session_state.update(lock_until=time.time() + BLOCCO_SECONDI, fails=0)
        st.error("Password sbagliata.")


def admin_panel(data):
    if isinstance(get_store(), LocalStore):
        st.warning("Modalità locale: i dati sono salvati in file CSV su questo computer, non nel foglio Google.")
    section = st.segmented_control("Gestione", ["Periodi", "Giochi", "Tag", "Membri", "Dati"], default="Periodi",
                                   key="admin_section") or "Periodi"
    {"Periodi": admin_periods, "Giochi": admin_games, "Tag": admin_tags, "Membri": admin_members,
     "Dati": admin_data}[section](data)


def update_period(data, period_id: str, **changes) -> bool:
    df = data["periodi"].copy()
    for k, v in changes.items():
        df.loc[df["period_id"] == period_id, k] = v
    return save_table("periodi", df)


def admin_periods(data):
    nm, gm = L.name_map(data), L.game_map(data)
    m = L.members(data)
    active_ids = m.loc[m["attivo"], "member_id"].tolist()
    games = sorted(gm, key=lambda g: gm[g].lower())

    with st.expander("➕ Nuovo periodo", expanded=False):
        if not active_ids or len(games) < 2:
            st.info("Servono almeno un membro e due giochi. Aggiungili nelle sezioni Membri e Giochi.")
        else:
            with st.form("nuovo_periodo", clear_on_submit=True):
                prop = st.selectbox("Proponente", active_ids, format_func=nm.get)
                when = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
                opts = ms("Opzioni (fino a 5)", games, format_func=gm.get, max_selections=5,
                                      help="Se un gioco non c'è, aggiungilo prima nella sezione Giochi.")
                start = st.radio("Stato iniziale", ["bozza", "votazione"], format_func=L.ETICHETTE_STATO.get, horizontal=True)
                ok = st.form_submit_button("Crea periodo", type="primary")
            if ok:
                if len(opts) < 2:
                    st.error("Servono almeno 2 opzioni.")
                else:
                    nums = L.periods(data)["numero_n"]
                    numero = int(nums.max()) + 1 if nums.notna().any() else 1
                    row = {"period_id": new_id(), "numero": str(numero), "proponente_id": prop, "data": when.isoformat(),
                           "stato": start, "opzioni": L.join_list(opts), "vincitore_id": "", "rivelato": ""}
                    if save_table("periodi", pd.concat([data["periodi"], pd.DataFrame([row])], ignore_index=True)):
                        st.toast(f"Periodo {numero} creato")
                        st.rerun()

    p = L.periods(data).iloc[::-1]
    for _, per in p.iterrows():
        pid, stato = per["period_id"], per["stato"]
        label = f"#{per['numero']} · {nm.get(per['proponente_id'], '?')} · {L.ETICHETTE_STATO.get(stato, stato)}"
        with st.expander(label, expanded=stato in ("votazione", "in_gioco")):
            options = L.split_list(per["opzioni"])

            if stato == "bozza":
                with st.form(f"bozza_{pid}"):
                    new_opts = ms("Opzioni", games, default=[g for g in options if g in gm],
                                              format_func=gm.get, max_selections=5)
                    c1, c2 = st.columns(2)
                    save = c1.form_submit_button("Salva opzioni")
                    open_vote = c2.form_submit_button("Apri votazione", type="primary")
                if (save or open_vote) and len(new_opts) >= 2:
                    changes = {"opzioni": L.join_list(new_opts)}
                    if open_vote:
                        changes["stato"] = "votazione"
                    if update_period(data, pid, **changes):
                        st.rerun()
                elif save or open_vote:
                    st.error("Servono almeno 2 opzioni.")
                if st.button("Elimina bozza", key=f"del_{pid}"):
                    if save_table("periodi", data["periodi"][data["periodi"]["period_id"] != pid]):
                        st.rerun()

            if stato in ("votazione", "in_gioco", "chiuso"):
                voters = L.eligible_voters(data, per)
                votes = L.period_votes(data, per)
                missing = [nm.get(v) for v in voters if v not in set(votes["member_id"])]
                counts = L.vote_counts(data, per)
                st.caption(f"Hanno votato {len(votes)} su {len(voters)}."
                           + (f" Mancano: {', '.join(missing)}." if missing and stato == "votazione" else ""))
                st.dataframe(counts[["gioco", "voti", "percentuale"]], hide_index=True, column_config={
                    "gioco": "Opzione", "voti": "Voti",
                    "percentuale": st.column_config.NumberColumn("% votanti", format="%.0f%%")})
                if not votes.empty:
                    with st.expander("Chi ha votato cosa (solo admin)"):
                        who = pd.DataFrame({
                            "Membro": votes["member_id"].map(nm),
                            "Scelte": votes["scelte"].map(lambda x: ", ".join(gm.get(g, g) for g in L.split_list(x)) or "(nessuna)"),
                        })
                        st.dataframe(who.sort_values("Membro"), hide_index=True)

            if stato == "votazione":
                top = L.leaders(counts)
                if len(top) > 1:
                    st.warning("Parità tra: " + ", ".join(gm.get(g, g) for g in top)
                               + ". Le regole per i pareggi non sono ancora definite: scegli tu il vincitore.")
                with st.form(f"chiudi_{pid}"):
                    win = st.selectbox("Vincitore", options, format_func=gm.get,
                                       index=options.index(top[0]) if len(top) == 1 else None,
                                       placeholder="Scegli il vincitore")
                    ok = st.form_submit_button("Chiudi votazione e conferma il vincitore", type="primary")
                if ok:
                    if not win:
                        st.error("Scegli il vincitore.")
                    elif update_period(data, pid, stato="in_gioco", vincitore_id=win):
                        st.rerun()

            if stato == "in_gioco":
                rated = L.latest(data["valutazioni"], ["period_id", "member_id"])
                rated = rated[rated["period_id"] == pid]
                active_names = [nm.get(x) for x in active_ids]
                done = [nm.get(x) for x in rated["member_id"]]
                todo = [n for n in active_names if n not in done]
                st.caption(f"Valutazioni: {len(done)} su {len(active_names)}." + (f" Mancano: {', '.join(todo)}." if todo else ""))
                if st.button("Chiudi il periodo (blocca le valutazioni)", key=f"close_{pid}", type="primary"):
                    if update_period(data, pid, stato="chiuso"):
                        st.rerun()

            if stato in ("in_gioco", "chiuso"):
                admin_ratings_table(data, per)
                if L.is_revealed(per):
                    st.success("Voti rivelati: tutti vedono valutazioni e statistiche di questo periodo.")
                else:
                    st.info("🔒 Voti nascosti: i membri vedono solo i propri.")
                    if st.button("Rivela i voti a tutti", key=f"reveal_{pid}", type="primary"):
                        if update_period(data, pid, rivelato="1"):
                            st.toast("Voti rivelati")
                            st.rerun()

            with st.popover("Correzioni"):
                st.caption("Per sistemare errori. Cambiare stato non cancella voti né valutazioni.")
                new_state = st.selectbox("Stato", L.STATI_PERIODO, index=L.STATI_PERIODO.index(stato) if stato in L.STATI_PERIODO else 0,
                                         format_func=L.ETICHETTE_STATO.get, key=f"force_{pid}")
                if st.button("Applica", key=f"apply_{pid}"):
                    if update_period(data, pid, stato=new_state):
                        st.rerun()
                if L.is_revealed(per) and st.button("Nascondi di nuovo i voti", key=f"hide_{pid}"):
                    if update_period(data, pid, rivelato=""):
                        st.rerun()


def admin_ratings_table(data, per):
    """Tutte le valutazioni del periodo, membro per membro. Visibile solo all'admin."""
    pid = per["period_id"]
    nm = L.name_map(data)
    rows = L.latest(data["valutazioni"], ["period_id", "member_id"])
    rows = rows[rows["period_id"] == pid]
    if rows.empty:
        return
    hype = L.hype_table(data)
    hype = hype[hype["period_id"] == pid].set_index("member_id")["voto"]
    tab = pd.DataFrame({"Membro": rows["member_id"].map(nm).values, "Stato": rows["stato"].values,
                        "Hype": rows["member_id"].map(hype).astype(float).values})
    for c in ["final"] + L.CATEGORIE + ["ore"]:
        tab[L.ETICHETTE[c]] = rows[c].map(L.to_num).astype(float).values
    weights = L.ratings(data).set_index(["period_id", "member_id"])["peso"]
    tab["Peso"] = [f"{weights.get((pid, m), 1) * 100:.0f}%" if s == "abbandonato" and not np.isnan(L.to_num(f)) else ""
                   for m, s, f in zip(rows["member_id"], rows["stato"], rows["final"])]
    tab["commento"] = rows["commento"].values
    label = f"Valutazioni di ogni membro ({len(tab)})"
    if not L.is_revealed(per):
        label += " · solo admin"
    with st.expander(label):
        numeric = ["Hype", "FINAL"] + [L.ETICHETTE[c] for c in L.CATEGORIE]
        tab = tab.sort_values("FINAL", ascending=False)
        st.dataframe(tab.drop(columns="commento"), hide_index=True,
                     column_config={**num_cols(numeric), "Ore": st.column_config.NumberColumn(format="%.0f")})
        comments_list(tab, name_col="Membro")


GAME_FIELDS = ["titolo", "tag", "anno", "piatt", "ore_storia", "ore_extra", "ore_completo", "hltb_url", "hltb_id", "sinossi"]


def _gkey(prefix: str, field: str) -> str:
    return f"{prefix}_{field}"


def init_game_fields(prefix: str, row=None):
    """Prepara i valori del modulo gioco nello stato della sessione.

    Streamlit cancella le chiavi dei widget che non vengono mostrati (per esempio quando
    si passa a un'altra sezione dell'area admin). Se manca il titolo, il modulo è stato
    "dimenticato": lo reimpostiamo tutto, compresi i dati HLTB non legati a un widget.
    """
    if _gkey(prefix, "titolo") in st.session_state:
        return
    get = (lambda c: str(row[c]) if row is not None and c in row else "")
    for k in [k for k in st.session_state if str(k).startswith(prefix + "_")]:
        del st.session_state[k]
    st.session_state[_gkey(prefix, "titolo")] = get("titolo")
    st.session_state[_gkey(prefix, "tag")] = L.split_list(get("tag"))
    st.session_state[_gkey(prefix, "anno")] = get("anno")
    st.session_state[_gkey(prefix, "piatt")] = L.split_multi(get("piattaforme"))
    for c in ["ore_storia", "ore_extra", "ore_completo", "hltb_url", "hltb_id", "sinossi"]:
        st.session_state[_gkey(prefix, c)] = get(c) if get(c) != "nan" else ""


def reset_game_fields(prefix: str):
    for k in [k for k in st.session_state if str(k).startswith(prefix + "_")]:
        del st.session_state[k]


def fill_from_hltb(prefix: str):
    """Callback: copia nel modulo il risultato HLTB scelto."""
    results = st.session_state.get(_gkey(prefix, "res")) or []
    idx = st.session_state.get(_gkey(prefix, "pick"))
    if idx is None or idx >= len(results):
        return
    r = results[idx]
    if not st.session_state.get(_gkey(prefix, "titolo")):
        st.session_state[_gkey(prefix, "titolo")] = r["nome"]
    if r["anno"]:
        st.session_state[_gkey(prefix, "anno")] = r["anno"]
    current = st.session_state.get(_gkey(prefix, "piatt")) or []
    st.session_state[_gkey(prefix, "piatt")] = current + [p for p in r["piattaforme"] if p not in current]
    for c in ["ore_storia", "ore_extra", "ore_completo"]:
        st.session_state[_gkey(prefix, c)] = "" if r[c] is None else f"{r[c]:g}"
    st.session_state[_gkey(prefix, "hltb_url")] = r["url"]
    st.session_state[_gkey(prefix, "hltb_id")] = r["hltb_id"]
    genres = hltb.fetch_genres(r["hltb_id"])
    if genres:
        current = st.session_state.get(_gkey(prefix, "tag")) or []
        st.session_state[_gkey(prefix, "tag")] = current + [g for g in genres if g not in current]


def hltb_search_block(prefix: str):
    st.markdown("**Dati da HowLongToBeat** (facoltativo)")
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    query = c1.text_input("Titolo da cercare", value=st.session_state.get(_gkey(prefix, "titolo"), ""),
                          key=_gkey(prefix, "q"))
    if c2.button("🔍 Cerca", key=_gkey(prefix, "go"), width="stretch"):
        with st.spinner("Cerco su HowLongToBeat…"):
            st.session_state[_gkey(prefix, "res")] = hltb.search(query)
        st.session_state[_gkey(prefix, "searched")] = query
    if not st.session_state.get(_gkey(prefix, "searched")):
        return
    results = st.session_state.get(_gkey(prefix, "res"))
    link = hltb.search_url(st.session_state[_gkey(prefix, "searched")])
    if results is None:
        st.warning(f"La ricerca su HowLongToBeat non è riuscita: il sito può aver cambiato qualcosa o bloccato la richiesta. "
                   f"Puoi [cercarlo tu]({link}) e copiare i dati nei campi qui sotto.")
    elif not results:
        st.info(f"Nessun risultato. Prova con il titolo in inglese, oppure [cercalo tu]({link}).")
    else:
        st.radio("Risultati", range(len(results)), format_func=lambda i: hltb.label(results[i]),
                 key=_gkey(prefix, "pick"), index=0)
        st.button("Usa questo risultato", key=_gkey(prefix, "use"), on_click=fill_from_hltb, args=(prefix,))


def game_form(data, prefix: str, submit_label: str):
    """Modulo gioco condiviso tra 'nuovo' e 'modifica'. Restituisce la riga se inviato e valido."""
    tags = sorted(set(L.all_tags(data)) | set(st.session_state.get(_gkey(prefix, "tag")) or []), key=str.lower)
    plats = sorted(set(L.PIATTAFORME_BASE) | set(L.all_platforms(data)) | set(st.session_state.get(_gkey(prefix, "piatt")) or []),
                   key=str.lower)
    with st.form(_gkey(prefix, "form")):
        st.text_input("Titolo", key=_gkey(prefix, "titolo"))
        ms("Generi", tags, accept_new_options=True, key=_gkey(prefix, "tag"), help="Puoi scriverne di nuovi.")
        ms("Piattaforme", plats, accept_new_options=True, key=_gkey(prefix, "piatt"))
        st.text_input("Anno di uscita", key=_gkey(prefix, "anno"))
        st.text_area("Sinossi (senza spoiler)", key=_gkey(prefix, "sinossi"), max_chars=800, height=120,
                     help="Due o tre frasi per far capire agli altri di che gioco si tratta. Compare quando il gioco "
                          "viene proposto e nella sua scheda.")
        st.caption("Durata in ore (da HowLongToBeat o a mano). Lascia vuoto se non la conosci.")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Storia", key=_gkey(prefix, "ore_storia"))
        c2.text_input("+ Extra", key=_gkey(prefix, "ore_extra"))
        c3.text_input("Completo", key=_gkey(prefix, "ore_completo"))
        st.text_input("Link HowLongToBeat", key=_gkey(prefix, "hltb_url"), placeholder="https://howlongtobeat.com/game/…")
        ok = st.form_submit_button(submit_label, type="primary")
    if not ok:
        return None
    v = {f: st.session_state.get(_gkey(prefix, f)) for f in GAME_FIELDS}
    hours = {}
    for c in ["ore_storia", "ore_extra", "ore_completo"]:
        raw = str(v[c] or "").strip()
        num = L.to_num(raw)
        if raw and np.isnan(num):
            st.error(f"“{raw}” non è un numero di ore valido.")
            return None
        hours[c] = "" if np.isnan(num) else f"{num:g}"
    if not str(v["titolo"]).strip():
        st.error("Scrivi il titolo.")
        return None
    return {"titolo": v["titolo"].strip(), "tag": L.join_list(v["tag"] or []), "anno": str(v["anno"] or "").strip(),
            "piattaforme": L.join_list(v["piatt"] or []), "hltb_url": str(v["hltb_url"] or "").strip(),
            "hltb_id": str(v["hltb_id"] or "").strip(), "sinossi": str(v["sinossi"] or "").strip(), **hours}


def admin_games(data):
    g = data["giochi"]
    with st.expander("➕ Nuovo gioco", expanded=False):
        init_game_fields("ng")
        hltb_search_block("ng")
        row = game_form(data, "ng", "Aggiungi gioco")
        if row is not None:
            if row["titolo"].lower() in {t.lower() for t in g["titolo"]}:
                st.error("Questo gioco c'è già.")
            elif save_table("giochi", pd.concat([g, pd.DataFrame([{"game_id": new_id(), **row}])], ignore_index=True)):
                reset_game_fields("ng")
                st.toast("Gioco aggiunto")
                st.rerun()

    if g.empty:
        st.info("Nessun gioco ancora.")
        return
    gm = L.game_map(data)
    ids = sorted(gm, key=lambda x: gm[x].lower())
    gid = st.selectbox("Modifica un gioco", ids, format_func=gm.get, index=None, placeholder="Scegli un gioco")
    if gid:
        prefix = f"eg_{gid}"
        init_game_fields(prefix, g[g["game_id"] == gid].iloc[0])
        hltb_search_block(prefix)
        row = game_form(data, prefix, "Salva modifiche")
        if row is not None:
            others = {t.lower() for i, t in zip(g["game_id"], g["titolo"]) if i != gid}
            if row["titolo"].lower() in others:
                st.error("Esiste già un altro gioco con questo titolo.")
            else:
                df = g.copy()
                for k, v in row.items():
                    df.loc[df["game_id"] == gid, k] = v
                if save_table("giochi", df):
                    reset_game_fields(prefix)
                    st.toast("Gioco aggiornato")
                    st.rerun()

    st.markdown("**Database dei giochi**")
    cat = L.games_catalog(data)
    res = filter_games(cat, "adm")
    st.caption(f"{len(res)} giochi su {len(cat)}. Nelle schede, qui vedi anche le valutazioni non ancora rivelate.")
    games_view(res, data, "adm")


def admin_tags(data):
    kind = st.segmented_control("Tipo di tag", ["Generi", "Piattaforme"], default="Generi", key="tag_kind") or "Generi"
    column = "tag" if kind == "Generi" else "piattaforme"
    counts = L.tag_counts(data, column)
    if not counts:
        st.info(f"Nessun tag di tipo {kind.lower()} nel database.")
        return
    st.dataframe(pd.DataFrame({"Tag": list(counts), "Giochi": list(counts.values())}), hide_index=True)

    tag = st.selectbox("Tag da modificare", list(counts), index=None, placeholder="Scegli un tag",
                       format_func=lambda t: f"{t} ({counts[t]} gioc{'o' if counts[t] == 1 else 'hi'})", key=f"tag_sel_{kind}")
    if not tag:
        return
    games = data["giochi"]
    splitter = L.split_list if column == "tag" else L.split_multi
    used_by = games.loc[games[column].map(lambda v: tag in splitter(v)), "titolo"].tolist()
    st.caption("Usato da: " + ", ".join(used_by))

    new_name = st.text_input("Nuovo nome", value=tag, key=f"tag_new_{kind}_{tag}",
                             help="Se scrivi il nome di un tag che esiste già, i due tag vengono uniti.")
    c1, c2 = st.columns(2)
    if c1.button("Rinomina", key=f"tag_ren_{kind}_{tag}", width="stretch"):
        target = new_name.strip()
        if not target:
            st.error("Scrivi il nuovo nome.")
        elif target == tag:
            st.info("Il nome non è cambiato.")
        elif save_table("giochi", L.replace_tag(games, column, tag, target)):
            merged = " (uniti)" if target in counts else ""
            st.toast(f"“{tag}” → “{target}”{merged}")
            st.rerun()
    with c2.popover("Elimina", width="stretch"):
        st.write(f"Tolgo “{tag}” da {len(used_by)} gioc{'o' if len(used_by) == 1 else 'hi'}. I giochi restano, perdono solo questo tag.")
        if st.button("Sì, elimina il tag", key=f"tag_del_{kind}_{tag}", type="primary"):
            if save_table("giochi", L.replace_tag(games, column, tag, None)):
                st.toast(f"Tag “{tag}” eliminato")
                st.rerun()


def admin_members(data):
    m = L.members(data)
    with st.form("nuovo_membro", clear_on_submit=True):
        name = st.text_input("Aggiungi un membro", placeholder="Nome o soprannome")
        ok = st.form_submit_button("Aggiungi")
    if ok:
        if not name.strip():
            st.error("Scrivi un nome.")
        elif name.strip().lower() in {n.lower() for n in m["nome"]}:
            st.error("Esiste già un membro con questo nome.")
        else:
            row = {"member_id": new_id(), "nome": name.strip(), "attivo": "1"}
            if save_table("membri", pd.concat([data["membri"], pd.DataFrame([row])], ignore_index=True)):
                st.rerun()

    if m.empty:
        return
    st.dataframe(m[["nome", "attivo", "pin_impostato"]], hide_index=True,
                 column_config={"nome": "Nome", "attivo": "Attivo", "pin_impostato": "PIN impostato"})
    names = dict(zip(m["member_id"], m["nome"]))
    mid = st.selectbox("Gestisci un membro", list(names), format_func=names.get, index=None, placeholder="Scegli un membro")
    if not mid:
        return
    row = m[m["member_id"] == mid].iloc[0]
    new_name = st.text_input("Nome", value=row["nome"], key=f"name_{mid}")
    c1, c2, c3 = st.columns(3)
    if c1.button("Salva nome", key=f"rn_{mid}"):
        df = data["membri"].copy()
        df.loc[df["member_id"] == mid, "nome"] = new_name.strip()
        if save_table("membri", df):
            st.rerun()
    if c2.button("Disattiva" if row["attivo"] else "Riattiva", key=f"act_{mid}"):
        df = data["membri"].copy()
        df.loc[df["member_id"] == mid, "attivo"] = "0" if row["attivo"] else "1"
        if save_table("membri", df):
            st.rerun()
    if c3.button("Azzera PIN", key=f"pin_{mid}", disabled=not row["pin_impostato"]):
        if save_append("pin", {"member_id": mid, "pin_hash": "", "ts": now_ts()}):
            st.toast(f"PIN di {row['nome']} azzerato: al prossimo accesso ne sceglierà uno nuovo.")
            st.rerun()
    st.caption("Un membro disattivato non compare più nell'accesso e non conta tra i votanti, ma i suoi voti restano nelle statistiche.")


def admin_data(data):
    if data["membri"].empty and data["giochi"].empty and data["periodi"].empty:
        st.markdown("**Importa i dati iniziali**")
        st.write("Carica i 10 membri, i 10 giochi e i due periodi del foglio Level One (Hellblade in gioco, proposte di Bubu in bozza).")
        if st.button("Importa dati iniziali", type="primary"):
            ok = all(save_table(t, df) for t, df in seed.build().items())
            if ok:
                st.toast("Dati importati")
                st.rerun()
        st.divider()

    st.markdown("**Completa i giochi da HowLongToBeat**")
    g = data["giochi"]
    no_hltb = g["hltb_id"].str.strip() == ""
    no_genres = g["tag"].str.strip() == ""
    todo = g[no_hltb | no_genres]
    st.caption(f"{int(no_hltb.sum())} giochi senza dati HowLongToBeat, {int(no_genres.sum())} senza generi. "
               "L'app prende il risultato più simile al titolo; quelli incerti li segnala da controllare a mano. "
               "I generi vengono solo aggiunti, mai tolti.")
    if len(todo) and st.button("Completa i dati mancanti"):
        df, report = g.copy(), []
        bar = st.progress(0.0)
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            mask, hid, esito = df["game_id"] == row["game_id"], row["hltb_id"].strip(), ""
            if not hid:
                res = hltb.search(row["titolo"], limit=1)
                if res is None:
                    esito = "ricerca non riuscita"
                elif not res or res[0]["similarita"] < 0.75:
                    esito = "da controllare a mano"
                else:
                    r = res[0]
                    plats = L.split_multi(row["piattaforme"])
                    df.loc[mask, "piattaforme"] = L.join_list(plats + [p for p in r["piattaforme"] if p not in plats])
                    if not row["anno"].strip():
                        df.loc[mask, "anno"] = r["anno"]
                    for c in ["ore_storia", "ore_extra", "ore_completo"]:
                        df.loc[mask, c] = "" if r[c] is None else f"{r[c]:g}"
                    df.loc[mask, ["hltb_id", "hltb_url"]] = [r["hltb_id"], r["url"]]
                    hid, esito = r["hltb_id"], f"ok → {r['nome']}"
            genres_note = ""
            if hid:
                genres = hltb.fetch_genres(hid)
                if genres:
                    current = L.split_list(df.loc[mask, "tag"].iloc[0])
                    df.loc[mask, "tag"] = L.join_list(current + [x for x in genres if x not in current])
                    genres_note = ", ".join(genres)
                else:
                    genres_note = "non trovati" if genres == [] else "pagina non raggiungibile"
            report.append({"Gioco": row["titolo"], "Esito": esito or "dati già presenti", "Generi": genres_note})
            bar.progress(i / len(todo))
        if not df.equals(g):
            save_table("giochi", df)
        st.dataframe(pd.DataFrame(report), hide_index=True)
        st.caption("Controlla gli abbinamenti e i generi in Giochi: se qualcosa è sbagliato, correggilo lì.")
    st.divider()

    st.markdown("**Backup**")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table in SCHEMA:
            z.writestr(f"{table}.csv", data[table].to_csv(index=False))
    st.download_button("Scarica tutti i dati (ZIP di CSV)", buf.getvalue(),
                       file_name=f"level-one-backup-{date.today().isoformat()}.zip", mime="application/zip")
    st.caption("I PIN nel backup sono cifrati. Conserva comunque il file in un posto privato.")

    st.markdown("**Aggiorna**")
    if st.button("Ricarica i dati dal foglio"):
        load_data.clear()
        st.rerun()


# ================================================================ pagina principale

def main():
    try:
        data = load_data()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossibile leggere i dati. Controlla la configurazione (vedi guida admin). Dettaglio: {exc}")
        st.stop()

    restore_session(data)
    me = st.session_state.get("member_id")
    nm = L.name_map(data)
    if me not in nm:
        st.session_state.pop("member_id", None)
        login_view(data)
        sync_cookie(data)
        return

    st.markdown("## 🎮 Level One")
    st.caption(f"Ciao {nm[me]}!")

    tabs = st.tabs(["🗳️ Proposte", "🎮 In gioco", "🕹️ Giochi", "📊 Statistiche", "📜 Storico", "📖 Guida", "🔧 Admin"])
    with tabs[0]:
        proposals_tab(data, me)
    with tabs[1]:
        playing_tab(data, me)
    with tabs[2]:
        games_tab(data, me)
    with tabs[3]:
        stats_tab(data, me)
    with tabs[4]:
        history_tab(data, me)
    with tabs[5]:
        show_guide()
    with tabs[6]:
        admin_gate(data)

    st.divider()
    st.caption(f"Resti connesso per {SESSIONE_MINUTI} minuti dall'ultima azione, anche se ricarichi la pagina.")
    if st.button(f"Esci ({nm[me]})", type="tertiary"):
        st.session_state.pop("member_id", None)
        st.session_state["admin_ok"] = False
        st.rerun()
    sync_cookie(data)

main()
