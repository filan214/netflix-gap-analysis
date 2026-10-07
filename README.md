# Netflix Catalog Gap Analysis (Global + Indonesia)

Where does Netflix's catalog deliver audience-rated quality, where is it thin compared with what exists in the world, and how does Indonesian content compare? Scope and definitions: [`PRD.md`](PRD.md). Build spec: [`IMPLEMENTATION_GUIDE.md`](IMPLEMENTATION_GUIDE.md).

## Data

Nothing under `data/` is committed. IMDb data is licensed for non-commercial use only, so raw and title-level IMDb data stay local.

| File | Source | How to get it |
|---|---|---|
| `data/raw/netflix_titles.csv` | Kaggle [`shivamb/netflix-shows`](https://www.kaggle.com/datasets/shivamb/netflix-shows) (8,807 titles, through 2021) | Download and place as is |
| `data/raw/title.basics*.tsv` | [datasets.imdbws.com](https://datasets.imdbws.com/) `title.basics.tsv.gz` | Download and unzip |
| `data/raw/title.ratings*.tsv` | [datasets.imdbws.com](https://datasets.imdbws.com/) `title.ratings.tsv.gz` | Download and unzip |

The IMDb download date used for this analysis is in `docs/imdb_download_date.txt`. `data/raw/` is never modified.

Derived files in `data/clean/`:

| File | Built by | Rows |
|---|---|---|
| `netflix_titles_clean.csv` | `notebooks/02_clean.ipynb` | 8,807 |
| `title_country.csv` | `notebooks/02_clean.ipynb` | 10,843 |
| `title_genre.csv` | `notebooks/02_clean.ipynb` | 19,323 |
| `imdb_filtered.csv` | `scripts/01_filter_imdb.py` | 556,239 |

`imdb_filtered.csv` keeps title types `movie`, `tvMovie`, `tvSpecial`, `tvSeries`, `tvMiniSeries`, with `isAdult = 0`, a known `startYear`, and a rating row. Rating and vote thresholds are applied later from `mart.params`, not here.

PostgreSQL schemas (built by `scripts/02_load_postgres.py`):

| Schema | Tables |
|---|---|
| `netflix` | `titles`, `title_country`, `title_genre`, `title_match` (filled in Phase 3) |
| `imdb` | `titles`, `title_names` (normalized primary + original titles), `title_genres` |
| `mart` | `params` (single row of analysis thresholds); analysis marts arrive in Phase 4 |

## Setup

Requires Python 3.13 and PostgreSQL 14+ (built on 18) with the `pg_trgm` extension available (ships with the standard installer). Run every command from the repo root in PowerShell.

1. Create and activate a virtual environment, then install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Create the database (asks for the `postgres` password):
   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres netflix_gap
   ```
3. Copy `.env.example` to `.env` and put your password in `DATABASE_URL`. `.env` is gitignored.
   ```powershell
   Copy-Item .env.example .env
   ```
4. Put the raw files in `data/raw/` (see Data), then run `notebooks/02_clean.ipynb` to build the Netflix files in `data/clean/`.
5. Filter IMDb (about 1 minute):
   ```powershell
   python scripts/01_filter_imdb.py
   ```
6. Load PostgreSQL (about 1 minute). This drops and recreates schemas `netflix` and `imdb`, so re-run Phases 3 and 4 after any reload:
   ```powershell
   python scripts/02_load_postgres.py
   ```
   The loader prints row counts and the Phase 2 checks, and exits with code 1 if any check fails.
7. Run the tests:
   ```powershell
   python -m pytest
   ```
