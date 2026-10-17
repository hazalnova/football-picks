# football-picks

NFL and college football predictions: winners, spreads, totals and NFL player props, compared with the sportsbooks every week. GitHub runs the models on a schedule and publishes the results to the **Line Check** website.

**Website:** https://hazalnova.github.io/football-picks/

## What runs when

The **Update picks** workflow (in the **Actions** tab) runs on this schedule. Times are Central and can start a few minutes late.

| When | What runs |
|---|---|
| Tuesday, about 9:15 AM | Post-game review, then this week's college picks |
| Thursday, about 9:15 AM | Review, NFL picks before Thursday night, and fresh college lines |
| Saturday, about 8:15 AM | Fresh college lines before the Saturday games |
| Sunday, about 6:15 AM | NFL props with the final injury reports |

From Nov 1 to mid-March, when Central time falls back an hour, each run starts an hour earlier.

Every run saves the updated logs to the `data` folder and republishes the website. The first logged pick for each game still counts, the same as in Colab, so a later run never changes a logged pick.

After the notebooks, every run also does two more things:
1. **Top picks lists** (`scripts/top_picks.py`). Builds the lists on the website's **Top picks** tab from the models' own chances: the most likely winners, the best value against the sportsbook, risky underdogs, and, for the NFL, the most likely and the risky player milestones. Each game's entries lock at kickoff and are graded after the game in `data/top_picks_log.csv`, so the site can show whether "likely" really meant likely.
2. **AI news check** (`scripts/ai_notes.py`). Claude reads the lists, the latest results and the post-game reviews, searches the web for news the models can't see, like injuries and quarterback changes, and writes short notes with links. It also keeps a list of patterns it notices in `data/ai/lessons.json` and reads it again next run. That file is its memory. The AI only adds notes: it never changes a pick, a list or a model. Its lessons are ideas to test on past seasons first. This step needs the `ANTHROPIC_API_KEY` secret (see **Secrets**), and without it, it's skipped.

**To run it now:** open **Actions → Update picks → Run workflow**, choose what to run, and click the green button. It takes about 10–15 minutes.

**To see what a run did:** open the run in the **Actions** tab. The summary page shows what each notebook printed: this week's game cards, the scorecard and what was saved. The full notebooks, tables included, are under **Artifacts → notebooks-with-output**.

If a run fails, GitHub emails you. The picks keep running even if the post-game review can't get this week's play-by-play.

## What's where

| Folder | What's in it |
|---|---|
| `notebooks/` | The three notebooks the workflow runs: `game_review`, `ncaa_game_model` and `nfl_game_model` |
| `data/` | The pick logs, props log, Top picks log, review files, saved preseason and efficiency data, `ai/lessons.json` with the AI's lessons, and `app_data/` with the website's data |
| `site/` | The website, `index.html`. It reads `nfl.json`, `cfb.json`, `top_picks.json` and `ai_notes.json` from `data/app_data/` when the workflow publishes it |
| `scripts/` | `run_notebook.py`, which runs a notebook from top to bottom the way Colab's **Run all** does; `top_picks.py`, which builds and grades the Top picks lists; and `ai_notes.py`, the AI news check |
| `.github/workflows/` | `update.yml`, the schedule and steps |

## Changing things

- **The models:** edit a notebook here. To open it in Colab, choose **File → Open notebook → GitHub**, allow access to private repositories, and pick `hazalnova/football-picks`. Save it back with **File → Save a copy in GitHub**. The next run uses the new version.
- **The website:** edit `site/index.html`. Saving a change to it republishes the site within a couple of minutes, without running the models.
- **The schedule:** edit the `cron` lines at the top of `.github/workflows/update.yml`.
- **The Top picks lists:** the thresholds, like the 70% for "most likely" milestones, are in `SETTINGS` at the top of `scripts/top_picks.py`. The website's descriptions follow them.
- **The AI:** the instructions it follows are `SYSTEM` near the top of `scripts/ai_notes.py`. To use a different Claude model or allow more searches per run, add a repository variable under **Settings → Secrets and variables → Actions → Variables**: `AI_MODEL` (for example `claude-haiku-5-5`, which costs much less) or `AI_MAX_SEARCHES`, the most web searches per league in a run (8 unless set).

The copies of the notebooks in Google Drive are now just for trying things out. If you run them in Colab, they write to the old logs in Drive, not to this repository.

## Secrets

Both keys live under **Settings → Secrets and variables → Actions**. They never appear in the code, the logs or the website.

- **`CFBD_API_KEY`**: the college notebook refreshes its preseason data from CollegeFootballData with it. Without it, the notebook uses the saved preseason file in `data/cfbd/`, which covers the current season.
- **`ANTHROPIC_API_KEY`**: turns on the AI news check. Create it in the Claude Console at platform.claude.com, under **Settings → API keys**. API use is billed in the Console, separately from a Claude chat subscription. With the default model, Claude Sonnet 5.5 ($2 per million tokens read, $10 per million written, plus $10 per 1,000 web searches), a run usually costs $0.50 to $1, or roughly $10 to $15 a month during the season. Each run's summary page shows its estimated cost. To cap spending, create the key in a Console workspace with a monthly spend limit.

## Data sources

nflverse (NFL games, players and lines), sportsdataverse and CollegeFootballData (college games and play-by-play), and ESPN's public scoreboard for this week's college lines. The AI's news comes from Claude's web search, with links to each source. For fans and research, not betting advice.
