"""SQLite storage for wavu replay data.

One row per match, keyed on `battle_id`, so re-fetching overlapping time windows
is a harmless no-op (INSERT OR IGNORE). We store the raw API fields verbatim and
do all interpretation at analysis time.
"""

import os
import sqlite3

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "wavu.db")

# Columns match the /api/replays JSON fields exactly.
COLUMNS = [
    "battle_id",       # TEXT primary key
    "battle_at",       # unix seconds
    "battle_type",     # 2 = ranked
    "game_version",    # patch id, e.g. 30101
    "stage_id",
    "winner",          # 1 = p1 won, 2 = p2 won
    "p1_chara_id", "p1_rank", "p1_power", "p1_rating_before", "p1_rating_change",
    "p1_region_id", "p1_area_id", "p1_rounds", "p1_name", "p1_polaris_id",
    "p1_user_id", "p1_lang",
    "p2_chara_id", "p2_rank", "p2_power", "p2_rating_before", "p2_rating_change",
    "p2_region_id", "p2_area_id", "p2_rounds", "p2_name", "p2_polaris_id",
    "p2_user_id", "p2_lang",
]

_INT_COLUMNS = {
    "battle_at", "battle_type", "game_version", "stage_id", "winner",
    "p1_chara_id", "p1_rank", "p1_power", "p1_rating_before", "p1_rating_change",
    "p1_region_id", "p1_area_id", "p1_rounds", "p1_user_id",
    "p2_chara_id", "p2_rank", "p2_power", "p2_rating_before", "p2_rating_change",
    "p2_region_id", "p2_area_id", "p2_rounds", "p2_user_id",
}

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS replays (
    battle_id     TEXT PRIMARY KEY,
    {", ".join(c + (" INTEGER" if c in _INT_COLUMNS else " TEXT")
               for c in COLUMNS if c != "battle_id")}
);
CREATE INDEX IF NOT EXISTS idx_battle_at   ON replays(battle_at);
CREATE INDEX IF NOT EXISTS idx_p1_chara    ON replays(p1_chara_id);
CREATE INDEX IF NOT EXISTS idx_p2_chara    ON replays(p2_chara_id);
CREATE INDEX IF NOT EXISTS idx_p1_rank     ON replays(p1_rank);
CREATE INDEX IF NOT EXISTS idx_p2_rank     ON replays(p2_rank);
CREATE INDEX IF NOT EXISTS idx_version     ON replays(game_version);
"""

_INSERT_SQL = (
    f"INSERT OR IGNORE INTO replays ({', '.join(COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in COLUMNS)})"
)


def connect(path=DEFAULT_DB_PATH):
    """Open (creating parent dir + schema if needed) and return a connection."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
    return conn


def insert_replays(conn, replays):
    """Insert a batch of replay dicts. Returns the number of new rows added."""
    rows = [tuple(r.get(col) for col in COLUMNS) for r in replays]
    before = conn.total_changes
    conn.executemany(_INSERT_SQL, rows)
    conn.commit()
    return conn.total_changes - before


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM replays").fetchone()[0]


def min_battle_at(conn):
    return conn.execute("SELECT MIN(battle_at) FROM replays").fetchone()[0]


def max_battle_at(conn):
    return conn.execute("SELECT MAX(battle_at) FROM replays").fetchone()[0]
