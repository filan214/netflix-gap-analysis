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

## Method

### Matching Netflix to IMDb (Phase 3)

The two sources share no ID, so titles are matched on normalized name + year + type (`sql/03_match.sql`, run by `scripts/03_run_match.py`). Full rules: PRD section 6.

1. **Normalize names.** `scripts/lib/normalize.py` folds accents, casefolds, turns `&` into `and`, and replaces punctuation with spaces. The same function builds the Netflix `title_norm` and the IMDb `name_norm` (primary and original titles). Empty names are never joined on.
2. **Match in tiers.** Each tier only looks at titles still unmatched:
   - **T1 `exact`**: same normalized name, compatible type (`Movie` ↔ `movie`/`tvMovie`/`tvSpecial`, `TV Show` ↔ `tvSeries`/`tvMiniSeries`), and the exact year rule. For movies, release year = IMDb start year. For TV shows, the Netflix release year falls inside the IMDb start-end span, which stays open if the show is ongoing.
   - **T2 `year_pm1`**: the same rule, with the year widened by 1.
   - **T3 `fuzzy`** (trigram similarity) is **not built**. The PRD builds it only if T1+T2 leave the match rate below 85% *and* the unmatched titles look like near-misses rather than titles missing from IMDb. T1+T2 reach 85.1%, just above that line, so the decision waits for the audit.
3. **Break ties.** When several IMDb titles qualify, the one with the most votes wins. `candidate_count` and `ambiguous` record that it happened.
4. **Never drop titles.** Every Netflix title gets exactly one row in `netflix.title_match`. Titles that match nothing get an `unmatched` row.
5. **Report and audit.**
   - `docs/match_report.md` gives the match rate by tier, type, country (including Indonesia and Unknown) and year added. It also lists IMDb titles claimed by more than one Netflix title, ambiguous matches, near misses, and a random sample of unmatched titles.
   - `scripts/03_audit.py export` draws a reproducible sample of 30 matches per tier for checking by hand. `scripts/03_audit.py summary` prints precision per tier from the filled file.
   - A tier counts in the analysis only with precision >= 90%.

Current result: 7,492 of 8,807 titles matched (85.1%). Movies 85.1%, TV shows 84.9%. Titles with no country listed match far less often (55.2%).

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
8. Match Netflix to IMDb. This rebuilds `netflix.title_match`, writes `docs/match_report.md`, and exits with code 1 if a P3 check fails:
   ```powershell
   python scripts/03_run_match.py
   ```
9. Export the audit sample, fill `correct` with `y` or `n` in `docs/match_audit_sample.csv`, then print precision per tier:
   ```powershell
   python scripts/03_audit.py export
   ```
   ```powershell
   python scripts/03_audit.py summary
   ```
