# IMPLEMENTATION_GUIDE — Netflix Catalog Gap Analysis

> Companion to `PRD.md`. Build spec for Phases 2-4: architecture, contracts, table definitions, the matching algorithm, the analysis marts, and verification checkpoints. Phases 0-1 are already done (`notebooks/01_profile.ipynb`, `notebooks/02_clean.ipynb`).

**Claude Code prompt prefix (use every session):**
> Read PRD.md and IMPLEMENTATION_GUIDE.md first, then complete the following task:

---

## 0. Architecture at a glance

```
data/clean/netflix_titles_clean.csv ─┐
data/clean/title_country.csv        ─┼─► scripts/02_load_postgres.py ─► schema netflix
data/clean/title_genre.csv          ─┘
data/clean/imdb_filtered.csv ─────────► scripts/02_load_postgres.py ─► schema imdb

netflix.titles + imdb.title_names ─► sql/03_match*.sql ─► netflix.title_match
netflix.* + imdb.* + title_match  ─► sql/04_*.sql      ─► schema mart (analysis tables)
mart.*                            ─► scripts/04_build_marts.py ─► dashboard/data/*.csv ─► Power BI (Phase 5)
```

- Local PostgreSQL (16 or 17; `string_to_table` needs 14+). Extension `pg_trgm` only matters if tier T3 gets built.
- Three schemas: `netflix` (cleaned source), `imdb` (filtered source), `mart` (analysis outputs).
- Python only loads data and runs SQL files. The matching and analysis logic lives in SQL.

## 1. Repo layout (new items marked +)

```
netflix-gap-analysis/
  PRD.md  IMPLEMENTATION_GUIDE.md  CLAUDE_CODE_PROMPTS.md  README.md   +
  .env  (gitignored)   .env.example   +
  data/raw, data/clean            # gitignored
  notebooks/01_profile.ipynb  02_clean.ipynb
  scripts/
    01_filter_imdb.py
    lib/normalize.py   +
    02_load_postgres.py   +
    03_run_match.py  03_audit.py   +
    04_build_marts.py   +
  sql/
    01_schema.sql  02_indexes.sql   +
    03_match.sql   +
    04_marts.sql  04_sensitivity.sql   +
  tests/test_normalize.py   +
  dashboard/data/             # aggregate mart CSVs only   +
  docs/  profile_before.json  profile_after.json  imdb_download_date.txt
         match_report.md  match_audit_sample.csv   +
```

## 2. Environment

- Dependencies to add: `psycopg[binary]`, `python-dotenv`, `pytest` (pandas is already installed). Re-run `pip freeze > requirements.txt` after installing.
- `.env`: `DATABASE_URL=postgresql://postgres:<password>@localhost:5432/netflix_gap`. Commit `.env.example` with a placeholder, never `.env`.
- All commands must be single-line and PowerShell-safe (no backslash continuations).
- Scripts run from the repo root: `python scripts/02_load_postgres.py`.
- Every script is idempotent: running it twice gives the same result.
- Never modify `data/raw/`. Never commit `data/` or `.env`.

## 3. Contracts

### 3.1 Title normalization (`scripts/lib/normalize.py`) — deterministic, a contract
`normalize_title(s) -> str`:
1. Unicode NFKD, then drop combining marks (so `é` becomes `e`).
2. Casefold.
3. Replace `&` with ` and `.
4. Replace every character that is not a Unicode letter or digit with a space.
5. Collapse whitespace and strip.
- Do **not** drop leading articles ("the", "a") in v1.
- A result of `''` is allowed to exist but must **never** be joined on. Titles in non-Latin scripts can normalize to a non-empty string; only fully symbolic titles become empty.
- The same function builds `netflix.titles.title_norm` and `imdb.title_names.name_norm`. Tests in `tests/test_normalize.py` cover accents, ampersand, punctuation, digits, non-Latin text, and an all-symbol title.

### 3.2 Type mapping
| Netflix `type` | IMDb `titleType` |
|---|---|
| Movie | `movie`, `tvMovie`, `tvSpecial` |
| TV Show | `tvSeries`, `tvMiniSeries` |

### 3.3 Tables (`sql/01_schema.sql`)

```
netflix.titles
  show_id text PK, type text NOT NULL CHECK (type IN ('Movie','TV Show')),
  title text NOT NULL, title_norm text NOT NULL,
  director text, cast_members text,            -- CSV column "cast" is a reserved word: rename on load
  country text, date_added date, release_year int NOT NULL,
  rating text NOT NULL, duration text NOT NULL, listed_in text NOT NULL, description text,
  duration_min int, seasons int, rating_group text NOT NULL, year_added int,
  added_before_release boolean NOT NULL, country_known boolean NOT NULL
netflix.title_country (show_id FK -> titles, country text, PK(show_id, country))
netflix.title_genre   (show_id FK -> titles, genre text,   PK(show_id, genre))
netflix.title_match
  show_id text PK FK -> titles, tconst text NULL FK -> imdb.titles,
  match_tier text NOT NULL CHECK (match_tier IN ('exact','year_pm1','fuzzy','unmatched')),
  candidate_count int NOT NULL, ambiguous boolean NOT NULL, similarity numeric NULL

imdb.titles
  tconst text PK, title_type text, primary_title text, original_title text,
  start_year int NOT NULL, end_year int NULL, runtime_min int NULL, genres text NULL,
  avg_rating numeric(3,1) NOT NULL, num_votes int NOT NULL
imdb.title_names  (tconst FK -> titles, name_norm text, PK(tconst, name_norm))   -- primary + original, deduped, no empty keys
imdb.title_genres (tconst FK -> titles, genre text, PK(tconst, genre))            -- exploded from genres

mart.params (single row)
  min_rating numeric = 7.0, min_votes int = 1000, min_n int = 30,
  universe_start_year int = 2000, accepted_tiers text[] = '{exact,year_pm1}'
```

`sql/02_indexes.sql`: `imdb.title_names(name_norm)`, `imdb.titles(start_year, title_type)`, `imdb.title_genres(genre)`, `netflix.title_country(country)`, `netflix.title_genre(genre)`, and a GIN trigram index on `imdb.title_names(name_norm)` for T3. Create indexes after bulk load, then `ANALYZE`.

---

## 4. Phase 2 — Model in PostgreSQL (0.5-1 day)

**Build**
0. Add `endYear` to `usecols` in `scripts/01_filter_imdb.py` and re-run it so `imdb_filtered.csv` has `endYear`.
1. `scripts/lib/normalize.py` + tests.
2. `sql/01_schema.sql`, `sql/02_indexes.sql`.
3. `scripts/02_load_postgres.py`: read `.env`; drop and recreate schemas `netflix` and `imdb` (derived data, safe to wipe; `mart` is rebuilt by Phase 4); bulk-load with `COPY` through psycopg; compute `title_norm`, `title_names`, `title_genres`; create indexes; `ANALYZE`; print row counts.

**Note:** reloading wipes `netflix.title_match`. After any reload, re-run Phase 3 and Phase 4.
**Note:** if `COUNTRY_FIX` is changed in `02_clean.ipynb`, re-run its Cells 7-9, then re-run the loader.

**Done when:** the P2 checks in section 7 pass, and a second run of the loader gives identical counts.

## 5. Phase 3 — Match Netflix to IMDb (about 1 day + 20-30 min manual audit)

**Build T1 and T2 first, print the report, and stop.** T3 is conditional (see below).

**Algorithm** (`sql/03_match.sql`, driven by `scripts/03_run_match.py`). Seed `title_match` empty, then fill tier by tier; each tier only considers Netflix titles not yet matched. For each tier, build candidates, rank them, keep rank 1:

```sql
-- shape of one tier (T1 shown; type and year rules per PRD section 6)
SELECT n.show_id, i.tconst, i.num_votes,
       count(*)     OVER (PARTITION BY n.show_id) AS candidate_count,
       row_number() OVER (PARTITION BY n.show_id ORDER BY i.num_votes DESC, i.tconst) AS rn
FROM netflix.titles n
JOIN imdb.title_names nm ON nm.name_norm = n.title_norm AND n.title_norm <> ''
JOIN imdb.titles i       ON i.tconst = nm.tconst
WHERE <type compatible per 3.2>
  AND <year rule>
  AND n.show_id NOT IN (SELECT show_id FROM netflix.title_match)
```

Year rules:
| | T1 `exact` | T2 `year_pm1` |
|---|---|---|
| Movie | `i.start_year = n.release_year` | `abs(i.start_year - n.release_year) <= 1` |
| TV Show | `n.release_year BETWEEN i.start_year AND COALESCE(i.end_year, 9999)` | `n.release_year BETWEEN i.start_year - 1 AND COALESCE(i.end_year, 9999) + 1` |

After T2, insert an `unmatched` row (tconst NULL, candidate_count 0) for every remaining Netflix title, so `title_match` has exactly one row per title.

**T3 `fuzzy` — conditional, do not build unless asked.** Build it only if the match rate after T1+T2 is below 85% and the unmatched sample (below) shows near-misses. If built: `n.title_norm % nm.name_norm`, `pg_trgm.similarity_threshold = 0.85`, `length(n.title_norm) >= 5`, T2 year rule, rank by similarity then votes, store `similarity`, add the GIN trigram index. If skipped, say so in the README Method section.

**Match report** printed by `03_run_match.py` and saved to `docs/match_report.md`:
- Counts and percentages per tier, overall and by `type`.
- Match rate for the 10 biggest countries, Indonesia, and `Unknown`. This is the bias check: where do unmatched titles concentrate?
- Number of `tconst` matched by more than one Netflix title, and number of `ambiguous` matches.
- 30 random unmatched titles (title, year, type, country), to judge whether T3 is needed.

**Audit** (`scripts/03_audit.py`, two modes, fixed random seed)
- `export`: writes `docs/match_audit_sample.csv` with up to 30 random rows per built tier: `show_id`, Netflix title / year / type / country, IMDb title / year / type, `tconst`, IMDb URL (`https://www.imdb.com/title/<tconst>/`), `tier`, and an empty `correct` column. The user fills `correct` with `y` or `n`.
- `summary`: reads the filled file and prints precision per tier. It changes nothing. If a tier is below 90%, edit `mart.params.accepted_tiers` by hand and log it in PRD section 10.

**Done when:** the P3 checks in section 7 pass and the audit precision per tier is recorded in `docs/match_report.md`.

## 6. Phase 4 — Analysis marts in SQL (about 1 day)

All marts read thresholds from `mart.params`, use accepted tiers only, and are built by one script, `scripts/04_build_marts.py`, which runs the SQL, exports the CSVs and prints a summary. Segment-level tables carry `n_matched` and `small_n`.

| Mart | Grain | Key columns |
|---|---|---|
| `mart.catalog_summary` | one row | titles, matched, match_rate, high_rated_n, overall_high_rate |
| `mart.quality_index` | dimension (`genre`, `country`, `rating_group`) x segment | n_matched, n_high, high_rate, quality_index, share_of_catalog, small_n, quadrant |
| `mart.coverage_gap_genre` | IMDb genre x type group (movie / series) | netflix_high_n, netflix_high_share, world_high_n, world_high_share, coverage_gap, n_matched, small_n |
| `mart.country_votes_context` | country (n_matched >= `min_n`, Unknown included) | n_matched, matched_titles, total_titles, match_rate, median_votes, pct_titles_over_1000_votes, pct_rated_at_or_above_min_rating, visibility_penalty, quality_index |
| `mart.growth_by_year_added` | year_added x type | total_titles, matched_titles, indonesia_total_titles, indonesia_matched_titles. Full catalog, matched or not (null `year_added` excluded) |
| `mart.indonesia_vs_global` | dimension (`genre`, `rating_group`) x segment | indonesia_n, indonesia_pct, global_n, global_pct |
| `mart.sensitivity_genre` | scenario x genre | quality_index, rank |

Implementation notes:
- Bridge-table counts use `COUNT(DISTINCT show_id)` inside each segment. The whole-catalog rate uses distinct matched titles, not bridge rows.
- **Sensitivity: 3 scenarios only** (baseline 7.0 / 1,000 votes, lenient 6.5 / 500, strict 7.5 / 5,000), genre dimension only. Report how many of the baseline's top 5 and bottom 5 genres stay in the top 5 and bottom 5 in each scenario. No full grid, no rank-correlation statistics.
- Export aggregate marts to `dashboard/data/<mart>.csv`. Nothing title-level goes to a committed folder.
- The script prints (no results file): the analysis-population size, the top and bottom 5 segments per dimension with their n, and the sensitivity overlap counts. That output feeds the Phase 6 memo.

**Done when:** the P4 checks in section 7 pass.

---

## 7. Verification checkpoints (evidence, not assumption)

**P2** (done)
- `netflix.titles` = 8,807 rows. Bridge tables match their CSVs. Indonesia rows in `title_country` = 90 (or the new number if `COUNTRY_FIX` changed).
- `imdb.titles` row count = data rows in `imdb_filtered.csv`. `imdb.title_names` has zero empty `name_norm` values.
- Loader run twice gives identical counts. `python -m pytest` passes.

**P3**
- `title_match` has exactly 8,807 rows, one per `show_id`. Tier counts add up to 8,807.
- Report shows match rate by type, tier and country (including Indonesia), plus the 30-title unmatched sample.
- Five known titles checked by hand against IMDb.
- Audit file exported; precision per tier computed after the manual pass.

**P4**
- Quality index of the whole catalog recomputed independently equals 1.0 (assert in the script).
- One segment recounted with a hand-written query matches the mart.
- No segment below `min_n` appears in a ranking without `small_n` set.
- The analysis uses accepted tiers only, and the number of matched titles in the analysis population is printed.

## 8. Handoff to Phase 5 (Power BI, manual)
- Data: `dashboard/data/*.csv` (or connect Power BI to local PostgreSQL schema `mart`).
- Pages: 1) global (quality index, quadrant, coverage gap), 2) Indonesia (descriptive, n on every chart), 3) method and limitations (match rate, audit precision, PRD section 7).

## 9. Guardrails carried from the PRD
- Definitions in PRD section 5 are a contract. A change needs a deviation-log entry.
- Unmatched titles are reported, never silently dropped.
- Every number shown with its n. No indices for Indonesia genre slices.
- IMDb data is never committed. Only aggregate marts go to Git.
- Log any divergence between spec and implementation in PRD section 10.
