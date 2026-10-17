"""Sportsbook prop odds from The Odds API (the-odds-api.com), for scripts/top_picks.py.

The NFL notebook fetches each game's main prop lines itself (Step 10), with its own copy of these helpers so it still
runs on its own in Colab. Both save to the same file, data/odds/nfl_prop_odds.json, so each game is fetched about
once a week. The key comes from the ODDS_API_KEY secret and is never printed.

How credits are counted: one credit per prop market with data, per game, for the one region ("us") requested.
Listing the week's games is free.
"""
import json
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
ODDS_FILE = DATA / "odds" / "nfl_prop_odds.json"
ODDS_URL = os.environ.get("ODDS_API_URL", "https://api.the-odds-api.com") + "/v4/sports/americanfootball_nfl"
WINDOW_HOURS = 72          # only fetch games that kick off within this many hours...
REFRESH_HOURS = 12         # ...and that weren't fetched more recently than this
KEEP_DAYS = 10             # saved odds for games older than this are dropped
MARKETS = {"passing_yards": "player_pass_yds", "rushing_yards": "player_rush_yds",
           "receiving_yards": "player_reception_yds", "receptions": "player_receptions"}
STATS = {v: k for k, v in MARKETS.items()}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
FATAL = {"INVALID_KEY", "MISSING_KEY", "DEACTIVATED_KEY", "OUT_OF_USAGE_CREDITS"}
HINTS = {"INVALID_KEY": "Check the ODDS_API_KEY secret.",
         "DEACTIVATED_KEY": "The key was deactivated; get a new one at the-odds-api.com.",
         "OUT_OF_USAGE_CREDITS": "This month's credits are used up. Prices come back when they reset."}


class OddsStop(Exception):
    """The key is missing, wrong or out of credits: stop asking for the rest of this run."""


def key():
    return (os.environ.get("ODDS_API_KEY") or "").strip().strip("\"'“”").strip() or None


def name_key(name):
    """A player's name for matching across data sources: "D.J. Moore Jr." and "DJ Moore" both become "dj moore"."""
    text = "".join(c if c.isalnum() or c.isspace() else " " if c == "-" else "" for c in (name or "").lower())
    return " ".join(w for w in text.split() if w not in SUFFIXES)


def to_prob(price):
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def to_price(prob):
    return round(-100 * prob / (1 - prob)) if prob >= 0.5 else round(100 * (1 - prob) / prob)


def middle_price(prices):
    """The middle of several books' prices, worked out on their implied chances so +105 and -105 average sensibly."""
    return to_price(statistics.median(to_prob(p) for p in prices)) if prices else None


def load():
    try:
        return json.loads(ODDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"games": {}}


def save(saved):
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    saved["games"] = {g: v for g, v in saved["games"].items() if datetime.fromisoformat(v["kickoff"]) > cutoff}
    ODDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ODDS_FILE.write_text(json.dumps(saved, indent=1, sort_keys=True))


class Client:
    def __init__(self, saved):
        self.saved = saved
        self.credits = 0
        self.events = None

    def get(self, path, **params):
        """One request. Returns the data, None if this request didn't work, or raises OddsStop."""
        try:
            r = requests.get(f"{ODDS_URL}{path}", params={"apiKey": key(), **params}, timeout=30)
        except requests.RequestException as e:          # the message can include the URL and key, so only the type
            print(f"Couldn't reach The Odds API ({type(e).__name__}).")
            return None
        if r.headers.get("x-requests-remaining") is not None:
            self.saved["credits"] = {"remaining": r.headers.get("x-requests-remaining"), "used": r.headers.get("x-requests-used"),
                                     "checked": datetime.now(timezone.utc).isoformat(timespec="minutes")}
            self.credits += int(float(r.headers.get("x-requests-last") or 0))
        if r.ok:
            return r.json()
        try:
            err = r.json()
        except ValueError:
            err = {}
        code = err.get("error_code") or str(r.status_code)
        print(f"The Odds API said no ({code}). {HINTS.get(code, '')}".strip())
        if code in FATAL or r.status_code == 401:
            raise OddsStop(code)
        return None

    def event_id(self, game_id, home_name, away_name, kickoff):
        """The game's id at The Odds API, matched on the two team nicknames and the kickoff time. Listing games is free."""
        g = self.saved["games"].get(game_id, {})
        if g.get("event_id"):
            return g["event_id"]
        if self.events is None:
            self.events = self.get("/events") or []
        want = {home_name.split()[-1], away_name.split()[-1]}
        for e in self.events:
            when = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            if {e["home_team"].split()[-1], e["away_team"].split()[-1]} == want and abs(when - kickoff) < timedelta(hours=36):
                return e["id"]
        return None

    def alternates(self, game_id, event_id, kickoff, stats):
        """Fetch the "at least" ladders (alternate lines) for some props in one game and save them."""
        g = self.saved["games"].setdefault(game_id, {"kickoff": kickoff.isoformat()})
        g["event_id"] = event_id
        data = self.get(f"/events/{event_id}/odds", regions="us", oddsFormat="american",
                        markets=",".join(MARKETS[s] + "_alternate" for s in stats))
        if data is None:
            return
        alt = g.setdefault("alternate", {"lines": {}})
        for s in stats:                                  # these props are being refreshed
            alt["lines"] = {k: v for k, v in alt["lines"].items() if not k.endswith("|" + s)}
        for book in data.get("bookmakers", []):
            for m in book.get("markets", []):
                stat = STATS.get(m["key"].removesuffix("_alternate"))
                for o in m.get("outcomes", []):
                    if stat and o.get("name") == "Over" and o.get("point") is not None and o.get("description"):
                        ladder = alt["lines"].setdefault(f"{name_key(o['description'])}|{stat}", {})
                        ladder.setdefault(str(float(o["point"])), {})[book["key"]] = o["price"]
        stamp = datetime.now(timezone.utc).isoformat(timespec="minutes")
        alt.setdefault("fetched", {}).update({s: stamp for s in stats})     # when each prop's ladder was fetched


def fresh(stamp, now):
    return stamp is not None and now - datetime.fromisoformat(stamp) < timedelta(hours=REFRESH_HOURS)


def milestone_price(saved, game_id, player, stat, milestone):
    """The books' middle price for "at least `milestone`" (an over at milestone - 0.5), and how many books offer it."""
    g = saved["games"].get(game_id) or {}
    k = f"{name_key(player)}|{stat}"
    point = float(milestone) - 0.5
    prices = dict(((g.get("alternate") or {}).get("lines") or {}).get(k, {}).get(str(point), {}))   # book: price
    for book, line, over, _under in ((g.get("standard") or {}).get("lines") or {}).get(k, []):
        if float(line) == point:                         # a book's main line can be the same as a milestone
            prices.setdefault(book, over)
    return middle_price(list(prices.values())), len(prices)
