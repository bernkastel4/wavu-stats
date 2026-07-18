"""Rendering: CLI tables, CSV export, and a self-contained HTML dashboard."""

import csv
import html
import json
import math
import os
import time

from constants import chara_name, rank_name


# --------------------------------------------------------------------------- #
# CLI tables
# --------------------------------------------------------------------------- #

def _pct(x):
    return f"{x * 100:5.1f}%"


def print_character_table(rows, top=None):
    rows = rows[:top] if top else rows
    print(f"\n{'Character':<14}{'Games':>8}{'Wins':>8}{'Win%':>8}{'Wilson':>9}")
    print("-" * 47)
    for r in rows:
        print(f"{r['name']:<14}{r['games']:>8}{r['wins']:>8}"
              f"{_pct(r['winrate']):>8}{_pct(r['wilson']):>9}")


def print_rank_char_table(rows, top=None):
    rows = rows[:top] if top else rows
    print(f"\n{'Rank':<18}{'Character':<14}{'Games':>8}{'Win%':>8}{'Wilson':>9}")
    print("-" * 57)
    for r in rows:
        print(f"{r['rank_name']:<18}{r['name']:<14}{r['games']:>8}"
              f"{_pct(r['winrate']):>8}{_pct(r['wilson']):>9}")


def print_rank_distribution(rows, top=None):
    rows = rows[:top] if top else rows
    print(f"\n{'Rank':<24}{'Players':>9}{'Players%':>10}"
          f"{'Appearances':>13}{'Appear%':>10}")
    print("-" * 66)
    for r in rows:
        print(f"{r['rank_name']:<24}{r['players']:>9,}"
              f"{_pct(r['players_pct']):>10}{r['appearances']:>13,}"
              f"{_pct(r['appearances_pct']):>10}")


def print_matchup_table(rows, top=None):
    rows = rows[:top] if top else rows
    print(f"\n{'Matchup':<28}{'Games':>8}{'Win%':>8}{'Wilson':>9}")
    print("-" * 53)
    for r in rows:
        label = f"{r['a_name']} vs {r['b_name']}"
        print(f"{label:<28}{r['games']:>8}{_pct(r['winrate']):>8}"
              f"{_pct(r['wilson']):>9}")


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #

def export_csv(rows, path, columns):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c) for c in columns])
    print(f"wrote {path} ({len(rows)} rows)")


# --------------------------------------------------------------------------- #
# HTML dashboard
# --------------------------------------------------------------------------- #

def _sortable_table(headers, rows, numeric_cols):
    """headers: list of str. rows: list of list of (display, sortval)."""
    ths = "".join(
        f'<th data-num="{1 if i in numeric_cols else 0}">{html.escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    trs = []
    for row in rows:
        tds = "".join(
            f'<td data-v="{html.escape(str(sortv))}">{disp}</td>'
            for disp, sortv in row
        )
        trs.append(f"<tr>{tds}</tr>")
    return (f'<table class="sortable"><thead><tr>{ths}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def _wr_cell(winrate):
    """A win% cell with an inline bar."""
    pct = winrate * 100
    return (f'<div class="bar"><span style="width:{pct:.1f}%"></span>'
            f'<b>{pct:.1f}%</b></div>')


def _heat_color(winrate):
    # red (low) -> yellow (50%) -> green (high), around a 30%-70% span.
    t = max(0.0, min(1.0, (winrate - 0.30) / 0.40))
    hue = 0 + t * 120  # 0=red .. 120=green
    return f"hsl({hue:.0f} 65% 45%)"


def _matchup_heatmap(matchups):
    if not matchups:
        return "<p class='muted'>No matchup data for this filter.</p>"
    chars = sorted({m["a_id"] for m in matchups} | {m["b_id"] for m in matchups},
                   key=chara_name)
    lookup = {(m["a_id"], m["b_id"]): m for m in matchups}
    head = "".join(f"<th class='rot'><span>{html.escape(chara_name(c))}</span></th>"
                   for c in chars)
    body = []
    for a in chars:
        cells = [f"<th class='rowh'>{html.escape(chara_name(a))}</th>"]
        for b in chars:
            m = lookup.get((a, b))
            if not m:
                cells.append("<td class='na'></td>")
            elif a == b:
                cells.append("<td class='mirror'>&mdash;</td>")
            else:
                c = _heat_color(m["winrate"])
                title = (f"{chara_name(a)} vs {chara_name(b)}: "
                         f"{m['winrate']*100:.1f}% over {m['games']} games")
                cells.append(f"<td style='background:{c}' title='{html.escape(title)}'>"
                             f"{m['winrate']*100:.0f}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f"<div class='heatwrap'><table class='heat'>"
            f"<thead><tr><th class='corner'>A \\ B</th>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>"
            f"<p class='muted'>Cell = row character's win% vs column character. "
            f"Green favours the row.</p>")


# Ranks below this are the sparse low tiers (Beginner..Eliminator); the chart
# folds them into one leading bucket so the populated high ranks get room. This
# is display-only -- the table and CSV still list every rank in full.
DIST_CHART_FLOOR = 15  # Garyu


def _short_rank(name):
    """Compact x-axis label -- the full name still shows in the table + hover."""
    return name.replace("God of Destruction", "GoD")


def _dist_chart_categories(distribution):
    """Collapse ranks below DIST_CHART_FLOOR into one leading bucket for the
    chart. Returns [(label, players_pct, appearances_pct, hover_detail), ...]."""
    low = [r for r in distribution if r["rank_id"] < DIST_CHART_FLOOR]
    cats = []
    if low:
        cats.append((
            f"< {_short_rank(rank_name(DIST_CHART_FLOOR))}",
            sum(r["players_pct"] for r in low),
            sum(r["appearances_pct"] for r in low),
            f"Ranks below {rank_name(DIST_CHART_FLOOR)}, combined",
        ))
    for r in distribution:
        if r["rank_id"] >= DIST_CHART_FLOOR:
            cats.append((_short_rank(r["rank_name"]), r["players_pct"],
                         r["appearances_pct"], r["rank_name"]))
    return cats


def _rank_distribution_chart(distribution):
    """Inline SVG grouped bar chart: per rank, players% beside appearances%.
    Self-contained (no external requests); native <title> gives per-bar hover."""
    cats = _dist_chart_categories(distribution)
    if not cats:
        return "<p class='muted'>No rank data for this filter.</p>"

    ymax = max(max(p, a) for _, p, a, _ in cats)
    step = 0.02 if ymax <= 0.12 else 0.05
    ymax = math.ceil(ymax / step) * step or step

    ML, MR, MT, MB = 44, 12, 16, 104         # margins (MB fits rotated labels)
    PH, gw, bw, gap = 230, 36, 12, 3         # plot height, group/bar widths
    PW = len(cats) * gw
    W, H = ML + PW + MR, MT + PH + MB
    baseline = MT + PH

    def y(v):
        return MT + PH * (1 - v / ymax)

    p = [f'<svg class="distchart" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-label="Rank distribution by share of players and appearances">']
    # y gridlines + labels
    for i in range(int(round(ymax / step)) + 1):
        v = i * step
        yy = y(v)
        p.append(f'<line class="grid" x1="{ML}" y1="{yy:.1f}" x2="{ML+PW}" y2="{yy:.1f}"/>')
        p.append(f'<text class="ylab" x="{ML-6}" y="{yy+3:.1f}">{v*100:.0f}%</text>')
    # grouped bars + rotated x labels
    for i, (label, pl, ap, detail) in enumerate(cats):
        gx = ML + i * gw
        x1 = gx + (gw - (2 * bw + gap)) / 2
        for x, val, cls, series in ((x1, pl, "sp", "Players"),
                                    (x1 + bw + gap, ap, "sa", "Appearances")):
            bh = PH * (val / ymax)
            p.append(
                f'<rect class="{cls}" x="{x:.1f}" y="{baseline-bh:.1f}" '
                f'width="{bw}" height="{bh:.1f}" rx="2"><title>'
                f'{html.escape(detail)} — {series} {val*100:.2f}%</title></rect>')
        lx = gx + gw / 2
        p.append(f'<text class="xlab" x="{lx:.1f}" y="{baseline+8:.1f}" '
                 f'transform="rotate(-55 {lx:.1f} {baseline+8:.1f})">'
                 f'{html.escape(label)}</text>')
    p.append(f'<line class="axis" x1="{ML}" y1="{baseline}" x2="{ML+PW}" y2="{baseline}"/>')
    p.append('</svg>')

    legend = ('<div class="distlegend">'
              '<span><i class="sw sp"></i>Players (headcount, latest rank)</span>'
              '<span><i class="sw sa"></i>Appearances (activity-weighted)</span>'
              '</div>')
    return (f'<div class="chartwrap">{"".join(p)}</div>{legend}'
            f'<p class="muted">Each rank’s share of distinct players vs its '
            f'share of match appearances. Ranks below '
            f'{html.escape(rank_name(DIST_CHART_FLOOR))} are combined for display. '
            f'Counts only players active in the archive window — not everyone '
            f'who owns the game.</p>')


def build_dashboard(out_path, meta, characters, rank_chars, matchups, distribution):
    gen = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    def span(ts):
        return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "?"

    meta_bits = [
        f"{meta['games']:,} games",
        f"{span(meta['first'])} → {span(meta['last'])}",
        "patch " + (", ".join(str(v) for v in meta["versions"]) or "all"),
    ]
    if meta.get("filters"):
        meta_bits.append(meta["filters"])

    # Character table
    char_rows = [[
        (html.escape(r["name"]), r["name"]),
        (f"{r['games']:,}", r["games"]),
        (_wr_cell(r["winrate"]), r["winrate"]),
        (f"{r['wilson']*100:.1f}%", r["wilson"]),
    ] for r in characters]
    char_table = _sortable_table(
        ["Character", "Games", "Win rate", "Wilson lo"], char_rows, {1, 2, 3})

    # Rank x character table
    rc_rows = [[
        (html.escape(r["rank_name"]), r["rank_id"]),
        (html.escape(r["name"]), r["name"]),
        (f"{r['games']:,}", r["games"]),
        (_wr_cell(r["winrate"]), r["winrate"]),
    ] for r in rank_chars]
    # Rank (col 0) is numeric so it sorts by rank id, not rank-name alphabetical.
    rc_table = _sortable_table(
        ["Rank", "Character", "Games", "Win rate"], rc_rows, {0, 2, 3})

    heat = _matchup_heatmap(matchups)

    # Rank distribution: chart + exact-numbers table
    dist_chart = _rank_distribution_chart(distribution)
    dist_rows = [[
        (html.escape(r["rank_name"]), r["rank_id"]),
        (f"{r['players']:,}", r["players"]),
        (f"{r['players_pct']*100:.2f}%", r["players_pct"]),
        (f"{r['appearances']:,}", r["appearances"]),
        (f"{r['appearances_pct']*100:.2f}%", r["appearances_pct"]),
    ] for r in distribution]
    # Rank (col 0) is numeric so it sorts by rank id, not rank-name alphabetical.
    dist_table = _sortable_table(
        ["Rank", "Players", "Players %", "Appearances", "Appear %"],
        dist_rows, {0, 1, 2, 3, 4})

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tekken 8 Stats — wavu-stats</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#1a1a1a; --muted:#666;
          --line:#e2e2e2; --accent:#3b6ea5; --barbg:#eee;
          --series-players:#2a78d6; --series-appear:#008300; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#15171a; --fg:#e8e8e8; --muted:#9aa0a6; --line:#2c2f34;
             --accent:#5b9bd5; --barbg:#26292e;
             --series-players:#3987e5; --series-appear:#008300; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
          background:var(--bg); color:var(--fg); }}
  header {{ padding:20px 24px; border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 4px; font-size:20px; }}
  .meta {{ color:var(--muted); font-size:13px; }}
  .meta span {{ margin-right:14px; }}
  main {{ padding:16px 24px 60px; max-width:1100px; }}
  section {{ margin-top:28px; }}
  h2 {{ font-size:16px; border-bottom:2px solid var(--accent);
        padding-bottom:4px; display:inline-block; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  .sortable th {{ cursor:pointer; text-align:right; padding:6px 10px;
        border-bottom:1px solid var(--line); white-space:nowrap;
        position:sticky; top:0; background:var(--bg); user-select:none; }}
  .sortable th:first-child, .sortable td:first-child {{ text-align:left; }}
  .sortable th:hover {{ color:var(--accent); }}
  .sortable td {{ padding:4px 10px; border-bottom:1px solid var(--line);
        text-align:right; }}
  .scroll {{ overflow:auto; max-height:520px; border:1px solid var(--line);
        border-radius:6px; }}
  .bar {{ position:relative; background:var(--barbg); border-radius:3px;
        min-width:90px; height:18px; }}
  .bar span {{ position:absolute; left:0; top:0; bottom:0; background:var(--accent);
        border-radius:3px; opacity:.55; }}
  .bar b {{ position:relative; font-weight:600; padding:0 6px; line-height:18px;
        font-size:12px; }}
  .muted {{ color:var(--muted); font-size:12px; }}
  .heatwrap {{ overflow:auto; border:1px solid var(--line); border-radius:6px; }}
  table.heat {{ font-size:11px; }}
  table.heat td {{ width:26px; height:24px; text-align:center; color:#fff;
        border:1px solid rgba(0,0,0,.15); }}
  table.heat td.mirror {{ background:var(--barbg); color:var(--muted); }}
  table.heat td.na {{ background:transparent; }}
  table.heat th.rowh {{ text-align:right; padding:0 6px; white-space:nowrap;
        position:sticky; left:0; background:var(--bg); }}
  table.heat th.corner {{ position:sticky; left:0; background:var(--bg); }}
  table.heat th.rot {{ height:80px; white-space:nowrap; }}
  table.heat th.rot span {{ display:inline-block; transform:rotate(-60deg);
        transform-origin:left; width:20px; }}
  .chartwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:6px;
        padding:8px 4px; }}
  svg.distchart {{ display:block; }}
  svg.distchart .grid {{ stroke:var(--line); stroke-width:1; }}
  svg.distchart .axis {{ stroke:var(--muted); stroke-width:1; }}
  svg.distchart text.ylab {{ fill:var(--muted); font-size:10px; text-anchor:end; }}
  svg.distchart text.xlab {{ fill:var(--muted); font-size:10px; text-anchor:end; }}
  svg.distchart rect.sp {{ fill:var(--series-players); }}
  svg.distchart rect.sa {{ fill:var(--series-appear); }}
  .distlegend {{ display:flex; gap:20px; margin:8px 2px 2px; font-size:12px;
        color:var(--muted); }}
  .distlegend .sw {{ display:inline-block; width:11px; height:11px;
        border-radius:2px; margin-right:6px; vertical-align:-1px; }}
  .distlegend .sw.sp {{ background:var(--series-players); }}
  .distlegend .sw.sa {{ background:var(--series-appear); }}
</style>
</head>
<body>
<header>
  <h1>Tekken 8 ranked statistics</h1>
  <div class="meta">{''.join(f'<span>{html.escape(b)}</span>' for b in meta_bits)}</div>
  <div class="meta">Generated {gen} · source: wank.wavu.wiki · win%
     shown with sample-size-aware Wilson lower bound</div>
</header>
<main>
  <section>
    <h2>Rank distribution</h2>
    {dist_chart}
    <div class="scroll">{dist_table}</div>
  </section>
  <section>
    <h2>Character win rates</h2>
    <div class="scroll">{char_table}</div>
  </section>
  <section>
    <h2>Matchup chart</h2>
    {heat}
  </section>
  <section>
    <h2>Win rate by rank &amp; character</h2>
    <div class="scroll">{rc_table}</div>
  </section>
</main>
<script>
document.querySelectorAll('table.sortable').forEach(function(tbl) {{
  var dir = {{}};
  tbl.querySelectorAll('th').forEach(function(th, idx) {{
    th.addEventListener('click', function() {{
      var num = th.dataset.num === '1';
      var body = tbl.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      dir[idx] = !dir[idx];
      var sign = dir[idx] ? 1 : -1;
      rows.sort(function(a, b) {{
        var x = a.cells[idx].dataset.v, y = b.cells[idx].dataset.v;
        if (num) return sign * (parseFloat(x) - parseFloat(y));
        return sign * x.localeCompare(y);
      }});
      rows.forEach(function(r) {{ body.appendChild(r); }});
    }});
  }});
}});
</script>
</body>
</html>"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {out_path}")


# --------------------------------------------------------------------------- #
# Interactive HTML dashboard (single self-contained page)
#
# Unlike build_dashboard above -- which bakes ONE rank filter into static tables
# -- this ships per-rank buckets (from analyze.dashboard_data) as an inline JSON
# blob and does the aggregation in the browser, so a viewer can pick any rank
# range live. The render helpers above are re-implemented in the embedded JS
# below; keep the two in sync if the Python renderers change (they're small).
# The page stays fully self-contained (inline CSS/JS/data) per CLAUDE.md, so it
# also opens offline and works as a plain "upload this file" artifact.
# --------------------------------------------------------------------------- #

_INTERACTIVE_CSS = """
  :root { color-scheme: light dark; --bg:#fff; --fg:#1a1a1a; --muted:#666;
          --line:#e2e2e2; --accent:#3b6ea5; --barbg:#eee; --chip:#f2f2f2;
          --series-players:#2a78d6; --series-appear:#008300; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#15171a; --fg:#e8e8e8; --muted:#9aa0a6; --line:#2c2f34;
             --accent:#5b9bd5; --barbg:#26292e; --chip:#22262b;
             --series-players:#3987e5; --series-appear:#008300; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
          background:var(--bg); color:var(--fg); }
  header { padding:20px 24px 0; }
  h1 { margin:0 0 4px; font-size:20px; }
  .meta { color:var(--muted); font-size:13px; }
  .meta span { margin-right:14px; }
  main { padding:0 24px 60px; max-width:1100px; }
  h2 { font-size:16px; border-bottom:2px solid var(--accent);
        padding-bottom:4px; display:inline-block; margin-top:4px; }
  /* Controls */
  .controls { position:sticky; top:0; z-index:5; background:var(--bg);
        border-bottom:1px solid var(--line); padding:12px 24px;
        display:flex; flex-wrap:wrap; gap:14px 18px; align-items:center; }
  /* Greyed out while the baked matchup tab (which the selector can't drive)
     is active. */
  .controls.disabled { opacity:.4; pointer-events:none; }
  .controls label { font-size:13px; color:var(--muted); }
  .controls select, .controls input { font:inherit; font-size:13px; padding:3px 6px;
        background:var(--bg); color:var(--fg); border:1px solid var(--line);
        border-radius:5px; }
  .controls input[type=number] { width:90px; }
  .presets { display:flex; gap:6px; flex-wrap:wrap; }
  .presets button, .tabs button { font:inherit; font-size:12px; cursor:pointer;
        border:1px solid var(--line); background:var(--chip); color:var(--fg);
        border-radius:14px; padding:3px 10px; }
  .presets button:hover, .tabs button:hover { border-color:var(--accent);
        color:var(--accent); }
  .rangelabel { font-size:13px; color:var(--fg); font-weight:600; }
  /* Tabs */
  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin:18px 0 8px; }
  .tabs button { border-radius:6px; padding:5px 12px; font-size:13px; }
  .tabs button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  section.tab { display:none; margin-top:8px; }
  section.tab.active { display:block; }
  /* Tables */
  table { border-collapse:collapse; width:100%; font-size:13px; }
  .sortable th { cursor:pointer; text-align:right; padding:6px 10px;
        border-bottom:1px solid var(--line); white-space:nowrap;
        position:sticky; top:0; background:var(--bg); user-select:none; }
  .sortable th:first-child, .sortable td:first-child { text-align:left; }
  .sortable th:hover { color:var(--accent); }
  .sortable td { padding:4px 10px; border-bottom:1px solid var(--line);
        text-align:right; }
  .scroll { overflow:auto; max-height:560px; border:1px solid var(--line);
        border-radius:6px; }
  .bar { position:relative; background:var(--barbg); border-radius:3px;
        min-width:90px; height:18px; }
  .bar span { position:absolute; left:0; top:0; bottom:0; background:var(--accent);
        border-radius:3px; opacity:.55; }
  .bar b { position:relative; font-weight:600; padding:0 6px; line-height:18px;
        font-size:12px; }
  .muted { color:var(--muted); font-size:12px; }
  .heatwrap { overflow:auto; border:1px solid var(--line); border-radius:6px; }
  table.heat { font-size:11px; }
  table.heat td { width:26px; height:24px; text-align:center; color:#fff;
        border:1px solid rgba(0,0,0,.15); }
  table.heat td.mirror { background:var(--barbg); color:var(--muted); }
  table.heat td.na { background:transparent; }
  table.heat th.rowh { text-align:right; padding:0 6px; white-space:nowrap;
        position:sticky; left:0; background:var(--bg); }
  table.heat th.corner { position:sticky; left:0; background:var(--bg); }
  table.heat th.rot { height:80px; white-space:nowrap; }
  table.heat th.rot span { display:inline-block; transform:rotate(-60deg);
        transform-origin:left; width:20px; }
  .chartwrap { overflow-x:auto; border:1px solid var(--line); border-radius:6px;
        padding:8px 4px; }
  svg.distchart { display:block; }
  svg.distchart .grid { stroke:var(--line); stroke-width:1; }
  svg.distchart .axis { stroke:var(--muted); stroke-width:1; }
  svg.distchart text.ylab { fill:var(--muted); font-size:10px; text-anchor:end; }
  svg.distchart text.xlab { fill:var(--muted); font-size:10px; text-anchor:end; }
  svg.distchart rect.sp { fill:var(--series-players); }
  svg.distchart rect.sa { fill:var(--series-appear); }
  .distlegend { display:flex; gap:20px; margin:8px 2px 2px; font-size:12px;
        color:var(--muted); }
  .distlegend .sw { display:inline-block; width:11px; height:11px;
        border-radius:2px; margin-right:6px; vertical-align:-1px; }
  .distlegend .sw.sp { background:var(--series-players); }
  .distlegend .sw.sa { background:var(--series-appear); }
"""

# The whole client. Written as one plain string (NOT an f-string) so JS braces
# need no escaping; the data blob is spliced in at the __DATA_JSON__ marker.
_INTERACTIVE_JS = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
const CN = DATA.charNames, RN = DATA.rankNames, RANKS = DATA.ranks;

// ---- helpers (ports of the Python renderers) ----
function wilson(wins, games) {
  if (games === 0) return 0;
  const z = 1.96, p = wins / games;
  const denom = 1 + z*z/games;
  const centre = p + z*z/(2*games);
  const margin = z * Math.sqrt((p*(1-p) + z*z/(4*games)) / games);
  return (centre - margin) / denom;
}
function esc(s) { const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML; }
function charName(id) { return CN[id] || ('Char ' + id); }
function rankName(id) { return RN[id] || ('Rank ' + id); }
function shortRank(name) { return name.replace('God of Destruction', 'GoD'); }
function commas(n) { return n.toLocaleString('en-US'); }

function currentRange() {
  let lo = +document.getElementById('rlo').value;
  let hi = +document.getElementById('rhi').value;
  if (lo > hi) { const t = lo; lo = hi; hi = t; }
  return [lo, hi];
}

function wrCell(wr) {
  const p = wr * 100;
  return '<div class="bar"><span style="width:' + p.toFixed(1) + '%"></span><b>'
       + p.toFixed(1) + '%</b></div>';
}
function heatColor(wr) {
  const t = Math.max(0, Math.min(1, (wr - 0.30) / 0.40));
  return 'hsl(' + (t * 120).toFixed(0) + ' 65% 45%)';
}
function sortableTable(headers, rows, numeric) {
  const ths = headers.map((h, i) =>
    '<th data-num="' + (numeric.has(i) ? 1 : 0) + '">' + esc(h) + '</th>').join('');
  const trs = rows.map(r => '<tr>' + r.map(c =>
    '<td data-v="' + esc(c[1]) + '">' + c[0] + '</td>').join('') + '</tr>').join('');
  return '<table class="sortable"><thead><tr>' + ths + '</tr></thead><tbody>'
       + trs + '</tbody></table>';
}

// ---- aggregation + rendering per view ----
function renderChar(lo, hi, mg) {
  const acc = {};
  for (const [rank, ch, g, w] of DATA.rankChar) {
    if (rank < lo || rank > hi) continue;
    (acc[ch] = acc[ch] || [0, 0])[0] += g, acc[ch][1] += w;
  }
  let rows = Object.keys(acc).map(ch => {
    const g = acc[ch][0], w = acc[ch][1];
    return { name: charName(ch), games: g, winrate: w/g, wilson: wilson(w, g) };
  }).filter(r => r.games >= mg);
  rows.sort((a, b) => b.winrate - a.winrate);
  const trows = rows.map(r => [
    [esc(r.name), r.name],
    [commas(r.games), r.games],
    [wrCell(r.winrate), r.winrate],
    [(r.wilson*100).toFixed(1) + '%', r.wilson],
  ]);
  return rows.length
    ? sortableTable(['Character', 'Games', 'Win rate', 'Wilson lo'], trows, new Set([1,2,3]))
    : '<p class="muted">No characters meet this filter.</p>';
}
function renderRankChar(lo, hi, mg) {
  mg = Math.max(mg, 1);
  let rows = [];
  for (const [rank, ch, g, w] of DATA.rankChar) {
    if (rank < lo || rank > hi || g < mg) continue;
    rows.push({ rank: rank, ch: ch, games: g, winrate: w/g });
  }
  rows.sort((a, b) => (a.rank - b.rank) || (b.winrate - a.winrate));
  const trows = rows.map(r => [
    [esc(rankName(r.rank)), r.rank],
    [esc(charName(r.ch)), charName(r.ch)],
    [commas(r.games), r.games],
    [wrCell(r.winrate), r.winrate],
  ]);
  return rows.length
    ? sortableTable(['Rank', 'Character', 'Games', 'Win rate'], trows, new Set([0,2,3]))
    : '<p class="muted">No rows meet this filter.</p>';
}
function renderMatchup() {
  // Baked matrix: a flat [a, b, games, wins] list for one rank range + patch,
  // fixed at generation time. The rank selector above does NOT drive it (which
  // is why the controls grey out on this tab).
  const ms = DATA.matchup.map(r =>
    ({ a: r[0], b: r[1], games: r[2], winrate: r[2] ? r[3]/r[2] : 0 }));
  if (!ms.length) return '<p class="muted">No matchup data for this filter.</p>';
  const set = new Set();
  ms.forEach(m => { set.add(m.a); set.add(m.b); });
  const chars = [...set].sort((x, y) => charName(x).localeCompare(charName(y)));
  const lk = {};
  ms.forEach(m => { lk[m.a + ',' + m.b] = m; });
  const head = chars.map(c =>
    '<th class="rot"><span>' + esc(charName(c)) + '</span></th>').join('');
  const body = chars.map(a => {
    let cells = '<th class="rowh">' + esc(charName(a)) + '</th>';
    cells += chars.map(b => {
      const m = lk[a + ',' + b];
      if (!m) return '<td class="na"></td>';
      if (a === b) return '<td class="mirror">&mdash;</td>';
      const title = charName(a) + ' vs ' + charName(b) + ': '
                  + (m.winrate*100).toFixed(1) + '% over ' + m.games + ' games';
      return '<td style="background:' + heatColor(m.winrate) + '" title="'
           + esc(title) + '">' + (m.winrate*100).toFixed(0) + '</td>';
    }).join('');
    return '<tr>' + cells + '</tr>';
  }).join('');
  return '<div class="heatwrap"><table class="heat"><thead><tr>'
       + '<th class="corner">A \\ B</th>' + head + '</tr></thead><tbody>'
       + body + '</tbody></table></div>'
       + '<p class="muted">Cell = row character\'s win% vs column character. '
       + 'Green favours the row. Baked for <b>' + esc(DATA.matchupMeta.label)
       + '</b> at ' + esc(DATA.matchupMeta.patch) + '; the rank range '
       + 'filters the <b>row (subject) character</b> only (opponent can be any '
       + 'rank). The rank selector above does not affect this chart.</p>';
}
function distCats(rows) {
  // One bar per rank in range -- no low-rank folding.
  return rows.map(r =>
    [shortRank(rankName(r.rank)), r.players_pct, r.appearances_pct, rankName(r.rank)]);
}
function distChart(rows) {
  const cats = distCats(rows);
  if (!cats.length) return '<p class="muted">No rank data for this filter.</p>';
  let ymax = Math.max.apply(null, cats.map(c => Math.max(c[1], c[2])));
  const step = ymax <= 0.12 ? 0.02 : 0.05;
  ymax = Math.ceil(ymax / step) * step || step;
  const ML=44, MR=12, MT=16, MB=104, PH=230, gw=36, bw=12, gap=3;
  const PW = cats.length*gw, W = ML+PW+MR, H = MT+PH+MB, baseline = MT+PH;
  const y = v => MT + PH*(1 - v/ymax);
  const p = ['<svg class="distchart" viewBox="0 0 ' + W + ' ' + H + '" width="' + W
    + '" height="' + H + '" role="img" aria-label="Rank distribution">'];
  const steps = Math.round(ymax/step);
  for (let i = 0; i <= steps; i++) {
    const v = i*step, yy = y(v);
    p.push('<line class="grid" x1="' + ML + '" y1="' + yy.toFixed(1) + '" x2="'
      + (ML+PW) + '" y2="' + yy.toFixed(1) + '"/>');
    p.push('<text class="ylab" x="' + (ML-6) + '" y="' + (yy+3).toFixed(1) + '">'
      + (v*100).toFixed(0) + '%</text>');
  }
  cats.forEach((c, i) => {
    const label = c[0], gx = ML + i*gw, x1 = gx + (gw - (2*bw+gap))/2;
    [[x1, c[1], 'sp', 'Players'], [x1+bw+gap, c[2], 'sa', 'Appearances']]
      .forEach(b => {
        const x = b[0], val = b[1], bh = PH*(val/ymax);
        p.push('<rect class="' + b[2] + '" x="' + x.toFixed(1) + '" y="'
          + (baseline-bh).toFixed(1) + '" width="' + bw + '" height="' + bh.toFixed(1)
          + '" rx="2"><title>' + esc(c[3] + ' — ' + b[3] + ' '
          + (val*100).toFixed(2) + '%') + '</title></rect>');
      });
    const lx = gx + gw/2;
    p.push('<text class="xlab" x="' + lx.toFixed(1) + '" y="' + (baseline+8).toFixed(1)
      + '" transform="rotate(-55 ' + lx.toFixed(1) + ' ' + (baseline+8).toFixed(1)
      + ')">' + esc(label) + '</text>');
  });
  p.push('<line class="axis" x1="' + ML + '" y1="' + baseline + '" x2="' + (ML+PW)
    + '" y2="' + baseline + '"/></svg>');
  const legend = '<div class="distlegend">'
    + '<span><i class="sw sp"></i>Players (headcount, latest rank)</span>'
    + '<span><i class="sw sa"></i>Appearances (activity-weighted)</span></div>';
  return '<div class="chartwrap">' + p.join('') + '</div>' + legend;
}
function renderDist(lo, hi) {
  let rows = DATA.rankDist.filter(d => d[0] >= lo && d[0] <= hi)
    .map(d => ({ rank: d[0], players: d[1], appearances: d[2] }));
  const ptot = rows.reduce((s, r) => s + r.players, 0) || 1;
  const atot = rows.reduce((s, r) => s + r.appearances, 0) || 1;
  rows.forEach(r => { r.players_pct = r.players/ptot; r.appearances_pct = r.appearances/atot; });
  rows.sort((a, b) => a.rank - b.rank);
  const chart = distChart(rows);
  const trows = rows.map(r => [
    [esc(rankName(r.rank)), r.rank],
    [commas(r.players), r.players],
    [(r.players_pct*100).toFixed(2) + '%', r.players_pct],
    [commas(r.appearances), r.appearances],
    [(r.appearances_pct*100).toFixed(2) + '%', r.appearances_pct],
  ]);
  const table = rows.length
    ? sortableTable(['Rank', 'Players', 'Players %', 'Appearances', 'Appear %'],
        trows, new Set([0,1,2,3,4]))
    : '<p class="muted">No rank data for this filter.</p>';
  const note = '<p class="muted">Each rank\'s share of distinct players vs its '
    + 'share of match appearances. Percentages are renormalised over the selected '
    + 'range. Counts only players active in the archive window.</p>';
  return { chart: chart, table: table, note: note };
}

// ---- click-to-sort (re-attached after each re-render) ----
function attachSort() {
  document.querySelectorAll('table.sortable').forEach(function (tbl) {
    const dir = {};
    tbl.querySelectorAll('th').forEach(function (th, idx) {
      th.addEventListener('click', function () {
        const num = th.dataset.num === '1';
        const body = tbl.tBodies[0];
        const rows = Array.prototype.slice.call(body.rows);
        dir[idx] = !dir[idx];
        const sign = dir[idx] ? 1 : -1;
        rows.sort(function (a, b) {
          const x = a.cells[idx].dataset.v, y = b.cells[idx].dataset.v;
          if (num) return sign * (parseFloat(x) - parseFloat(y));
          return sign * x.localeCompare(y);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
}

function fmtDate(ts) {
  return ts ? new Date(ts*1000).toISOString().slice(0, 10) : '?';
}
function renderAll() {
  const [lo, hi] = currentRange();
  const dist = renderDist(lo, hi);
  document.getElementById('distchart').innerHTML = dist.chart;
  document.getElementById('disttable').innerHTML = dist.table;
  document.getElementById('distnote').innerHTML = dist.note;
  document.getElementById('char').innerHTML = renderChar(lo, hi, 0);
  document.getElementById('rankchar').innerHTML = renderRankChar(lo, hi, 0);
  attachSort();
  document.getElementById('rangelabel').textContent =
    'Ranks ' + rankName(lo) + ' → ' + rankName(hi);
}

// ---- wire up controls ----
function snap(val, dir) {
  // nearest available rank id: dir=+1 -> smallest >= val, dir=-1 -> largest <= val
  const inRange = RANKS.filter(r => dir > 0 ? r >= val : r <= val);
  if (inRange.length) return dir > 0 ? inRange[0] : inRange[inRange.length - 1];
  return dir > 0 ? RANKS[RANKS.length - 1] : RANKS[0];
}
function initControls() {
  const rlo = document.getElementById('rlo'), rhi = document.getElementById('rhi');
  const opts = RANKS.map(r => '<option value="' + r + '">' + esc(rankName(r)) + '</option>').join('');
  rlo.innerHTML = opts; rhi.innerHTML = opts;
  rlo.value = RANKS[0]; rhi.value = RANKS[RANKS.length - 1];
  [rlo, rhi].forEach(el => el.addEventListener('change', renderAll));
  document.querySelectorAll('.presets button').forEach(btn =>
    btn.addEventListener('click', function () {
      const lo = this.dataset.lo === 'MIN' ? RANKS[0] : snap(+this.dataset.lo, 1);
      const hi = this.dataset.hi === 'MAX' ? RANKS[RANKS.length - 1] : snap(+this.dataset.hi, -1);
      rlo.value = lo; rhi.value = hi; renderAll();
    }));
  document.querySelectorAll('.tabs button').forEach(btn =>
    btn.addEventListener('click', function () {
      document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('section.tab').forEach(s => s.classList.remove('active'));
      this.classList.add('active');
      document.getElementById(this.dataset.tab).classList.add('active');
      // The baked matchup chart ignores the rank selector -- grey it out so the
      // controls don't look like they drive this tab.
      document.querySelector('.controls').classList
        .toggle('disabled', this.dataset.tab === 'tab-matchup');
    }));
}
(function () {
  const m = DATA.meta;
  const bits = [commas(m.games) + ' games',
                fmtDate(m.first) + ' → ' + fmtDate(m.last),
                'patch ' + (m.versions.join(', ') || 'all')];
  if (m.filters) bits.push(m.filters);
  document.getElementById('metabits').innerHTML =
    bits.map(b => '<span>' + esc(b) + '</span>').join('');
  document.getElementById('gen').textContent =
    'Generated ' + m.generated + ' · source: wank.wavu.wiki · '
    + 'win% shown with a sample-size-aware Wilson lower bound';
  // The matchup chart is baked (or omitted) at generation time. When present,
  // label its tab + heading with the range/patch and render it once; when
  // absent, drop the tab and section entirely.
  if (DATA.matchup) {
    const title = 'Matchup chart (' + DATA.matchupMeta.label + ', '
                + DATA.matchupMeta.patch + ')';
    document.getElementById('tab-matchup-btn').textContent = title;
    document.querySelector('#tab-matchup h2').textContent = title;
    document.getElementById('matchup').innerHTML = renderMatchup();
  } else {
    const btn = document.getElementById('tab-matchup-btn');
    if (btn) btn.remove();
    const sec = document.getElementById('tab-matchup');
    if (sec) sec.remove();
  }
  initControls();
  renderAll();
})();
"""

_INTERACTIVE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tekken 8 Stats &mdash; wavu-stats</title>
<style>__CSS__</style>
</head>
<body>
<header>
  <h1>Tekken 8 ranked statistics</h1>
  <div class="meta"><span id="metabits"></span></div>
  <div class="meta" id="gen"></div>
</header>
<div class="controls">
  <label>Rank from <select id="rlo"></select></label>
  <label>to <select id="rhi"></select></label>
  <span class="presets">
    <button data-lo="MIN" data-hi="MAX">All ranks</button>
    <button data-lo="25" data-hi="MAX">Tekken King+</button>
    <button data-lo="29" data-hi="MAX">God of Destruction+</button>
  </span>
  <span class="rangelabel" id="rangelabel"></span>
</div>
<main>
  <nav class="tabs">
    <button data-tab="tab-dist" class="active">Rank distribution</button>
    <button data-tab="tab-char">Character win rates</button>
    <button data-tab="tab-matchup" id="tab-matchup-btn">Matchup chart</button>
    <button data-tab="tab-rankchar">Rank &amp; character</button>
  </nav>
  <section class="tab active" id="tab-dist">
    <h2>Rank distribution</h2>
    <div id="distchart"></div>
    <div class="scroll" id="disttable"></div>
    <div id="distnote"></div>
  </section>
  <section class="tab" id="tab-char">
    <h2>Character win rates</h2>
    <div class="scroll" id="char"></div>
  </section>
  <section class="tab" id="tab-matchup">
    <h2>Matchup chart</h2>
    <div id="matchup"></div>
  </section>
  <section class="tab" id="tab-rankchar">
    <h2>Win rate by rank &amp; character</h2>
    <div class="scroll" id="rankchar"></div>
  </section>
</main>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>__JS__</script>
</body>
</html>"""


def build_interactive_dashboard(out_path, data):
    """Write the single-file interactive dashboard. `data` is the dict from
    analyze.dashboard_data (with `generated` + `filters` added to its meta)."""
    blob = json.dumps(data, separators=(",", ":"))
    # Neutralise any "</script>" (and the "<!--" opener) that could close the
    # host <script> element early; the JSON parser reads these escapes fine.
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
    doc = (_INTERACTIVE_HTML
           .replace("__CSS__", _INTERACTIVE_CSS)
           .replace("__DATA_JSON__", blob)
           .replace("__JS__", _INTERACTIVE_JS))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {out_path} ({len(doc)/1e6:.1f} MB)")
