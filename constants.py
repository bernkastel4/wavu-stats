"""Human-readable lookup tables for the numeric ids in wavu replay data.

Sourced from the TEKKEN 8 replay format (same mapping wank.wavu.wiki and the
TK8-thing project use). New characters added in later patches may not be listed
yet -- `main.py check-ids` flags any id present in the DB that is missing here,
and `chara_name()`/`rank_name()` fall back to a readable placeholder.
"""

# chara_id -> character name
CHARACTERS = {
    0: "Paul",
    1: "Law",
    2: "King",
    3: "Yoshimitsu",
    4: "Hwoarang",
    5: "Xiaoyu",
    6: "Jin",
    7: "Bryan",
    8: "Kazuya",
    9: "Steve",
    10: "Jack-8",
    11: "Asuka",
    12: "Devil Jin",
    13: "Feng",
    14: "Lili",
    15: "Dragunov",
    16: "Leo",
    17: "Lars",
    18: "Alisa",
    19: "Claudio",
    20: "Shaheen",
    21: "Nina",
    22: "Lee",
    23: "Kuma",
    24: "Panda",
    28: "Zafina",
    29: "Leroy",
    32: "Jun",
    33: "Reina",
    34: "Azucena",
    35: "Victor",
    36: "Raven",
    38: "Eddy",
    39: "Lidia",
    40: "Heihachi",
    41: "Clive",
    42: "Anna",
    43: "Fahkumram",
    44: "Armor King",
    45: "Mairy Zo",
    46: "Kunimitsu",
}

# rank id (a.k.a. "dan") -> rank name. In the data God of Destruction is 29;
# the game also labels it dan 100, so both map to the same name.
RANKS = {
    0: "Beginner",
    1: "1st Dan",
    2: "2nd Dan",
    3: "Fighter",
    4: "Strategist",
    5: "Combatant",
    6: "Brawler",
    7: "Ranger",
    8: "Cavalry",
    9: "Warrior",
    10: "Assailant",
    11: "Dominator",
    12: "Vanquisher",
    13: "Destroyer",
    14: "Eliminator",
    15: "Garyu",
    16: "Shinryu",
    17: "Tenryu",
    18: "Mighty Ruler",
    19: "Flame Ruler",
    20: "Battle Ruler",
    21: "Fujin",
    22: "Raijin",
    23: "Kishin",
    24: "Bushin",
    25: "Tekken King",
    26: "Tekken Emperor",
    27: "Tekken God",
    28: "Tekken God Supreme",
    29: "God of Destruction",
    # Season 2 (2026) added higher God of Destruction tiers above the base rank.
    30: "God of Destruction I",
    31: "God of Destruction II",
    32: "God of Destruction III",
    33: "God of Destruction IV",
    34: "God of Destruction V",
    35: "God of Destruction VI",
    36: "God of Destruction VII",
    37: "God of Destruction Inf",
    100: "God of Destruction",
}

# Convenience: name -> rank id, for --rank-floor lookups (case/space-insensitive).
RANK_IDS_BY_NAME = {
    name.lower().replace(" ", "_"): rid for rid, name in RANKS.items()
}

REGIONS = {
    0: "Asia",
    1: "Middle East",
    2: "Oceania",
    3: "America",
    4: "Europe",
    5: "Africa",
}

BATTLE_TYPES = {
    1: "quick match",
    2: "ranked match",
    3: "group match",
    4: "player match",
}

STAGES = {
    100: "Arena",
    101: "Arena Underground",
    200: "Urban Square",
    201: "Urban Square Evening",
    300: "Yakushima",
    400: "Coliseum of Fate",
    500: "Rebel Hangar",
    700: "Fallen Destiny",
    900: "Descent into Subconscious",
    1000: "Sanctum",
    1100: "Into the Stratosphere",
    1200: "Ortiz Farm",
    1300: "Celebration On The Seine",
    1400: "Secluded Training Ground",
    1500: "Elegant Palace",
    1600: "Midnight Siege",
}


def chara_name(chara_id):
    return CHARACTERS.get(chara_id, f"Char {chara_id}")


def rank_name(rank_id):
    return RANKS.get(rank_id, f"Rank {rank_id}")


def region_name(region_id):
    return REGIONS.get(region_id, f"Region {region_id}")


def resolve_rank_floor(value):
    """Accept a rank id (int/str digits) or a name like 'tekken_king' / 'Tekken King'.

    Returns the numeric rank id, or None if it can't be resolved.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    key = s.lower().replace(" ", "_")
    return RANK_IDS_BY_NAME.get(key)
