"""wavu-stats -- fetch Tekken 8 ranked replays from wank.wavu.wiki and compute
character / matchup / rank win-rate stats.

Examples:
  python main.py top-up                       # grab newest games since last run
  python main.py backfill --days 14           # build ~2 weeks of history
  python main.py info                          # what's in the DB
  python main.py check-ids                     # flag unmapped character/rank ids
  python main.py analyze --view chars --min-games 200
  python main.py analyze --view matchups --character King --min-games 50
  python main.py report --html --csv           # write dashboard + CSVs to ./out
"""

import argparse
import calendar
import sys
import time

import analyze
import db
import report
from constants import (CHARACTERS, RANKS, REGIONS, resolve_rank_floor,
                       chara_name, rank_name)


def _parse_date(s):
    if s is None:
        return None
    if str(s).isdigit():
        return int(s)
    return calendar.timegm(time.strptime(s, "%Y-%m-%d"))


def _resolve_character(s):
    """Accept a chara_id or a (case-insensitive) character name."""
    if s is None:
        return None
    if str(s).isdigit():
        return int(s)
    for cid, name in CHARACTERS.items():
        if name.lower() == s.lower():
            return cid
    sys.exit(f"Unknown character: {s!r}")


def _patch_label(version, vfloor, vceiling):
    """Human label for the active patch constraint, or None if unconstrained.
    Handles the exact --version, an open/closed --version-floor/-ceiling range,
    and collapses a floor==ceiling range to a single 'patch N'."""
    if version is not None:
        return f"patch {version}"
    if vfloor is not None and vceiling is not None:
        return f"patch {vfloor}" if vfloor == vceiling else f"patches {vfloor}-{vceiling}"
    if vfloor is not None:
        return f"patch {vfloor}+"
    if vceiling is not None:
        return f"patches <= {vceiling}"
    return None


def _build_filters(args):
    floor = resolve_rank_floor(getattr(args, "rank_floor", None))
    if getattr(args, "rank_floor", None) and floor is None:
        sys.exit(f"Unknown rank: {args.rank_floor!r}")
    version = getattr(args, "version", None)
    vfloor = getattr(args, "version_floor", None)
    vceiling = getattr(args, "version_ceiling", None)
    if version is not None and (vfloor is not None or vceiling is not None):
        sys.exit("--version is an exact patch; don't combine it with "
                 "--version-floor / --version-ceiling.")
    if vfloor is not None and vceiling is not None and vfloor > vceiling:
        sys.exit("--version-floor must not exceed --version-ceiling.")
    f = {
        "since": _parse_date(getattr(args, "since", None)),
        "until": _parse_date(getattr(args, "until", None)),
        "version": version,
        "version_floor": vfloor,
        "version_ceiling": vceiling,
        "rank_floor": floor,
        "region": getattr(args, "region", None),
    }
    if getattr(args, "all_types", False):
        f["battle_type"] = None
    bits = []
    if floor is not None:
        bits.append(f"rank >= {RANKS.get(floor, floor)}")
    if f["region"] is not None:
        bits.append(f"region {REGIONS.get(f['region'], f['region'])}")
    patch = _patch_label(version, vfloor, vceiling)
    if patch is not None:
        bits.append(patch)
    f["_label"] = ", ".join(bits)
    return f


def _add_filter_args(p):
    p.add_argument("--since", help="only games on/after this date (YYYY-MM-DD)")
    p.add_argument("--until", help="only games on/before this date (YYYY-MM-DD)")
    p.add_argument("--version", type=int, help="only this game_version (patch id)")
    p.add_argument("--version-floor", type=int,
                   help="only patches at/above this game_version id")
    p.add_argument("--version-ceiling", type=int,
                   help="only patches at/below this game_version id")
    p.add_argument("--rank-floor", help="only count sides at/above this rank "
                   "(id or name, e.g. 'Tekken King')")
    p.add_argument("--region", type=int,
                   help="only this region id (0 Asia,1 ME,2 Oceania,3 America,4 Europe)")
    p.add_argument("--all-types", action="store_true",
                   help="include all battle types, not just ranked. NOTE: wavu "
                   "only archives ranked matches, so with this data source the "
                   "flag currently changes nothing (kept for if that ever changes)")
    p.add_argument("--min-games", type=int, default=0,
                   help="drop rows below this sample size")


def cmd_topup(args):
    import fetch
    conn = db.connect(args.db)
    added = fetch.Fetcher(delay=args.delay).top_up(conn)
    print(f"Done. Added {added} new games. DB now holds {db.count(conn):,}.")


def cmd_backfill(args):
    import fetch
    conn = db.connect(args.db)
    added = fetch.Fetcher(delay=args.delay).backfill(conn, args.days)
    print(f"Done. Added {added} new games. DB now holds {db.count(conn):,}.")


def cmd_info(args):
    conn = db.connect(args.db)
    n = db.count(conn)
    if not n:
        print("DB is empty. Run 'python main.py top-up' first.")
        return
    lo, hi = db.min_battle_at(conn), db.max_battle_at(conn)
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))
    versions = [r[0] for r in conn.execute(
        "SELECT DISTINCT game_version FROM replays ORDER BY game_version")]
    print(f"Games stored : {n:,}")
    print(f"Date range   : {fmt(lo)}  ->  {fmt(hi)}")
    print(f"Game versions: {', '.join(map(str, versions))}")


def cmd_check_ids(args):
    conn = db.connect(args.db)
    problems = 0
    for col, table, label in [
        ("p1_chara_id", CHARACTERS, "character"),
        ("p2_chara_id", CHARACTERS, "character"),
        ("p1_rank", RANKS, "rank"),
        ("p2_rank", RANKS, "rank"),
        ("p1_region_id", REGIONS, "region"),
        ("p2_region_id", REGIONS, "region"),
    ]:
        ids = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col} FROM replays WHERE {col} IS NOT NULL")]
        unknown = sorted(i for i in ids if i not in table)
        if unknown:
            problems += len(unknown)
            print(f"Unmapped {label} ids in {col}: {unknown}")
    if not problems:
        print("All character/rank/region ids present in the DB are mapped. [ok]")
    else:
        print(f"\n{problems} unmapped id(s). Add them to constants.py.")


def cmd_analyze(args):
    conn = db.connect(args.db)
    if not db.count(conn):
        sys.exit("DB is empty. Run 'python main.py top-up' first.")
    f = _build_filters(args)
    if args.view == "chars":
        rows = analyze.character_winrates(conn, f, args.min_games)
        report.print_character_table(rows, args.top)
    elif args.view == "rank":
        rows = analyze.rank_character_winrates(conn, f, args.min_games)
        report.print_rank_char_table(rows, args.top)
    elif args.view == "matchups":
        char = _resolve_character(args.character)
        rows = analyze.matchup_winrates(conn, f, args.min_games, character=char)
        report.print_matchup_table(rows, args.top)
    elif args.view == "distribution":
        rows = analyze.rank_distribution(conn, f)
        report.print_rank_distribution(rows, args.top)
    print(f"\n({len(rows)} rows"
          + (f", filter: {f['_label']}" if f["_label"] else "") + ")")


def cmd_report(args):
    conn = db.connect(args.db)
    if not db.count(conn):
        sys.exit("DB is empty. Run 'python main.py top-up' first.")
    f = _build_filters(args)

    # Interactive dashboard: ship per-rank buckets, filter live in the browser.
    # The matchup heatmap is the exception -- it's baked to a single rank range
    # (--rank-floor [+ --rank-ceiling]) at the latest patch, since shipping a
    # per-rank matchup matrix for the browser to sum is what bloated the blob.
    if args.interactive:
        floor = f.get("rank_floor")           # from --rank-floor (may be None)
        ceiling = resolve_rank_floor(args.rank_ceiling)
        if args.rank_ceiling and ceiling is None:
            sys.exit(f"Unknown rank: {args.rank_ceiling!r}")
        if ceiling is not None and floor is None:
            sys.exit("--rank-ceiling needs --rank-floor (it sets the upper "
                     "bound of the matchup chart's rank range).")

        # The floor/ceiling drive the matchup chart only; the other tabs stay
        # full-range and live-filterable, so strip the floor from the page-level
        # queries.
        f["rank_floor"] = None

        matchup = None
        if floor is not None:
            # The matchup chart's patch selection follows the page: an exact
            # --version, else the --version-floor/-ceiling range, else default
            # to the latest patch only (matchups shouldn't silently blend every
            # historical patch even when the rest of the page shows all of them).
            if args.version is not None:
                patch = {"version": args.version}
                patch_label = _patch_label(args.version, None, None)
            elif f["version_floor"] is not None or f["version_ceiling"] is not None:
                patch = {"version_floor": f["version_floor"],
                         "version_ceiling": f["version_ceiling"]}
                patch_label = _patch_label(None, f["version_floor"],
                                           f["version_ceiling"])
            else:
                versions = analyze.summary(
                    conn, dict(f, version=None, version_floor=None,
                               version_ceiling=None))["versions"]
                latest = versions[-1] if versions else None
                patch = {"version": latest}
                patch_label = (_patch_label(latest, None, None)
                               if latest is not None else "all patches")
            label = (f"{rank_name(floor)}+" if ceiling is None
                     else f"{rank_name(floor)}-{rank_name(ceiling)}")
            matchup = {"floor": floor, "ceiling": ceiling, "patch": patch,
                       "label": label, "patch_label": patch_label}
            print(f"note: matchup chart baked for {label}, {patch_label}")
        else:
            print("note: no --rank-floor given; matchup chart omitted "
                  "(pass --rank-floor [--rank-ceiling] to include it).")

        data = analyze.dashboard_data(conn, f, matchup)
        data["meta"]["generated"] = time.strftime("%Y-%m-%d %H:%M UTC",
                                                   time.gmtime())
        data["meta"]["filters"] = f["_label"]
        report.build_interactive_dashboard(f"{args.out}/index.html", data)
        return

    chars = analyze.character_winrates(conn, f, args.min_games)
    rankc = analyze.rank_character_winrates(conn, f, max(args.min_games, 1))
    mus = analyze.matchup_winrates(conn, f, max(args.min_games, 1))
    dist = analyze.rank_distribution(conn, f)
    meta = analyze.summary(conn, f)
    meta["filters"] = f["_label"]

    if args.csv:
        report.export_csv(chars, f"{args.out}/character_winrates.csv",
                          ["chara_id", "name", "games", "wins", "losses",
                           "winrate", "wilson"])
        report.export_csv(rankc, f"{args.out}/rank_character_winrates.csv",
                          ["rank_id", "rank_name", "chara_id", "name",
                           "games", "wins", "winrate", "wilson"])
        report.export_csv(mus, f"{args.out}/matchups.csv",
                          ["a_id", "a_name", "b_id", "b_name", "games",
                           "wins", "winrate", "wilson", "mirror"])
        report.export_csv(dist, f"{args.out}/rank_distribution.csv",
                          ["rank_id", "rank_name", "players", "players_pct",
                           "appearances", "appearances_pct"])
    # HTML is the default output unless only --csv was asked for.
    if args.html or not args.csv:
        report.build_dashboard(f"{args.out}/dashboard.html", meta,
                               chars, rankc, mus, dist)


def main():
    p = argparse.ArgumentParser(prog="wavu-stats", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=db.DEFAULT_DB_PATH, help="SQLite path")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("top-up", help="fetch newest games since last run")
    pt.add_argument("--delay", type=float, default=1.1, help="seconds between requests")
    pt.set_defaults(func=cmd_topup)

    pb = sub.add_parser("backfill", help="fetch N days of history")
    pb.add_argument("--days", type=float, default=7)
    pb.add_argument("--delay", type=float, default=1.1, help="seconds between requests")
    pb.set_defaults(func=cmd_backfill)

    sub.add_parser("info", help="summarise the DB").set_defaults(func=cmd_info)
    sub.add_parser("check-ids", help="flag unmapped ids").set_defaults(func=cmd_check_ids)

    pa = sub.add_parser("analyze", help="print a stats table")
    pa.add_argument("--view",
                    choices=["chars", "matchups", "rank", "distribution"],
                    default="chars")
    pa.add_argument("--character", help="matchups: limit to this character (id or name)")
    pa.add_argument("--top", type=int, help="show only the first N rows")
    _add_filter_args(pa)
    pa.set_defaults(func=cmd_analyze)

    pr = sub.add_parser("report", help="write CSVs and/or an HTML dashboard")
    pr.add_argument("--out", default="out", help="output directory")
    pr.add_argument("--html", action="store_true", help="write dashboard.html")
    pr.add_argument("--csv", action="store_true", help="write CSV files")
    pr.add_argument("--interactive", action="store_true",
                    help="write a single index.html with a live rank-range "
                    "selector (for GitHub Pages). Ships per-rank buckets and "
                    "filters in the browser. Use --version-floor/-ceiling to "
                    "bake a patch range into the whole page. The matchup chart "
                    "is baked to the --rank-floor [--rank-ceiling] range at the "
                    "page's patch selection (latest patch by default, or "
                    "--version / the --version-floor..-ceiling range); without "
                    "--rank-floor it is omitted")
    pr.add_argument("--rank-ceiling", help="interactive matchup chart: upper "
                    "bound of the rank range (id or name); needs --rank-floor")
    _add_filter_args(pr)
    pr.set_defaults(func=cmd_report)

    # Windows consoles default to cp1252 and crash on non-ASCII output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
