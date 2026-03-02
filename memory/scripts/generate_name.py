#!/usr/bin/env python3
"""Generate coordinator name syllable.

Three naming styles with 16+16 syllable pools each.
Script picks style + first syllable (Pool A).
Coordinator picks second syllable (Pool B).
"""

import json
import random
import sys

POOLS = {
    1: {
        "style": "closed",
        "description": "Hard, robotic (CVC + CVC)",
        "pool_a": ["Thum", "Triz", "Vret", "Drag", "Lus", "Kron", "Brig", "Plim",
                    "Grek", "Stur", "Falk", "Brox", "Neld", "Drog", "Jask", "Zelt"],
        "pool_b": ["Dim", "Gur", "Pul", "Tros", "Kroy", "Nax", "Belk", "Frim",
                    "Shod", "Velt", "Klun", "Rist", "Bont", "Marg", "Wex", "Drin"]
    },
    2: {
        "style": "open",
        "description": "Soft, melodic (VCV + VCV)",
        "pool_a": ["Ani", "Olli", "Eni", "Ile", "Aru", "Ika", "Ema", "Uli",
                    "Ayo", "Ona", "Isi", "Elo", "Ura", "Oki", "Alu", "Evi"],
        "pool_b": ["Ara", "Oli", "Inu", "Eka", "Umi", "Ola", "Iru", "Ame",
                    "Oti", "Ela", "Uki", "Aro", "Ini", "Uve", "Oma", "Ise"]
    },
    3: {
        "style": "semi-open",
        "description": "Contrasting, hybrid (VC + CV)",
        "pool_a": ["Alk", "Orn", "Ist", "Elm", "Urd", "Ank", "Olt", "Esh",
                    "Arv", "Eld", "Irk", "Usk", "Onk", "Ash", "Irt", "Ung"],
        "pool_b": ["Bra", "Kri", "Sho", "Plu", "Gra", "Flo", "Dre", "Ska",
                    "Bli", "Kla", "Vro", "Pha", "Tri", "Glo", "Ste", "Dru"]
    }
}


def generate():
    style_num = random.randint(1, 3)
    pool = POOLS[style_num]
    syllable = random.choice(pool["pool_a"])
    return {
        "style": style_num,
        "style_name": pool["style"],
        "description": pool["description"],
        "syllable": syllable,
        "pool_b": pool["pool_b"]
    }


if __name__ == "__main__":
    result = generate()
    print(json.dumps(result))
