# wavu-stats

Small CLI tool that pulls TEKKEN 8 ranked match data from the public
[wank.wavu.wiki](https://wank.wavu.wiki/api) API into a local SQLite file and
generate gameplay statistic

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py top-up                 # grab newest games since last run
python main.py backfill --days 14     # build up 14 days of history
python main.py info                   # games stored / date range / patches

python main.py analyze --view chars        --min-games 200
python main.py analyze --view rank         --rank-floor "Tekken King" --min-games 50
python main.py analyze --view matchups     --character King --min-games 30
python main.py analyze --view distribution # rank distribution of the playerbase

python main.py report --html --csv    # writes out/dashboard.html + CSVs
python main.py report --interactive --out docs --version-floor 30000 --rank-floor 29  # writes docs/index.html from version 30000 and onwards, matchup matrix from GoD and onwards (check constants.py)
```

Open `out/` to see the generated reports