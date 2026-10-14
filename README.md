# Netflix Catalog Gap Analysis (Global + Indonesia)

Where does Netflix's catalog deliver audience-rated quality, where is it thin compared with the rest of the world, and how does Indonesian content compare?

**Stack:** Python, PostgreSQL, Power BI. Netflix titles (Kaggle, 8,807 titles through 2021) matched to IMDb ratings.

## Key findings

- **Match:** 7,492 of 8,807 titles matched to IMDb (85.1%). Audited precision: 100% for exact matches, 96.7% for ±1-year matches.
- **Strongest genres:** Classic Movies (index 2.61), Anime Series (2.39), TV Action & Adventure (2.04).
- **Weakest genres:** Horror Movies (0.22), Faith & Spirituality (0.31), Children & Family Movies (0.49).
- **Countries:** Japan (1.84), Ireland (1.83) and South Korea (1.71) lead. Nigeria (0.00) and Taiwan (0.35) trail, partly because their titles get few IMDb votes.
- **Coverage gaps:** compared with the world, Netflix is thinnest in War (1.50) and Thriller (1.31) movies and in Sport (1.18) and Romance (1.16) series.
- **Indonesia** (79 of 90 titles matched): heavy on Dramas (68%), Romantic Movies (30%) and Horror (13%), all well above the global mix.

## Method

1. **Clean** the Netflix data (`notebooks/`) and filter IMDb to movies and series with ratings (`scripts/01_filter_imdb.py`).
2. **Load** both into PostgreSQL (`scripts/02_load_postgres.py`).
3. **Match** Netflix to IMDb on normalized title + year + type, in two tiers: exact year, then ±1 year (`scripts/03_run_match.py`). Ties go to the IMDb title with the most votes. A sample of 60 matches was audited; results are in `docs/match_report.md`.
4. **Analyse** in SQL (`scripts/04_build_marts.py`), then export aggregate tables to `dashboard/data/` for Power BI.

**Definitions**
- **High-rated:** IMDb rating ≥ 7.0 with ≥ 1,000 votes.
- **Quality index:** a segment's high-rated rate ÷ the rate across all matched titles. Above 1 means better than average.
- **Coverage gap:** a genre's share of the world's high-rated titles (IMDb, 2000 on) ÷ its share of Netflix's high-rated titles. Above 1 means Netflix is thin there.
- Segments with fewer than 30 titles are shown but not ranked.

## Limitations

- IMDb votes measure popularity, not Netflix viewership, and the ratings were downloaded in 2026 while the catalog ends in 2021.
- 14.9% of titles are unmatched. Titles with no country listed match only 55.2% of the time, so country "Unknown" is not ranked.
- Low country scores can reflect low IMDb visibility (few votes) rather than low ratings.
- Indonesia is too small for per-genre indices, so it is shown as counts and shares only.
- The top of the genre ranking shifts with the rating and vote thresholds. The bottom is stable.

## Setup

Requires Python 3.13 and PostgreSQL 14+. Run from the repo root in PowerShell.

1. Install dependencies:
   ```powershell
   python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
   ```
2. Create the database `netflix_gap`, copy `.env.example` to `.env`, and add your password.
3. Put the raw files in `data/raw/`: `netflix_titles.csv` from [Kaggle](https://www.kaggle.com/datasets/shivamb/netflix-shows), plus `title.basics.tsv` and `title.ratings.tsv` from [IMDb datasets](https://datasets.imdbws.com/). Then run `notebooks/02_clean.ipynb`.
4. Run the pipeline:
   ```powershell
   python scripts/01_filter_imdb.py; python scripts/02_load_postgres.py; python scripts/03_run_match.py; python scripts/04_build_marts.py
   ```

IMDb data is licensed for non-commercial use, so nothing under `data/` is committed. Only aggregate tables go to `dashboard/data/`.
