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
   - **T3 `fuzzy`** (trigram similarity) is **not built, and will not be built.** The PRD builds it only if T1+T2 leave the match rate below 85% *and* the unmatched titles look like near-misses. Neither holds:
     - T1+T2 reach 85.1%.
     - Only 149 of the 1,315 unmatched titles have a same-name, same-type IMDb title, and most of those are 3+ years off, which a name-similarity tier would not fix.
     - The 30 sampled unmatched titles are mostly specials, compilations and local titles that are not on IMDb at all.
3. **Break ties.** When several IMDb titles qualify, the one with the most votes wins. `candidate_count` and `ambiguous` record that it happened.
4. **Never drop titles.** Every Netflix title gets exactly one row in `netflix.title_match`. Titles that match nothing get an `unmatched` row.
5. **Report and audit.**
   - `docs/match_report.md` gives the match rate by tier, type, country (including Indonesia and Unknown) and year added. It also lists IMDb titles claimed by more than one Netflix title, ambiguous matches, near misses, and a random sample of unmatched titles.
   - `scripts/03_audit.py export` draws a reproducible sample of 30 matches per tier (seed 42). It writes them to `docs/match_audit_sample.csv` (gitignored, title-level IMDb data) with Netflix and IMDb context: director, description, genres, duration and runtime.
   - **The audit is AI-assisted, with a human-checked subset.**
     - Claude pre-labels every row in `ai_label` (y / n / unsure), with a one-line reason in `ai_evidence`. The evidence comes from movie runtime agreement (within 10% or 10 minutes), Netflix vs IMDb genre overlap, and the model's own knowledge of the title.
     - IMDb pages could not be fetched (HTTP 403), so director and cast were not compared. Thin evidence is labelled `unsure`, never `y`.
     - The human answer goes in `correct`. AI labels never write to it.
   - `scripts/03_audit.py review` prints the rows to check by hand: every `n` / `unsure` row, plus 10 random `y` rows (seed 42) as a spot-check of the AI.
   - `scripts/03_audit.py summary` prints precision per tier from human answers only. `summary --use-ai-for-blank` lets blank `correct` rows count as their `ai_label`. It shows how many labels are human and how many are AI, and leaves `unsure` rows out of precision, counted separately.
   - A tier counts in the analysis only with precision >= 90%. The precision reported in `docs/match_report.md` states how many of its labels were human-checked.

Current result: 7,492 of 8,807 titles matched (85.1%). Movies 85.1%, TV shows 84.9%. Titles with no country listed match far less often (55.2%). Audit precision is 100.0% for `exact` (30/30) and 96.7% for `year_pm1` (29/30), with 12 of the 60 labels human-checked, so both tiers are accepted.

### Analysis marts (Phase 4)

`scripts/04_build_marts.py` runs `sql/04_marts.sql` and `sql/04_sensitivity.sql` in one transaction. It then checks the result, exports every mart to `dashboard/data/<mart>.csv` and prints the summary. Definitions follow PRD section 5. Thresholds come from `mart.params`: rating >= 7.0, votes >= 1,000, small-n below 30, world from 2000, accepted tiers `exact,year_pm1`.

- **Analysis population:** the 7,492 titles matched by an accepted tier (`mart.analysis_titles`). Every mart is built on it. The 1,315 unmatched titles are counted in `catalog_summary`, and `quality_index.n_titles` shows each segment's titles before matching.
- **High-rated:** IMDb rating >= 7.0 and >= 1,000 votes.
- **Quality index** (`quality_index`; Netflix genre, country, rating group): a segment's high-rated rate ÷ the rate of all matched titles. A title counts once in each of its genres and countries (`COUNT(DISTINCT show_id)`).
  - `share_of_catalog` is the segment's share of matched titles.
  - Segments with fewer than 30 matched titles are flagged `small_n` and get no rank or quadrant.
  - Country **Unknown** is kept but flagged `not_ranked`. It matches at 55.2% against 82–92% for named countries, so its matched titles are not representative. It is left out of rankings and of the median share.
  - Quadrant labels use the median share of ranked segments within each dimension.
- **Coverage gap** (`coverage_gap_genre`; IMDb genres, movie and series groups): the genre's share of the world's high-rated titles ÷ its share of Netflix's high-rated titles. "World" means IMDb titles from 2000 on. Above 1 = Netflix is thin in that genre. The ratio is empty when Netflix has no high-rated title in the genre.
- **Indonesia** (`indonesia_vs_global`, `growth_by_year_added`): descriptive counts and percentages only. The base n is the **79 matched** Indonesian titles; the other 11 of the 90 could not be matched to IMDb (`catalog_summary.indonesia_unmatched`).
- **Sensitivity** (`sensitivity_genre`): the genre Quality index is rerun with the same SQL function (`mart.qi_counts`) in 4 scenarios: baseline 7.0 / 1,000, lenient 6.5 / 500, strict 7.5 / 5,000, and baseline without the 283 ambiguous matches. Stability = how many of the baseline's top 5 and bottom 5 genres stay there.
- **Checks** (the build rolls back if any fails):
  - accepted tiers only
  - whole-catalog index recomputed independently = 1.0
  - rating-group segments add back up to 1.0
  - a hand-written recount of genre `Dramas` matches the mart
  - nothing below 30 is ranked
  - Unknown not ranked
  - sensitivity baseline = `quality_index`
  - Indonesia base n = matched Indonesian titles

## Results

Numbers as of the 2021 catalog and the IMDb download of 2026-10-07. n = matched titles in the segment.

**Catalog:** 7,492 of 8,807 titles matched (85.1%). 2,142 of them are high-rated (28.6%).

**Quality index, Netflix genre** (39 ranked, 3 small_n)

| | Genre | n | High-rated | Index | Quadrant |
|---|---|---|---|---|---|
| Top | Classic Movies | 106 | 79 | 2.61 | Scale-up candidate |
| | Anime Series | 145 | 99 | 2.39 | Scale-up candidate |
| | TV Action & Adventure | 149 | 87 | 2.04 | Scale-up candidate |
| | Teen TV Shows | 67 | 38 | 1.98 | Scale-up candidate |
| | TV Mysteries | 94 | 53 | 1.97 | Scale-up candidate |
| Bottom | Thrillers | 537 | 83 | 0.54 | Volume without quality |
| | Romantic Movies | 576 | 85 | 0.52 | Volume without quality |
| | Children & Family Movies | 433 | 61 | 0.49 | Volume without quality |
| | Faith & Spirituality | 56 | 5 | 0.31 | Weak and small |
| | Horror Movies | 317 | 20 | 0.22 | Volume without quality |

**Quality index, country** (34 ranked, 88 small_n; Unknown not ranked: n 459, index 0.72)

| | Country | n | High-rated | Index | Quadrant |
|---|---|---|---|---|---|
| Top | Japan | 261 | 137 | 1.84 | Core strength |
| | Ireland | 42 | 22 | 1.83 | Scale-up candidate |
| | South Korea | 202 | 99 | 1.71 | Core strength |
| | United Kingdom | 712 | 277 | 1.36 | Core strength |
| | New Zealand | 32 | 11 | 1.20 | Scale-up candidate |
| Bottom | Singapore | 34 | 4 | 0.41 | Weak and small |
| | Philippines | 81 | 9 | 0.39 | Weak and small |
| | United Arab Emirates | 36 | 4 | 0.39 | Weak and small |
| | Taiwan | 81 | 8 | 0.35 | Weak and small |
| | Nigeria | 91 | 0 | 0.00 | Volume without quality |

**Quality index, rating group:**
- Not Rated / Unknown: 1.17 (n 75)
- Adult: 1.08 (n 3,592)
- Teen/Family: 0.99 (n 3,205)
- Kids: 0.59 (n 620)

**Coverage gap, IMDb genre** (above 1 = Netflix thinner than the world)
- **Movies, thinnest:**
  - War: 1.50 (n 58)
  - Thriller: 1.31 (n 651)
  - Animation: 1.19 (n 265)
  - Family: 1.15 (n 301)
  - Action: 1.09 (n 873)
- **Movies, most over-indexed:**
  - Musical: 0.63 (n 85)
  - Comedy: 0.77 (n 1,878)
  - Sci-Fi: 0.77 (n 158)
  - Biography: 0.82 (n 356)
  - Sport: 0.82 (n 157)
- **Series, thinnest:**
  - Sport: 1.18 (n 36)
  - Romance: 1.16 (n 245)
  - Thriller: 1.15 (n 114)
  - Mystery: 1.11 (n 173)
  - Biography: 1.07 (n 63)
- **Series, most over-indexed:**
  - Documentary: 0.63 (n 344)
  - Family: 0.73 (n 185)
  - Reality-TV: 0.75 (n 198)
  - Horror: 0.81 (n 82)
  - Adventure: 0.81 (n 370)

**Indonesia** (n = 79 matched of 90; 11 not matched). Share of Indonesian titles vs share of all matched titles:

| Genre | Indonesia | All matched |
|---|---|---|
| International Movies | 71 (89.9%) | 31.6% |
| Dramas | 54 (68.3%) | 29.4% |
| Romantic Movies | 24 (30.4%) | 7.7% |
| Comedies | 14 (17.7%) | 19.5% |
| Horror Movies | 10 (12.7%) | 4.2% |

**Sensitivity of the genre ranking** (how many of the baseline's top 5 / bottom 5 genres stay there)

| Scenario | Population | Top 5 kept | Bottom 5 kept | Dropped out |
|---|---|---|---|---|
| Lenient 6.5 / 500 | 7,492 | 2/5 | 5/5 | top: TV Action & Adventure, TV Mysteries, Teen TV Shows |
| Strict 7.5 / 5,000 | 7,492 | 3/5 | 4/5 | top: TV Mysteries, Teen TV Shows; bottom: Thrillers |
| Baseline, ambiguous matches excluded | 7,209 | 4/5 | 5/5 | top: TV Action & Adventure |

The bottom of the ranking is stable. Of the top 5, only Classic Movies and Anime Series hold in every scenario.

## Limitations

From PRD section 7, plus what the build showed.

1. IMDb votes are a popularity proxy, not Netflix viewership.
2. IMDb ratings are from the download date (2026-10-07), not 2021, while the Netflix snapshot ends in 2021.
3. 1,315 titles (14.9%) are unmatched and left out of the analysis. Titles with no country listed match at 55.2%, so country Unknown is shown but not ranked.
4. Netflix and IMDb genres are different taxonomies. Quality index uses Netflix genres and Coverage gap uses IMDb genres, so the two are not compared with each other.
5. Country is the production-country field Netflix lists, often several per title. A title counts in each of its countries.
6. Indonesia has 90 titles, of which 79 are matched. Per-genre slices are often single digits, so Indonesia is descriptive only, with no index.
7. Findings are "as of the 2021 catalog".
8. **The vote threshold dominates for some countries.** Nigeria's index of 0.00 comes from 0 high-rated titles in 91: only 7 of its matched titles have 1,000+ votes (median 112 votes), though 11 are rated 7.0 or higher. Indonesia's matched titles have a median of 780 votes, against 2,925 for all matched titles. Read low country indices as "low rating *or* low IMDb visibility".
9. **The top of the genre ranking depends on thresholds.** Three of the baseline's top 5 genres drop out at 6.5 / 500 (see Results).
10. The coverage gap compares all matched Netflix titles (453 of 7,492 released before 2000) with world titles from 2000 on, as PRD section 5 defines it.
11. A known `exact` false positive exists outside the audit sample (s3857 *What If?*), so match precision is somewhat below the audited 96.7–100%.

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
9. Export the audit sample, list the rows to check by hand, fill `correct` with `y` or `n` in `docs/match_audit_sample.csv`, then print precision per tier and record it in `docs/match_report.md` (re-running the matcher keeps that section):
   ```powershell
   python scripts/03_audit.py export
   ```
   ```powershell
   python scripts/03_audit.py review
   ```
   ```powershell
   python scripts/03_audit.py summary --use-ai-for-blank --record
   ```
   A fresh export has empty `ai_label` / `ai_evidence` columns. AI labels are added in a Claude Code session, and a re-export keeps them.
10. Build the analysis marts. This rebuilds the `mart` tables, runs the P4 checks (rolling back if any fails), writes `dashboard/data/*.csv` and prints the summary used in Results:
   ```powershell
   python scripts/04_build_marts.py
   ```
   `dashboard/data/` holds aggregate marts only and is committed. Nothing title-level is exported.
