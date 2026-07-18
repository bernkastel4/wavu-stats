"""Win-rate / matchup aggregations over the replay archive.

Each match has two sides (p1, p2). For per-character stats we treat every match
as two observations -- one per side -- by UNION-ing the two sides together, so a
character "plays" every game it appears in and "wins" when its side == winner.

All queries accept a shared `filters` dict:
    battle_type : int   (default 2 = ranked; pass None to include all types)
    version     : int   game_version / patch id (exact match)
    version_floor   : int   game_version >= this patch id
    version_ceiling : int   game_version <= this patch id
    since       : int   battle_at >= this unix ts
    until       : int   battle_at <= this unix ts
    rank_floor  : int   only count a side whose own rank >= this
    region      : int   only count a side whose own region_id == this
"""

import math

from constants import chara_name, rank_name


def _common_where(f):
    clauses, params = [], []
    bt = f.get("battle_type", 2)
    if bt is not None:
        clauses.append("battle_type = ?"); params.append(bt)
    if f.get("version") is not None:
        clauses.append("game_version = ?"); params.append(f["version"])
    if f.get("version_floor") is not None:
        clauses.append("game_version >= ?"); params.append(f["version_floor"])
    if f.get("version_ceiling") is not None:
        clauses.append("game_version <= ?"); params.append(f["version_ceiling"])
    if f.get("since") is not None:
        clauses.append("battle_at >= ?"); params.append(f["since"])
    if f.get("until") is not None:
        clauses.append("battle_at <= ?"); params.append(f["until"])
    return clauses, params


def _side_where(side, f):
    clauses, params = [], []
    if f.get("rank_floor") is not None:
        clauses.append(f"{side}_rank >= ?"); params.append(f["rank_floor"])
    if f.get("region") is not None:
        clauses.append(f"{side}_region_id = ?"); params.append(f["region"])
    return clauses, params


def _union_sides(select_cols, f):
    """Build a `SELECT ... UNION ALL SELECT ...` over both sides.

    `select_cols` maps output name -> a template using {s} for the side prefix
    and {o} for the side's winner value (1 for p1, 2 for p2).
    Returns (sql, params).
    """
    common, cp = _common_where(f)
    parts, params = [], []
    for side, win_val in (("p1", 1), ("p2", 2)):
        sc, sp = _side_where(side, f)
        where = " AND ".join(common + sc) or "1"
        cols = ", ".join(
            tmpl.format(s=side, o=win_val) + f" AS {name}"
            for name, tmpl in select_cols.items()
        )
        parts.append(f"SELECT {cols} FROM replays WHERE {where}")
        params += cp + sp
    return " UNION ALL ".join(parts), params


def _wilson_lower(wins, games, z=1.96):
    """Wilson score lower bound for a binomial proportion -- a sample-size aware
    'pessimistic' win rate so tiny samples don't top the charts."""
    if games == 0:
        return 0.0
    p = wins / games
    denom = 1 + z * z / games
    centre = p + z * z / (2 * games)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games)
    return (centre - margin) / denom


def character_winrates(conn, filters, min_games=0):
    inner, params = _union_sides(
        {"chara": "{s}_chara_id", "win": "(winner = {o})"}, filters
    )
    sql = (f"SELECT chara, COUNT(*) games, SUM(win) wins "
           f"FROM ({inner}) GROUP BY chara")
    rows = []
    for r in conn.execute(sql, params):
        games, wins = r["games"], r["wins"] or 0
        if games < min_games:
            continue
        rows.append({
            "chara_id": r["chara"], "name": chara_name(r["chara"]),
            "games": games, "wins": wins, "losses": games - wins,
            "winrate": wins / games, "wilson": _wilson_lower(wins, games),
        })
    rows.sort(key=lambda x: x["winrate"], reverse=True)
    return rows


def matchup_winrates(conn, filters, min_games=0, character=None):
    """Directed matchups: row (A, B) = A's win rate vs B. A-vs-B and B-vs-A are
    both present. `character` (chara_id) limits rows to that character's As.

    The opponent column is the *other* side, so we build the two sides
    explicitly rather than via `_union_sides`."""
    common, cp = _common_where(filters)
    parts, params = [], []
    for side, opp, win_val in (("p1", "p2", 1), ("p2", "p1", 2)):
        sc, sp = _side_where(side, filters)  # filter on the subject side
        where = " AND ".join(common + sc) or "1"
        parts.append(
            f"SELECT {side}_chara_id AS a, {opp}_chara_id AS b, "
            f"(winner = {win_val}) AS win FROM replays WHERE {where}"
        )
        params += cp + sp
    inner = " UNION ALL ".join(parts)
    sql = f"SELECT a, b, COUNT(*) games, SUM(win) wins FROM ({inner}) GROUP BY a, b"
    rows = []
    for r in conn.execute(sql, params):
        if character is not None and r["a"] != character:
            continue
        games, wins = r["games"], r["wins"] or 0
        if games < min_games:
            continue
        rows.append({
            "a_id": r["a"], "a_name": chara_name(r["a"]),
            "b_id": r["b"], "b_name": chara_name(r["b"]),
            "games": games, "wins": wins,
            "winrate": wins / games, "wilson": _wilson_lower(wins, games),
            "mirror": r["a"] == r["b"],
        })
    rows.sort(key=lambda x: (x["a_name"], -x["winrate"]))
    return rows


def rank_character_winrates(conn, filters, min_games=0):
    """Win rate per (rank, character), where rank is the character's own rank."""
    inner, params = _union_sides(
        {"rank": "{s}_rank", "chara": "{s}_chara_id", "win": "(winner = {o})"},
        filters,
    )
    sql = (f"SELECT rank, chara, COUNT(*) games, SUM(win) wins "
           f"FROM ({inner}) GROUP BY rank, chara")
    rows = []
    for r in conn.execute(sql, params):
        games, wins = r["games"], r["wins"] or 0
        if games < min_games:
            continue
        rows.append({
            "rank_id": r["rank"], "rank_name": rank_name(r["rank"]),
            "chara_id": r["chara"], "name": chara_name(r["chara"]),
            "games": games, "wins": wins,
            "winrate": wins / games, "wilson": _wilson_lower(wins, games),
        })
    rows.sort(key=lambda x: (x["rank_id"], -x["winrate"]))
    return rows


# Fold the legacy God-of-Destruction alias (rank 100) into its modern id (29)
# so it doesn't surface as a second identically-named bucket.
_RANK_FOLD = "CASE WHEN {s}_rank = 100 THEN 29 ELSE {s}_rank END"


def _rank_appearances(conn, filters):
    """Activity-weighted rank counts: one observation per match-side. Equal to
    `rank_character_matrix` summed over characters -- see `_appearances_from_rc`
    for the scan-free version the interactive dashboard uses."""
    inner, params = _union_sides({"rank": _RANK_FOLD}, filters)
    return {r["rank"]: r["games"] for r in conn.execute(
        f"SELECT rank, COUNT(*) games FROM ({inner}) GROUP BY rank", params)}


def _appearances_from_rc(rc):
    """Appearances-per-rank derived from `rank_character_matrix` rows, so the
    dashboard doesn't scan the table a second time for numbers it already has."""
    appear = {}
    for rank, _chara, games, _wins in rc:
        appear[rank] = appear.get(rank, 0) + games
    return appear


def _rank_players(conn, filters):
    """Headcount: each user counted once at their *most recent* observed rank
    (dedupe on user_id). ROW_NUMBER's (battle_at, rank) tiebreak keeps it
    deterministic where a MAX(battle_at) self-join could double-count a user who
    played twice in the same second at two ranks."""
    inner, params = _union_sides(
        {"uid": "{s}_user_id", "rank": _RANK_FOLD, "battle_at": "battle_at"},
        filters,
    )
    return {r["rank"]: r["players"] for r in conn.execute(
        f"SELECT rank, COUNT(*) players FROM ("
        f"  SELECT rank, ROW_NUMBER() OVER "
        f"    (PARTITION BY uid ORDER BY battle_at DESC, rank DESC) rn "
        f"  FROM ({inner}) WHERE uid IS NOT NULL"
        f") WHERE rn = 1 GROUP BY rank", params)}


def _distribution_rows(players, appear):
    """Combine the headcount + activity-weighted rank counts into display rows,
    each with its share of its own total (fractions, 0..1)."""
    p_tot = sum(players.values()) or 1
    a_tot = sum(appear.values()) or 1
    rows = []
    for rank_id in sorted(set(players) | set(appear)):
        pl, ap = players.get(rank_id, 0), appear.get(rank_id, 0)
        rows.append({
            "rank_id": rank_id, "rank_name": rank_name(rank_id),
            "players": pl, "players_pct": pl / p_tot,
            "appearances": ap, "appearances_pct": ap / a_tot,
        })
    return rows


def rank_distribution(conn, filters):
    """Distribution of the ranked playerbase by rank, measured two ways:

      players      -- distinct players, each counted once at their *most recent*
                      observed rank (dedupe on user_id). The honest headcount.
      appearances  -- every match-side, so heavy players weigh more. What rank
                      you actually queue into (activity-weighted).

    Returns one row per rank present, sorted by rank id, with each count's share
    of its own total (fractions, 0..1). Both sides go through the same `filters`
    helpers as the other views, so --region / --version / --since all apply."""
    return _distribution_rows(_rank_players(conn, filters),
                              _rank_appearances(conn, filters))


# --------------------------------------------------------------------------- #
# Per-rank buckets for the interactive dashboard
#
# rank_character_matrix returns raw (rank, chara, games, wins) counts with NO
# rank floor applied, so the browser can sum whichever rank range the viewer
# picks. Win rate and the Wilson bound are both pure functions of (wins, games)
# and therefore additive across rank buckets -- summing rows for ranks lo..hi
# reproduces exactly what a server-side `rank_floor`/range filter would have
# computed. The rank fold (100 -> 29) keeps the legacy God-of-Destruction alias
# out as a duplicate. (The matchup heatmap does NOT get a per-rank matrix here;
# it's baked to one range at generation time by matchup_matrix below.)
# --------------------------------------------------------------------------- #

def rank_character_matrix(conn, filters):
    """Per (rank, chara): games and wins, rank = the character's own rank.

    The browser sums a rank range for character totals and reads rows directly
    for the rank x character table."""
    inner, params = _union_sides(
        {"rank": _RANK_FOLD, "chara": "{s}_chara_id", "win": "(winner = {o})"},
        filters,
    )
    sql = (f"SELECT rank, chara, COUNT(*) games, SUM(win) wins "
           f"FROM ({inner}) GROUP BY rank, chara")
    return [(r["rank"], r["chara"], r["games"], r["wins"] or 0)
            for r in conn.execute(sql, params)]


def matchup_matrix(conn, filters):
    """Per (A, B): games and A-wins, aggregated over ALL ranks that pass the
    subject-side rank floor/ceiling (no rank dimension in the result).

    This is the *baked* matchup matrix the interactive dashboard ships: the
    viewer picks the rank range at generation time (via --rank-floor /
    --rank-ceiling) rather than the browser summing per-rank buckets live, so we
    collapse the rank axis here and emit a flat (a, b, games, wins) list.

    Rank filtering is subject-side only (opponent unconstrained), matching
    matchup_winrates. The floor/ceiling are compared against the *folded* rank
    (100 -> 29) so the legacy God-of-Destruction alias buckets correctly under a
    ceiling; we build the WHERE inline rather than via `_side_where` so this fold
    doesn't leak into the other views."""
    common, cp = _common_where(filters)
    floor, ceiling = filters.get("rank_floor"), filters.get("rank_ceiling")
    parts, params = [], []
    for side, opp, win_val in (("p1", "p2", 1), ("p2", "p1", 2)):
        clauses, p = list(common), list(cp)
        rank_expr = _RANK_FOLD.format(s=side)
        if floor is not None:
            clauses.append(f"{rank_expr} >= ?"); p.append(floor)
        if ceiling is not None:
            clauses.append(f"{rank_expr} <= ?"); p.append(ceiling)
        if filters.get("region") is not None:
            clauses.append(f"{side}_region_id = ?"); p.append(filters["region"])
        where = " AND ".join(clauses) or "1"
        parts.append(
            f"SELECT {side}_chara_id AS a, {opp}_chara_id AS b, "
            f"(winner = {win_val}) AS win FROM replays WHERE {where}"
        )
        params += p
    inner = " UNION ALL ".join(parts)
    sql = f"SELECT a, b, COUNT(*) games, SUM(win) wins FROM ({inner}) GROUP BY a, b"
    return [(r["a"], r["b"], r["games"], r["wins"] or 0)
            for r in conn.execute(sql, params)]


def dashboard_data(conn, filters, matchup=None):
    """Assemble the JSON-ready payload for the interactive dashboard: per-rank
    buckets the browser aggregates live, plus meta and id->name label maps for
    only the ids actually present (keeps the embedded blob small).

    The matchup heatmap is the one view that would need a per-rank matrix; rather
    than ship that (the bulk of the old blob), it is *baked* to a single rank
    range + patch (range). Pass `matchup` = {"floor": int, "ceiling": int|None,
    "patch": dict, "label": str, "patch_label": str} to include it, where
    `patch` is the version filter for the chart (any of version /
    version_floor / version_ceiling); None omits the matchup tab entirely
    (no matchup data shipped)."""
    rc = rank_character_matrix(conn, filters)
    # Appearances-per-rank are just `rc` summed over characters, so derive them
    # instead of scanning the 26 GB table again; only the headcount (which needs
    # per-user dedup) still needs its own query.
    dist = _distribution_rows(_rank_players(conn, filters),
                              _appearances_from_rc(rc))
    meta = summary(conn, filters)

    payload = {
        "meta": meta,
        "rankChar": rc,
        "rankDist": [(d["rank_id"], d["players"], d["appearances"]) for d in dist],
    }
    chars = {c for _, c, *_ in rc}

    if matchup is not None:
        mf = dict(filters, rank_floor=matchup["floor"],
                  rank_ceiling=matchup["ceiling"])
        # The chart carries its own patch selection, which may differ from the
        # page's (e.g. the default is latest-patch-only even when the page shows
        # all patches). Drop any inherited version keys, then apply the chart's.
        for k in ("version", "version_floor", "version_ceiling"):
            mf.pop(k, None)
        mf.update(matchup["patch"])
        mm = matchup_matrix(conn, mf)
        payload["matchup"] = mm
        payload["matchupMeta"] = {"label": matchup["label"],
                                  "patch": matchup["patch_label"]}
        chars |= {a for a, _b, *_ in mm} | {b for _a, b, *_ in mm}

    ranks = sorted({r for r, *_ in rc} | {d["rank_id"] for d in dist})
    payload["charNames"] = {c: chara_name(c) for c in sorted(chars)}
    payload["rankNames"] = {r: rank_name(r) for r in ranks}
    payload["ranks"] = ranks
    return payload


def summary(conn, filters):
    """Overall totals for the current filter -- used for sanity checks/headers."""
    common, cp = _common_where(filters)
    where = " AND ".join(common) or "1"
    row = conn.execute(
        f"SELECT COUNT(*) games, MIN(battle_at) first, MAX(battle_at) last "
        f"FROM replays WHERE {where}", cp
    ).fetchone()
    versions = [r[0] for r in conn.execute(
        f"SELECT DISTINCT game_version FROM replays WHERE {where} "
        f"ORDER BY game_version", cp)]
    return {
        "games": row["games"], "first": row["first"], "last": row["last"],
        "versions": versions,
    }
