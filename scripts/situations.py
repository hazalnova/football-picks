"""The situation tester: checks whether a betting situation held up in past seasons before anyone trusts it.

A "situation" is a set of conditions plus a bet, for example "games where the model and Vegas favor different teams,
taking the model's side." This script checks every situation on two stretches of past seasons and this season so far:

- 2010–2019. For anything that uses the model's numbers, the model was fit on these years, so a good result here can
  be flattering. It's shown, but it isn't enough on its own.
- 2020–2025, which the model never trained on. This is the real test.

This season's record for the main situations is on the website's report card, from the logged picks.

It runs a few built-in situations, plus every AI lesson that comes with a test (the AI writes them in a fixed format;
see CHECK_SCHEMA in ai_notes.py). Results go to data/app_data/situations.json for the website, and next to each lesson
in data/ai/lessons.json, so the AI reads them on its next run.

The workflow runs it from the repository's top folder, after the notebooks and the AI step:

    python scripts/situations.py

It needs data/history/nfl_games.parquet and cfb_games.parquet, which the notebooks write each run.
"""
import json
import hashlib
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

DATA = Path(__file__).resolve().parent.parent / "data"
HISTORY = {"NFL": DATA / "history" / "nfl_games.parquet", "College": DATA / "history" / "cfb_games.parquet"}
OUT_PATH = DATA / "app_data" / "situations.json"
LESSONS_PATH = DATA / "ai" / "lessons.json"
NOTES_PATH = DATA / "app_data" / "ai_notes.json"
EASTERN = ZoneInfo("America/New_York")

PERIODS = [("2010–2019", 2010, 2019), ("2020–2025", 2020, 2025)]
BREAK_EVEN = 0.524            # spreads and totals at -110
MIN_GAMES = 40                # fewer games than this in 2020–2025 can't settle anything
HOLDS = 0.545                 # spreads and totals: what "holds up" needs in 2020–2025
WINNER_EDGE = 0.03            # winners: beat the sportsbooks' own chances by 3 points

# Fields a situation can use. Model fields are marked: those are flattering in 2010–2019.
FIELDS = {
    "model_vegas_differ": ("The model and Vegas favor different teams", True),
    "spread_gap_abs": ("Points between the model's spread and Vegas's", True),
    "total_gap_abs": ("Points between the model's total and Vegas's", True),
    "model_likes_home": ("The model favors the home team", True),
    "model_chance": ("The model's chance for the team it favors", True),
    "vegas_chance": ("Vegas's chance for its favorite", False),
    "spread_size": ("Size of Vegas's spread, in points", False),
    "home_is_favorite": ("Vegas favors the home team", False),
    "total_line": ("Vegas's total", False),
    "week": ("Week of the season", False),
    "rest_diff": ("Home team's extra days of rest (NFL)", False),
    "divisional": ("A division game (NFL)", False),
    "outdoors": ("Played outdoors (NFL)", False),
    "wind": ("Wind in mph (NFL, outdoor games)", False),
    "temp": ("Temperature in °F (NFL, outdoor games)", False),
    "qb_change": ("A team starts a different QB than last game (NFL)", False),
    "neutral": ("Neutral site", False),
    "conference_game": ("Conference game (college)", False),
}
OPS = {"==": lambda c, v: c == v, "!=": lambda c, v: c != v, ">": lambda c, v: c > v, ">=": lambda c, v: c >= v,
       "<": lambda c, v: c < v, "<=": lambda c, v: c <= v}
BETS = {
    "model_side_winner": "The team the model favors, to win",
    "vegas_favorite_winner": "The team Vegas favors, to win",
    "model_side_spread": "The model's side against the spread",
    "favorite_spread": "The favorite against the spread",
    "underdog_spread": "The underdog against the spread",
    "home_spread": "The home team against the spread",
    "away_spread": "The away team against the spread",
    "model_side_total": "The model's side of the total",
    "over": "The over",
    "under": "The under",
}

BUILT_IN = [
    {"title": "The model and Vegas favor different teams: the model's side to win",
     "league": league, "when": [{"field": "model_vegas_differ", "op": "==", "value": True}], "bet": "model_side_winner"}
    for league in ("NFL", "College")
] + [
    {"title": "The model's spread is 3+ points from Vegas's: the model's side",
     "league": league, "when": [{"field": "spread_gap_abs", "op": ">=", "value": 3}], "bet": "model_side_spread"}
    for league in ("NFL", "College")
] + [
    {"title": "The model's total is 4+ points from Vegas's: the model's side",
     "league": league, "when": [{"field": "total_gap_abs", "op": ">=", "value": 4}], "bet": "model_side_total"}
    for league in ("NFL", "College")
]


def load(league):
    """The league's game history with every field a situation can use."""
    path = HISTORY[league]
    if not path.exists():
        return None
    h = pl.read_parquet(path)
    col = lambda name: pl.col(name) if name in h.columns else pl.lit(None)
    return h.with_columns(
        model_vegas_differ=(pl.col("model_p_home") >= 0.5) != (pl.col("mkt_p_home") >= 0.5),
        spread_gap=pl.col("model_spread") - pl.col("spread_line"),
        total_gap=col("model_total") - pl.col("total_line"),
        model_likes_home=pl.col("model_p_home") >= 0.5,
        model_chance=pl.max_horizontal(pl.col("model_p_home"), 1 - pl.col("model_p_home")),
        vegas_chance=pl.max_horizontal(pl.col("mkt_p_home"), 1 - pl.col("mkt_p_home")),
        spread_size=pl.col("spread_line").abs(),
        home_is_favorite=pl.col("spread_line") > 0,
        divisional=col("div_game").cast(pl.Boolean, strict=False),
        outdoors=col("roof").is_in(["outdoors", "open"]) if "roof" in h.columns else pl.lit(None),
        qb_change=(col("qb_change_diff").cast(pl.Float64, strict=False).abs() > 1e-9),
        neutral=pl.coalesce(col("neutral_site"), col("neutral")).cast(pl.Boolean, strict=False),
        conference_game=col("conference_game").cast(pl.Boolean, strict=False),
        wind=col("wind").cast(pl.Float64, strict=False),
        temp=col("temp").cast(pl.Float64, strict=False),
        rest_diff=col("rest_diff").cast(pl.Float64, strict=False),
    ).with_columns(spread_gap_abs=pl.col("spread_gap").abs(), total_gap_abs=pl.col("total_gap").abs())


def check_spec(spec):
    """Problems with a situation, if any. Specs come from the AI, so nothing outside these lists runs."""
    problems = []
    if spec.get("league") not in HISTORY:
        problems.append(f"unknown league {spec.get('league')!r}")
    if spec.get("bet") not in BETS:
        problems.append(f"unknown bet {spec.get('bet')!r}")
    for c in spec.get("when") or []:
        if c.get("field") not in FIELDS:
            problems.append(f"unknown field {c.get('field')!r}")
        if c.get("op") not in OPS:
            problems.append(f"unknown comparison {c.get('op')!r}")
        if not isinstance(c.get("value"), (bool, int, float)):
            problems.append(f"{c.get('field')}: the value must be a number or true/false")
    return problems


def outcomes(games, bet):
    """Each game's result for the bet: win, loss or push, plus the sportsbooks' chance for winner bets."""
    if bet in ("model_side_winner", "vegas_favorite_winner"):
        home = (pl.col("model_p_home") >= 0.5) if bet == "model_side_winner" else (pl.col("mkt_p_home") >= 0.5)
        g = games.filter(pl.col("mkt_p_home").is_not_null() & (pl.col("result") != 0))
        return g.select(
            win=home == (pl.col("result") > 0), push=pl.lit(False),
            vegas=pl.when(home).then(pl.col("mkt_p_home")).otherwise(1 - pl.col("mkt_p_home")))
    if bet.endswith("total") or bet in ("over", "under"):
        g = games.filter(pl.col("total_line").is_not_null() & pl.col("total").is_not_null())
        over = {"over": pl.lit(True), "under": pl.lit(False), "model_side_total": pl.col("total_gap") > 0}[bet]
        if bet == "model_side_total":
            g = g.filter(pl.col("total_gap").is_not_null() & (pl.col("total_gap") != 0))
        vs = pl.col("total") - pl.col("total_line")
        return g.select(win=(vs > 0) == over, push=vs == 0, vegas=pl.lit(None, pl.Float64))
    g = games.filter(pl.col("spread_line").is_not_null())
    home = {"home_spread": pl.lit(True), "away_spread": pl.lit(False), "favorite_spread": pl.col("spread_line") > 0,
            "underdog_spread": pl.col("spread_line") < 0, "model_side_spread": pl.col("spread_gap") > 0}[bet]
    if bet == "model_side_spread":
        g = g.filter(pl.col("spread_gap") != 0)
    if bet in ("favorite_spread", "underdog_spread"):
        g = g.filter(pl.col("spread_line") != 0)
    vs = pl.col("result") - pl.col("spread_line")
    return g.select(win=(vs > 0) == home, push=vs == 0, vegas=pl.lit(None, pl.Float64))


def run(spec, history):
    games = history
    for c in spec.get("when") or []:
        games = games.filter(OPS[c["op"]](pl.col(c["field"]), c["value"]).fill_null(False))
    winner = spec["bet"].endswith("winner")
    out = []
    for label, a, b in PERIODS:
        o = outcomes(games.filter(pl.col("season").is_between(a, b)), spec["bet"])
        decided = o.filter(~pl.col("push"))
        wins = int(decided["win"].sum()) if decided.height else 0
        row = {"label": label, "games": decided.height, "wins": wins, "pushes": o.height - decided.height,
               "rate": round(wins / decided.height, 3) if decided.height else None}
        if winner:
            row["vegas"] = round(decided["vegas"].mean(), 3) if decided.height else None
        out.append(row)
    return out


def verdict(spec, periods):
    early, late = periods[0], periods[1]
    winner = spec["bet"].endswith("winner")
    uses_model = any(FIELDS[c["field"]][1] for c in spec.get("when") or []) or spec["bet"].startswith("model_side")
    if late["games"] < MIN_GAMES:
        return "not enough games", f"Only {late['games']} games in 2020–2025; it needs {MIN_GAMES}+ to say anything."
    if winner:
        edge_late = late["rate"] - late["vegas"]
        edge_early = (early["rate"] - early["vegas"]) if early["games"] else 0
        if edge_late >= WINNER_EDGE and edge_early >= 0:
            return "holds up", (f"Won {late['rate']:.0%} in 2020–2025 when Vegas's chances said {late['vegas']:.0%}. Those chances have the "
                                f"bookmaker's cut removed; a real bet pays it, which eats a couple of points of that edge.")
        if abs(edge_late) < 0.015:
            how = ", about what Vegas's own chances said, so there's no edge."
        elif edge_late < 0:
            how = ", so Vegas's chances were the better guide."
        else:
            how = ", not enough to count as an edge."
        return "doesn't hold up", f"Won {late['rate']:.0%} in 2020–2025 when Vegas's chances said {late['vegas']:.0%}" + how
    ok_early = early["games"] == 0 or (early["rate"] or 0) >= BREAK_EVEN
    if late["rate"] >= HOLDS and ok_early:
        note = f"Won {late['rate']:.1%} in 2020–2025, above the 52.4% break-even."
        if uses_model:
            note += " The 2010–2019 result is flattering, because the model was fit on those years."
        return "holds up", note
    return "doesn't hold up", f"Won {late['rate']:.1%} in 2020–2025; it needs about {HOLDS:.1%} to beat the 52.4% break-even with room to spare."


def describe(spec):
    parts = []
    for c in spec.get("when") or []:
        name, _ = FIELDS[c["field"]]
        if isinstance(c["value"], bool):
            parts.append(name if (c["op"] == "==") == c["value"] else f"not: {name.lower()}")
        else:
            parts.append(f"{name} {c['op']} {c['value']:g}")
    return "; ".join(parts) or "every game", BETS[spec["bet"]]


def spec_id(spec):
    return hashlib.sha1(json.dumps({k: spec.get(k) for k in ("league", "when", "bet")}, sort_keys=True).encode()).hexdigest()[:10]


def main():
    histories = {league: load(league) for league in HISTORY}
    lessons = json.loads(LESSONS_PATH.read_text()) if LESSONS_PATH.exists() else {"leagues": {}}
    checks = [dict(s, source="built in") for s in BUILT_IN]
    for league, items in lessons.get("leagues", {}).items():
        for lesson in items:
            if lesson.get("check"):
                checks.append(dict(lesson["check"], league=league, title=lesson["lesson"], source="AI lesson"))

    results, by_id, lines = [], {}, []
    for spec in checks:
        problems = check_spec(spec)
        if problems or histories.get(spec["league"]) is None:
            result = {"verdict": "couldn't test", "note": "; ".join(problems) or "No game history from this run."}
        else:
            periods = run(spec, histories[spec["league"]])
            v, note = verdict(spec, periods)
            result = {"verdict": v, "note": note, "periods": periods}
        conditions, bet = describe(spec) if not problems else ("", "")
        entry = {"id": spec_id(spec), "league": spec["league"], "title": spec["title"], "source": spec["source"],
                 "conditions": conditions, "bet": bet, **result}
        results.append(entry)
        by_id[entry["id"]] = entry
        lines.append(f"  {spec['league']}: {spec['title'][:70]} -> {entry['verdict']}")

    # Results next to each lesson, for the website and for the AI's next run
    tested = datetime.now(EASTERN).isoformat(timespec="minutes")
    for path in (LESSONS_PATH, NOTES_PATH):
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        for league, block in doc.get("leagues", {}).items():
            items = block if isinstance(block, list) else block.get("lessons", [])
            for lesson in items:
                if lesson.get("check"):
                    r = by_id.get(spec_id(dict(lesson["check"], league=league)))
                    if r:
                        lesson["test_result"] = {k: r.get(k) for k in ("verdict", "note", "periods")} | {"tested": tested}
        path.write_text(json.dumps(doc, indent=1))

    OUT_PATH.write_text(json.dumps({"kind": "situations", "updated": tested, "break_even": BREAK_EVEN,
                                    "checks": results}, indent=1))
    print("\n".join([f"Situation tester: {len(results)} situations"] + lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("<details><summary><b>situations</b></summary>\n\n```\n" + "\n".join(lines) + "\n```\n</details>\n\n")


if __name__ == "__main__":
    main()
