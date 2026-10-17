"""Build the website's Top picks lists from the models' numbers, save them to a log, and grade them.

The workflow runs this from the repository's top folder, after the notebooks:

    python scripts/top_picks.py

It reads data/app_data/nfl.json and cfb.json, which the notebooks write. With the ODDS_API_KEY secret, it also gets
the sportsbooks' prices for the player milestones on the lists from The Odds API (see odds_api.py). It saves:
- data/top_picks_log.csv: every list entry. Each game's entries lock at kickoff. Until then, every run replaces them
  with the current lists, the same way the props log works.
- data/app_data/top_picks.json: this week's lists, last week's graded lists and each list's record, for the website.

The lists only rearrange numbers the models already made. Nothing here changes a pick or a model.
Grading uses the final scores in the pick logs and the player stats in the props log.
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import odds_api

DATA = Path(__file__).resolve().parent.parent / "data"
LOG_PATH = DATA / "top_picks_log.csv"
OUT_PATH = DATA / "app_data" / "top_picks.json"
PROPS_LOG = DATA / "nfl_props_log.csv"
EASTERN = ZoneInfo("America/New_York")

LEAGUES = {
    "NFL": {"file": "nfl.json", "log": "nfl_pick_log.csv", "away": "away_score", "home": "home_score"},
    "College": {"file": "cfb.json", "log": "ncaa_pick_log.csv", "away": "away_points", "home": "home_points"},
}

# How the lists are chosen. The website's descriptions read these numbers from top_picks.json.
SETTINGS = {
    "list_size": 5,               # entries in each game list
    "props_per_stat": 2,          # entries per prop type in each props list
    "standard_price": -110,       # the price assumed for spreads and totals, which the data doesn't include
    "min_edge": 0.02,             # best value: marked as beating the break-even when the model's chance is 2+ points above it
    "underdog_vegas_max": 0.40,   # risky underdogs: the sportsbook gives them 40% or less...
    "underdog_model_min": 0.30,   # ...and the model gives them 30% or more
    "likely_prop_min": 0.70,      # most likely milestones: 70% or more
    "risky_prop": [0.25, 0.50],   # risky milestones: 25% to 50%
    "prop_floor": {"passing_yards": 200, "rushing_yards": 50, "receiving_yards": 50, "receptions": 4},
    "big_game": {"passing_yards": 300, "rushing_yards": 100, "receiving_yards": 100, "receptions": 8},
}
LISTS = ["likely", "value", "risky", "props_likely", "props_risky"]
STAT_WORDS = {"passing_yards": "passing yards", "rushing_yards": "rushing yards",
              "receiving_yards": "receiving yards", "receptions": "receptions"}
COLUMNS = ["logged_at_et", "league", "list", "season", "week", "game_id", "kickoff", "matchup", "kind", "pick",
           "side", "team", "opp", "player_id", "player", "stat", "line", "chance", "vegas_chance", "price", "books",
           "edge", "result", "actual"]
NUMBERS = {"season": int, "week": int, "line": float, "chance": float, "vegas_chance": float, "price": int,
           "books": int, "edge": float, "actual": float}


# ---------- prices ----------
def profit(price):
    """What a winning 1-unit bet pays at American odds: +150 pays 1.5, -150 pays 0.667."""
    return price / 100 if price > 0 else 100 / -price


def break_even(price):
    """The chance a bet at this price needs to win to break even: 52.4% at -110."""
    return 1 / (1 + profit(price))


def team_line(side, home_margin):
    """A spread written the sportsbook way, for one side: home_margin 3 means the home team is -3."""
    line = -home_margin if side == "home" else home_margin
    return "PK" if line == 0 else f"{line:+g}".replace("-", "−")


# ---------- building the lists ----------
def kickoff(g):
    return datetime.fromisoformat(g["kickoff"])


def upcoming_games(d, now):
    """Games that haven't kicked off, have a sportsbook spread and the model's numbers. College games against
    lower-division teams are left out, as on the website."""
    return [g for g in d["games"] if kickoff(g) > now and g["vegas"].get("home_margin") is not None
            and g["model"].get("home_win") is not None and g.get("fbs_vs_fbs", True)]


def entry(league, lst, d, g, **fields):
    e = {"league": league, "list": lst, "season": d["season"], "week": d["week"], "game_id": str(g["id"]),
         "kickoff": g["kickoff"], "matchup": f"{g['away']} at {g['home']}", "side": None, "team": None, "opp": None,
         "player_id": None, "player": None, "stat": None, "line": None, "vegas_chance": None, "price": None,
         "books": None, "edge": None, "result": None, "actual": None}
    e.update(fields)
    if e["price"] is not None:
        e["price"] = int(round(e["price"]))
    if e["price"] is not None and e["edge"] is None:
        e["edge"] = round(e["chance"] - break_even(e["price"]), 3)
    return e


def team_sides(g):
    m, v = g["model"], g["vegas"]
    p, pv = m["home_win"], v.get("home_win")
    yield "home", g["home"], g["away"], p, pv, v.get("home_moneyline")
    yield "away", g["away"], g["home"], 1 - p, None if pv is None else 1 - pv, v.get("away_moneyline")


def game_lists(league, d, now):
    """Most likely winners, best value and risky underdogs.

    Best value only uses spreads and totals. Their chances come from how the model's past disagreements with the
    sportsbooks actually turned out (the cover chance and over chance in Step 12 and Step 6/9 of the notebooks), so
    they're honest about the model's real edge. Moneylines are left out: the tests found the sportsbooks' win
    chances more accurate than the model's, so a gap there isn't evidence of value. The list shows the five
    closest calls even when none of them beats the break-even chance; the website says which ones do."""
    s = SETTINGS
    likely, risky, value = [], [], []
    for g in upcoming_games(d, now):
        options = []
        for side, team, opp, p, pv, price in team_sides(g):
            winner = dict(kind="winner", side=side, team=team, opp=opp, pick=f"{team} to win", chance=round(p, 3),
                          vegas_chance=None if pv is None else round(pv, 3), price=price)
            if p >= 0.5:
                likely.append(entry(league, "likely", d, g, **winner))
            if price is not None and pv is not None and pv <= s["underdog_vegas_max"] and p >= s["underdog_model_min"]:
                risky.append(entry(league, "risky", d, g, **winner))
            cover = g["model"].get("home_cover")
            if cover is not None:
                hm = g["vegas"]["home_margin"]
                options.append(dict(kind="spread", side=side, team=team, opp=opp, line=hm, pick=f"{team} {team_line(side, hm)}",
                                    chance=round(cover if side == "home" else 1 - cover, 3), price=s["standard_price"]))
        over, total = g["model"].get("over"), g["vegas"].get("total")
        if over is not None and total is not None:
            for side, c in (("over", over), ("under", 1 - over)):
                options.append(dict(kind="total", side=side, line=total, pick=f"{side.title()} {total:g}",
                                    chance=round(c, 3), price=s["standard_price"]))
        if options:                       # one value entry per game: its biggest edge
            value.append(max((entry(league, "value", d, g, **o) for o in options), key=lambda e: e["edge"]))
    n = s["list_size"]
    return (sorted(likely, key=lambda e: -e["chance"])[:n]
            + sorted(value, key=lambda e: -e["edge"])[:n]
            + sorted(risky, key=lambda e: -e["chance"])[:n])


def prop_lists(league, d, now):
    s = SETTINGS
    games = {str(g["id"]): g for g in d["games"]}
    likely, risky = {}, {}
    for p in d.get("props") or []:
        g = games.get(str(p["game"]))
        if not g or kickoff(g) <= now or not p.get("milestones"):
            continue
        stat = p["stat"]
        ladder = sorted((float(t), c) for t, c in p["milestones"].items())
        sure = [(t, c) for t, c in ladder if t >= s["prop_floor"][stat] and c >= s["likely_prop_min"]]
        long = [(t, c) for t, c in ladder if t >= s["big_game"][stat] and s["risky_prop"][0] <= c < s["risky_prop"][1]]
        common = dict(kind="prop", side="at least", team=p["team"], opp=p["opp"], player_id=p.get("player_id"),
                      player=p["player"], stat=stat)
        if sure:
            t, c = sure[-1]           # the biggest milestone that's still likely
            likely.setdefault(stat, []).append(entry(league, "props_likely", d, g, line=t, chance=c,
                                                     pick=f"{p['player']} {t:g}+ {STAT_WORDS[stat]}", **common))
        if long:
            t, c = long[-1]           # the biggest milestone that's still possible
            risky.setdefault(stat, []).append(entry(league, "props_risky", d, g, line=t, chance=c,
                                                    pick=f"{p['player']} {t:g}+ {STAT_WORDS[stat]}", **common))
    n, out = s["props_per_stat"], []
    for stat in STAT_WORDS:
        out += sorted(likely.get(stat, []), key=lambda e: (-e["line"], -e["chance"]))[:n]
    for stat in STAT_WORDS:
        out += sorted(risky.get(stat, []), key=lambda e: (-e["chance"], -e["line"]))[:n]
    return out


def attach_prices(league, d, entries, now):
    """The sportsbooks' prices for the player milestones on the lists, from The Odds API's alternate ("at least")
    lines. To save credits it only asks for the props on the lists, in games within 3 days of kickoff, and reuses
    anything fetched in the last 12 hours. Without a key, it still uses prices saved by earlier runs."""
    props = [e for e in entries if e["kind"] == "prop"]
    if league != "NFL" or not props:
        return
    saved = odds_api.load()
    games = {str(g["id"]): g for g in d["games"]}
    due = {}
    for e in props:
        k = kickoff(games[e["game_id"]])
        fetched = ((saved["games"].get(e["game_id"]) or {}).get("alternate") or {}).get("fetched") or {}
        if k - now < timedelta(hours=odds_api.WINDOW_HOURS) and not odds_api.fresh(fetched.get(e["stat"]), now):
            due.setdefault(e["game_id"], set()).add(e["stat"])
    if odds_api.key() and due:
        client = odds_api.Client(saved)
        try:
            for gid, stats in due.items():
                g = games[gid]
                event = client.event_id(gid, g["home_name"], g["away_name"], kickoff(g))
                if event:
                    client.alternates(gid, event, kickoff(g), sorted(stats))
                else:
                    print(f"No sportsbook game found for {g['away']} at {g['home']}.")
        except odds_api.OddsStop:
            pass
        odds_api.save(saved)
        left = (saved.get("credits") or {}).get("remaining")
        print(f"Milestone prices: asked for {sum(len(s) for s in due.values())} prop ladders in {len(due)} games, "
              f"{client.credits} credits" + (f", {left} left this month" if left is not None else ""))
    for e in props:
        price, books = odds_api.milestone_price(saved, e["game_id"], e["player"], e["stat"], e["line"])
        if price is not None:
            e["price"], e["books"] = price, books
            e["edge"] = round(e["chance"] - break_even(price), 3)


# ---------- the log ----------
def read_log():
    if not LOG_PATH.exists():
        return []
    rows = []
    with LOG_PATH.open(newline="") as f:
        for r in csv.DictReader(f):
            for k in COLUMNS:
                v = r.get(k, "")
                r[k] = None if v == "" else NUMBERS[k](float(v)) if k in NUMBERS else v
            rows.append(r)
    return rows


def write_log(rows):
    rows = sorted(rows, key=lambda r: (r["kickoff"], r["league"], LISTS.index(r["list"]), r["game_id"], r["pick"]))
    with LOG_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r.get(k) is None else r[k] for k in COLUMNS})


# ---------- grading ----------
def final_scores():
    """Final scores by game, from both pick logs and from this week's website data."""
    scores = {}
    for league, cfg in LEAGUES.items():
        path = DATA / cfg["log"]
        if path.exists():
            with path.open(newline="") as f:
                for r in csv.DictReader(f):
                    if r.get(cfg["away"]) not in (None, "") and r.get(cfg["home"]) not in (None, ""):
                        scores[(league, r["game_id"])] = (float(r[cfg["away"]]), float(r[cfg["home"]]))
        app = DATA / "app_data" / cfg["file"]
        if app.exists():
            for g in json.loads(app.read_text())["games"]:
                if g.get("final"):
                    scores.setdefault((league, str(g["id"])), (float(g["final"]["away"]), float(g["final"]["home"])))
    return scores


def prop_results():
    """Each player's real stats, and which games have stats in yet."""
    actual, games_in = {}, set()
    if PROPS_LOG.exists():
        with PROPS_LOG.open(newline="") as f:
            for r in csv.DictReader(f):
                if r.get("actual") not in (None, ""):
                    actual[(r["game_id"], r["player_id"], r["stat"])] = float(r["actual"])
                    games_in.add(r["game_id"])
    return actual, games_in


def grade(rows):
    scores = final_scores()
    actual, games_in = prop_results()
    for r in rows:
        if r["result"] is not None:
            continue
        if r["kind"] == "prop":
            key = (r["game_id"], r["player_id"], r["stat"])
            if key in actual:
                r["actual"] = actual[key]
                r["result"] = "hit" if actual[key] >= r["line"] else "miss"
            elif r["game_id"] in games_in and (r["league"], r["game_id"]) in scores:
                r["result"] = "void"          # the game's stats are in but he has none: he didn't play
            continue
        final = scores.get((r["league"], r["game_id"]))
        if final is None:
            continue
        away, home = final
        margin = home - away
        if r["kind"] == "winner":
            mine = margin if r["side"] == "home" else -margin
            r["actual"] = mine
            r["result"] = "push" if mine == 0 else "hit" if mine > 0 else "miss"
        elif r["kind"] == "spread":
            beat = (margin - r["line"]) if r["side"] == "home" else (r["line"] - margin)
            r["actual"] = margin
            r["result"] = "push" if beat == 0 else "hit" if beat > 0 else "miss"
        elif r["kind"] == "total":
            total = home + away
            beat = (total - r["line"]) if r["side"] == "over" else (r["line"] - total)
            r["actual"] = total
            r["result"] = "push" if beat == 0 else "hit" if beat > 0 else "miss"
    return rows


def record(rows):
    """Hits next to what the model's chances added up to, plus units won or lost where there's a price."""
    decided = [r for r in rows if r["result"] in ("hit", "miss")]
    priced = [r for r in rows if r["price"] is not None and r["result"] in ("hit", "miss", "push")]
    units = sum(profit(r["price"]) if r["result"] == "hit" else -1 if r["result"] == "miss" else 0 for r in priced)
    return {
        "graded": len(decided),
        "hits": sum(r["result"] == "hit" for r in decided),
        "expected": round(sum(r["chance"] for r in decided), 1),
        "pushes": sum(r["result"] == "push" for r in rows),
        "voids": sum(r["result"] == "void" for r in rows),
        "units": round(units, 2) if priced else None,
        "priced": len(priced),
    }


def public(r):
    keep = ["list", "kind", "pick", "matchup", "kickoff", "game_id", "side", "team", "opp", "player", "stat", "line",
            "chance", "vegas_chance", "price", "books", "edge", "result", "actual"]
    out = {k: r.get(k) for k in keep}
    out["key"] = item_key(r)
    return out


def item_key(r):
    return "|".join(str(r.get(k) or "") for k in ("league", "list", "game_id", "kind", "side", "player_id", "stat", "line"))


def main():
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(EASTERN).strftime("%Y-%m-%d %H:%M")
    rows = read_log()
    data = {}
    for league, cfg in LEAGUES.items():
        path = DATA / "app_data" / cfg["file"]
        if not path.exists():
            continue
        d = data[league] = json.loads(path.read_text())
        open_games = {str(g["id"]) for g in d["games"] if kickoff(g) > now}
        fresh = game_lists(league, d, now) + prop_lists(league, d, now)
        attach_prices(league, d, fresh, now)
        for e in fresh:
            e["logged_at_et"] = stamp
        # Games that haven't kicked off get this run's lists; games that have started stay locked
        rows = [r for r in rows if not (r["league"] == league and r["game_id"] in open_games)] + fresh
    rows = grade(rows)
    write_log(rows)

    out = {"kind": "top_picks", "updated": now.astimezone(EASTERN).isoformat(timespec="minutes"),
           "settings": SETTINGS, "leagues": {}}
    for league, d in data.items():
        season, week = d["season"], d["week"]
        mine = [r for r in rows if r["league"] == league and r["season"] == season]
        this_week = [r for r in mine if r["week"] == week]
        earlier = sorted({r["week"] for r in mine if r["week"] < week and r["result"] is not None})
        last = [r for r in mine if earlier and r["week"] == earlier[-1]]
        out["leagues"][league] = {
            "season": season, "week": week, "week_label": d.get("week_label"),
            "lists": {k: [public(r) for r in this_week if r["list"] == k] for k in LISTS},
            "last_week": {"week": earlier[-1] if earlier else None,
                          "lists": {k: [public(r) for r in last if r["list"] == k] for k in LISTS}},
            "record": {k: record([r for r in mine if r["list"] == k]) for k in LISTS},
        }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=1))

    lines = [f"Top picks: {LOG_PATH.name} has {len(rows)} entries."]
    for league, L in out["leagues"].items():
        counts = ", ".join(f"{k} {len(v)}" for k, v in L["lists"].items() if v)
        lines.append(f"  {league} {L['week_label']}: {counts or 'no lists (no upcoming games with lines)'}")
        for k, rec in L["record"].items():
            if rec["graded"]:
                lines.append(f"    {k}: {rec['hits']} of {rec['graded']} hit, {rec['expected']} expected"
                             + (f", {rec['units']:+.2f} units" if rec["units"] is not None else ""))
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("<details><summary><b>top_picks</b> finished</summary>\n\n```\n" + "\n".join(lines) + "\n```\n</details>\n\n")


if __name__ == "__main__":
    main()
