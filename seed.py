"""Dati iniziali presi dal foglio "Level One - Club del Videogioco".

I tag di genere sono una prima proposta: controllali e correggili dall'area admin.
"""

from __future__ import annotations

import pandas as pd

from logic import join_list
from storage import new_id

MEMBRI = ["Ventu", "Bubu", "Rick", "Scand", "Dalla", "Fede", "Marty", "Luca", "Stefano", "Denise"]

GIOCHI = [
    ("Expedition 33", ["RPG"]),
    ("Undertale", ["RPG", "Indie"]),
    ("The Curse of Monkey Island", ["Avventura", "Punta e clicca"]),
    ("Hellblade: Senua's Sacrifice", ["Action", "Avventura", "Narrativo"]),
    ("Half-Life", ["FPS"]),
    ("Kingdom Hearts 1", ["RPG", "Action"]),
    ("Hollow Knight", ["Metroidvania", "Action"]),
    ("Dispatch", ["Narrativo", "Avventura"]),
    ("Regions of Ruin", []),  # tag da completare
    ("Persona 5", ["RPG"]),
]


def build() -> dict[str, pd.DataFrame]:
    member_ids = {name: new_id() for name in MEMBRI}
    membri = pd.DataFrame(
        {"member_id": list(member_ids.values()), "nome": list(member_ids), "attivo": ["1"] * len(member_ids)}
    )

    game_ids = {title: new_id() for title, _ in GIOCHI}
    giochi = pd.DataFrame(
        {
            "game_id": [game_ids[t] for t, _ in GIOCHI],
            "titolo": [t for t, _ in GIOCHI],
            "tag": [join_list(tags) for _, tags in GIOCHI],
            "anno": [""] * len(GIOCHI),
            "piattaforme": [""] * len(GIOCHI),
        }
    )

    p1 = [game_ids[t] for t, _ in GIOCHI[:5]]
    p2 = [game_ids[t] for t, _ in GIOCHI[5:]]
    periodi = pd.DataFrame(
        [
            {
                "period_id": new_id(), "numero": "1", "proponente_id": member_ids["Ventu"],
                "data": "2026-06-16", "stato": "in_gioco", "opzioni": join_list(p1),
                "vincitore_id": game_ids["Hellblade: Senua's Sacrifice"],
            },
            {
                "period_id": new_id(), "numero": "2", "proponente_id": member_ids["Bubu"],
                "data": "", "stato": "bozza", "opzioni": join_list(p2), "vincitore_id": "",
            },
        ]
    )
    return {"membri": membri, "giochi": giochi, "periodi": periodi}
