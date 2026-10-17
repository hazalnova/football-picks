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

**To run it now:** open **Actions → Update picks → Run workflow**, choose what to run, and click the green button. It takes about 10–15 minutes.

**To see what a run did:** open the run in the **Actions** tab. The summary page shows what each notebook printed: this week's game cards, the scorecard and what was saved. The full notebooks, tables included, are under **Artifacts → notebooks-with-output**.

If a run fails, GitHub emails you. The picks keep running even if the post-game review can't get this week's play-by-play.

## What's where

| Folder | What's in it |
|---|---|
| `notebooks/` | The three notebooks the workflow runs: `game_review`, `ncaa_game_model` and `nfl_game_model` |
| `data/` | The pick logs, props log, review files, saved preseason and efficiency data, and `app_data/` with the website's data |
| `site/` | The website, `index.html`. It reads `nfl.json` and `cfb.json` from `data/app_data/` when the workflow publishes it |
| `scripts/` | `run_notebook.py`, which runs a notebook from top to bottom the way Colab's **Run all** does |
| `.github/workflows/` | `update.yml`, the schedule and steps |

## Changing things

- **The models:** edit a notebook here. To open it in Colab, choose **File → Open notebook → GitHub**, allow access to private repositories, and pick `hazalnova/football-picks`. Save it back with **File → Save a copy in GitHub**. The next run uses the new version.
- **The website:** edit `site/index.html`. Saving a change to it republishes the site within a couple of minutes, without running the models.
- **The schedule:** edit the `cron` lines at the top of `.github/workflows/update.yml`.

The copies of the notebooks in Google Drive are now just for trying things out. If you run them in Colab, they write to the old logs in Drive, not to this repository.

## Secrets

The college notebook refreshes its preseason data from CollegeFootballData with the `CFBD_API_KEY` secret, set under **Settings → Secrets and variables → Actions**. The key never appears in the code or the logs. Without it, the notebook uses the saved preseason file in `data/cfbd/`, which covers the current season.

## Data sources

nflverse (NFL games, players and lines), sportsdataverse and CollegeFootballData (college games and play-by-play), and ESPN's public scoreboard for this week's college lines. For fans and research, not betting advice.
