# CLAUDE_CODE_PROMPTS — Netflix Catalog Gap Analysis

Prefix **every** session with:
> Read PRD.md and IMPLEMENTATION_GUIDE.md first, then complete the following task:

Run one session per phase, in order. Paste the evidence each session prints back into the architecture chat before starting the next one.

---

## Phase 2 — Model in PostgreSQL

> Phase 2: model the data in PostgreSQL. Do not build matching or analysis yet.
>
> Step 0: add `endYear` to `usecols` in `scripts/01_filter_imdb.py` and re-run it so `data/clean/imdb_filtered.csv` includes `endYear`. Print the script's summary block.
> Step 1: implement `scripts/lib/normalize.py` exactly as in IMPLEMENTATION_GUIDE section 3.1, with pytest tests in `tests/test_normalize.py` covering accents, ampersand, punctuation, digits, non-Latin text, and an all-symbol title.
> Step 2: write `sql/01_schema.sql` and `sql/02_indexes.sql` per section 3.3 (schemas `netflix`, `imdb`, `mart`; all PKs, FKs and CHECKs; `mart.params` with its single default row; `pg_trgm` extension).
> Step 3: write `scripts/02_load_postgres.py`: read `DATABASE_URL` from `.env`, drop and recreate schemas `netflix` and `imdb`, bulk-load with COPY via psycopg, rename CSV column `cast` to `cast_members`, build `title_norm`, `imdb.title_names` (primary + original title, deduped, no empty keys) and `imdb.title_genres`, create indexes after the load, run ANALYZE, print row counts.
> Add `psycopg[binary]`, `python-dotenv`, `pytest` to requirements, create `.env.example`, and make sure `.env` is in `.gitignore`.
> All shell commands single-line and PowerShell-safe. Never touch `data/raw/`. Run the section 7 P2 checks and show the evidence (row counts, second-run counts, pytest output). At the end update the README (Data and Setup sections) and log any deviation in PRD section 10. Do not commit `data/` or `.env`.

---

## Phase 3 — Match Netflix to IMDb

> Phase 3: implement tiers T1 (exact) and T2 (year_pm1) of the matcher from IMPLEMENTATION_GUIDE section 5, in `sql/03_match.sql`, driven by `scripts/03_run_match.py`. Do NOT build T3 (fuzzy). Stop after the report.
>
> Use the year rules and type mapping exactly as specified. Every Netflix title must end with exactly one `netflix.title_match` row (unmatched titles get an `unmatched` row). Never join on an empty normalized title.
> `03_run_match.py` must print and save `docs/match_report.md` with: counts and percentages per tier, overall and by type; match rate for the 10 biggest countries, Indonesia, and Unknown; number of `tconst` matched by more than one Netflix title; number of ambiguous matches; 30 random unmatched titles (title, year, type, country).
> Write `scripts/03_audit.py` with two modes: `export` (fixed random seed, up to 30 rows per built tier, the columns listed in section 5, empty `correct` column) and `summary` (reads the filled file, prints precision per tier, changes nothing).
> Do not build analysis marts. Run the section 7 P3 checks and show the evidence. If a tier's behaviour contradicts the spec (for example TV shows matching far less than movies), report it and log it in PRD section 10 instead of silently changing rules. Update the README Method section. Do not commit `data/` or `.env`.

**Manual step after this session (20-30 min):** open `docs/match_audit_sample.csv`, check each row against IMDb, fill `correct` with `y` or `n`, then run `python scripts/03_audit.py summary`. Paste `docs/match_report.md` and the precision numbers into the architecture chat. That decides whether T3 is worth building.

---

## Phase 4 — Analysis marts

> Phase 4: build the six marts from IMPLEMENTATION_GUIDE section 6 in SQL (`sql/04_marts.sql`, `sql/04_sensitivity.sql`), driven by ONE script, `scripts/04_build_marts.py`, which runs the SQL, exports the CSVs and prints the summary.
>
> Use the definitions in PRD section 5 exactly (high-rated, Quality index, Coverage gap, small-n rule, quadrant labels, Indonesia descriptive-only). Read thresholds from `mart.params` and use accepted tiers only. Use `COUNT(DISTINCT show_id)` for bridge-table counts. Assert that the whole-catalog Quality index equals 1.0.
> Sensitivity: 3 scenarios only (7.0/1000, 6.5/500, 7.5/5000), genre dimension only; report how many baseline top-5 and bottom-5 genres stay in the top 5 and bottom 5.
> Export aggregate marts to `dashboard/data/` as CSV; export nothing title-level to a committed folder. Do not create a results file; print the analysis-population size, top and bottom 5 segments per dimension with their n, and the sensitivity overlap.
> Run the section 7 P4 checks and show the evidence, including one hand-written recount query. Update the README (Method, Limitations, Results sections) and log any deviation in PRD section 10. Do not commit `data/` or `.env`.

---

## After Phase 4
Phase 5 (Power BI) is manual: build from `dashboard/data/*.csv` using the page plan in IMPLEMENTATION_GUIDE section 8. Bring the numbers back to the architecture chat for the Phase 6 memo.
