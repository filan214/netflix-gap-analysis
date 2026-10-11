# PRD — Netflix Catalog Gap Analysis (Global + Indonesia)

> Scope and rationale. `IMPLEMENTATION_GUIDE.md` is the *how*. Phases 0-4 are done. Phase 5 (Power BI) and Phase 6 (memo) are done by hand.

## 1. Purpose
Data Analyst portfolio project. It shows: messy-data cleaning, SQL modeling, a join without a shared key, metrics defined up front with stated limits, a dashboard, and a recommendation memo. Secondary fit: general IT / data-engineering basics.

## 2. Business question
Where does Netflix's catalog deliver audience-rated quality, where is it thin compared with what exists in the world, and how does Indonesian content compare?

## 3. Scope

| Phase | Work | Status | Built by |
|---|---|---|---|
| 0 | Setup, raw profiling | Done | Manual |
| 1 | Clean Netflix, build bridge tables | Done | Manual |
| 2 | Model in PostgreSQL, load both sources | Done | Claude Code |
| 3 | Match Netflix to IMDb, audit the match | Done (T1 + T2; T3 not built) | Claude Code + manual audit |
| 4 | Analysis marts in SQL | Done | Claude Code |
| 5 | Power BI dashboard (3 pages) | | Manual |
| 6 | 1-page findings memo | | Manual |

**Out of scope:** viewership data, forecasting/ML, post-2021 catalog, a recommender, a backend or API.

## 4. Data
- **Netflix:** Kaggle `shivamb/netflix-shows`, 8,807 titles, snapshot through 2021. Cleaned in Phase 1 (`data/clean/`).
- **IMDb:** `title.basics` + `title.ratings` from datasets.imdbws.com, filtered by `scripts/01_filter_imdb.py`. Download date in `docs/imdb_download_date.txt`. Licensed for non-commercial use: raw or title-level IMDb data is never committed.
- **Facts from profiling:** 90 titles list Indonesia; 831 have no country; 10 have no `date_added`; 14 were added before their release year; 77% of titles have 2-3 genres.

## 5. Definitions (contract — do not change without a deviation-log entry)

- **Matched title:** a Netflix title linked to an IMDb title by an accepted match tier (section 6).
- **High-rated:** IMDb `averageRating` >= 7.0 AND `numVotes` >= 1,000. Stored in `mart.params`; sensitivity run at ratings 6.5 / 7.0 / 7.5 and votes 500 / 1,000 / 5,000.
- **Analysis population:** matched titles only. Unmatched titles are always reported (count and where they concentrate), never silently dropped.
- **Multi-membership:** a title counts once in *each* of its countries/genres. Segment counts therefore add up to more than the number of titles. Shares are shares of titles.
- **Quality index** (genre, country, rating group; Netflix taxonomies):
  `high-rated rate of the segment ÷ high-rated rate of all matched titles`.
  Above 1 = the segment's titles are rated better than the catalog average. Below 1 = worse.
- **Coverage gap** (genre only, IMDb genres on both sides):
  `segment's share of the world's high-rated titles ÷ segment's share of Netflix's high-rated titles`.
  Above 1 = Netflix is thin in that genre compared with the world. Below 1 = Netflix over-indexes.
  "World" = IMDb titles with startYear >= `universe_start_year` (default 2000), computed separately for the movie group and the series group.
  Country-level coverage gap is **not** built: IMDb only gives release region (via `title.akas`, very large), not production country.
- **Small-n rule:** a segment needs >= 30 matched titles to be ranked. Smaller segments are shown with a `small_n` flag and left out of rankings.
- **Quadrant label** (Quality-index segments): index >= 1.10 and share below the median share = *Scale-up candidate*; index >= 1.10 and share at or above median = *Core strength*; index <= 0.90 and share at or above median = *Volume without quality*; index <= 0.90 and share below median = *Weak and small*; otherwise *Average*.
- **Indonesia:** descriptive only. Counts and percentages side by side, with n on every chart. No quality index or coverage gap per genre.

## 6. Matching policy
No shared ID exists, so titles are matched by normalized name + year + type, in tiers. Each Netflix title gets exactly one row in `netflix.title_match` (including `unmatched`).

| Tier | Rule |
|---|---|
| T1 `exact` | Same normalized name (IMDb primary *or* original title), compatible type, exact year rule |
| T2 `year_pm1` | Same as T1 with the year rule widened by 1 |
| T3 `fuzzy` (conditional) | Trigram similarity >= 0.85, normalized length >= 5, T2 year rule, only for titles still unmatched. **Built only if** T1+T2 leave the match rate below 85% and a sample of unmatched titles shows near-misses (subtitles, punctuation) rather than titles that are simply not on IMDb |

- **Type compatibility:** Netflix `Movie` ↔ IMDb `movie`, `tvMovie`, `tvSpecial`. Netflix `TV Show` ↔ IMDb `tvSeries`, `tvMiniSeries`.
- **Year rule:** movies compare `release_year` with IMDb `startYear`. TV shows check that `release_year` falls inside the IMDb `startYear`-`endYear` span (open-ended if ongoing), because Netflix's year for a series may be a later season.
- **Ties:** pick the candidate with the most votes; store `candidate_count` and `ambiguous`.
- **Audit:** 30 random matches per built tier (all if fewer) are checked by hand. A tier is accepted into the analysis only with audit precision >= 90%.

## 7. Limitations (must appear on the dashboard limitations page and in the memo)
1. IMDb votes are a popularity proxy, not Netflix viewership.
2. IMDb ratings are from the download date, not 2021, while the Netflix snapshot ends in 2021.
3. Unmatched titles are probably concentrated in non-English and local titles. The match rate is reported by type, tier and country, including Indonesia.
4. Netflix genres and IMDb genres are different taxonomies, so Quality index uses Netflix genres and Coverage gap uses IMDb genres. They are not compared with each other.
5. Country is the production-country field Netflix lists, often several per title.
6. Indonesia has 90 titles; per-genre slices are single digits.
7. Findings are "as of the 2021 catalog".

## 8. Success criteria
- Match rate reported overall and sliced by type, tier and country (including Indonesia); audit precision stated per tier.
- Every headline number shown with its n.
- All numbers reproducible from scripts; a fresh clone plus the README Data section rebuilds everything.
- Sensitivity table shows whether top and bottom segments survive threshold changes.

## 9. Resume / portfolio bullet (fill X after Phase 3)
*"Cleaned 8,800+ Netflix titles and matched them to IMDb ratings in PostgreSQL with a tiered name-year-type matcher (X% match rate, Y% audited precision), then built quality-index and coverage-gap analyses of genre, country and maturity-rating coverage with a dedicated Indonesia view, delivered as a Power BI dashboard and findings memo."*

## 10. Deviation log

| Date | Change | Reason |
|---|---|---|
| 2026-10-08 | Original "gap index" split into Quality index + Coverage gap | The first definition compared two shares inside Netflix's catalog, so it measured quality over-index, not underrepresentation |
| 2026-10-08 | Added `rating_group` (Kids / Teen-Family / Adult / Not Rated-Unknown) | Raw ratings have segments with under 10 titles |
| 2026-10-08 | IMDb type filter widened to `tvMovie`, `tvSpecial` | Netflix "Movie" includes TV movies and stand-up specials |
| 2026-10-08 | `endYear` added to the IMDb filter | Needed for the TV-show year rule |
| 2026-10-08 | `scripts/01_filter_imdb.py` written in Phase 2. Filter: the 5 title types in section 6, `isAdult = 0`, `startYear` present, inner join with `title.ratings`. No vote or year filter (556,239 rows) | The script was not in the repo. Vote and year thresholds belong to `mart.params` so the sensitivity run can vary them; `start_year` and `avg_rating`/`num_votes` are NOT NULL in the schema |
| 2026-10-08 | `normalize_title` drops all combining-mark categories (`Mn`, `Mc`, `Me`), not only those with a combining class | Spacing vowel signs (e.g. Devanagari) would otherwise become spaces in step 4 and split one word. NFKD also turns Hangul syllables into jamo. Both sides use the same function, so joins are unaffected |
| 2026-10-08 | Schema adds CHECKs beyond the guide: allowed `title_type` and `rating_group` values, rating/vote/year ranges, `name_norm <> ''`, `(match_tier = 'unmatched') = (tconst IS NULL)`, single-row `mart.params`. `imdb.titles.title_type` and `primary_title` are NOT NULL | Catch bad loads at insert time. The data has no nulls in these columns |
| 2026-10-08 | `mart.params` is created only if missing and is not dropped by the loader | Tier decisions written after the Phase 3 audit survive a reload |
| 2026-10-08 | `ambiguous` = more than one IMDb candidate passed the tier's rules (`candidate_count > 1`) | Section 6 did not define it. 283 of 7,492 matches (3.8%) |
| 2026-10-08 | Phase 3 spec check, no rule changed. TV shows match about as well as movies (84.9% vs 85.1%), so the TV year rule does not under-match. Titles with no country match at 55.2%, against 82-92% for the 10 biggest countries. 6 of the 7 IMDb titles claimed by two Netflix titles are Netflix duplicates (the same film under 2 `show_id`s) | All three are reported in `docs/match_report.md`. The Unknown-country gap falls under limitation 3 in section 7. The duplicates come from the Phase 1 data and are left as they are |
| 2026-10-08 | Match report also shows match rate by `year_added` and an unmatched near-miss count (same name and type in IMDb, year outside the T2 window) | Extra diagnostics for the T3 decision. Neither changes a rule |
| 2026-10-08 | Phase 3 audit is AI-assisted with a human-checked subset. Claude pre-labels all 60 sampled matches (`ai_label` y / n / unsure + `ai_evidence`) from runtime agreement, genre overlap and model knowledge; IMDb pages returned HTTP 403, so no director/cast check. The human checks every `n` / `unsure` row plus 10 random `y` rows, and answers go in `correct`. Precision may count blank `correct` rows as their AI label (`summary --use-ai-for-blank`), with human vs AI label counts reported and `unsure` rows excluded | Cuts the manual pass while keeping a human check where the AI is unsure and a spot-check of its `y` labels. Section 6 says matches are "checked by hand"; this replaces a full hand check of all 60 rows. AI pre-labels (before human review): exact 30 y; year_pm1 28 y, 2 unsure, 0 n |
| 2026-10-08 | Phase 3 audit result: `exact` 100.0% (30/30; 7 human, 23 AI labels), `year_pm1` 96.7% (29/30; 5 human, 25 AI). Both tiers stay in `mart.params.accepted_tiers` (`{exact,year_pm1}`), no change. The AI agreed with the human on 10/10 spot-checked `y` rows; its 2 `unsure` rows resolved to 1 y, 1 n | Recorded in `docs/match_report.md`. A known `exact` false positive outside the sample (s3857 *What If?* -> tt8860450) shows that precision is below 100% in practice |
| 2026-10-11 | T3 `fuzzy` will not be built (final). Analysis tiers stay `{exact,year_pm1}` | T1+T2 reach 85.1%, above the 85% trigger in section 6. Only 149 of 1,315 unmatched titles have a same-name, same-type IMDb title, and most of those are 3+ years off. The 30 sampled unmatched titles are mostly specials, compilations and local titles absent from IMDb |
| 2026-10-11 | Country **Unknown** is kept in `mart.quality_index` but flagged `not_ranked`. It is left out of rankings and of the median share used for quadrant labels, and gets no quadrant | It matches at 55.2% vs 82-92% for named countries, so its matched titles are not representative |
| 2026-10-11 | Fourth sensitivity scenario: baseline thresholds (7.0 / 1,000) with the 283 ambiguous matches excluded (population 7,209). Result: top 5 kept 4/5, bottom 5 kept 5/5 | Tests whether tie-broken matches drive the genre ranking |
| 2026-10-11 | Indonesia tables use the 79 matched titles as n (11 of 90 not matched, shown in `mart.catalog_summary.indonesia_unmatched`). `mart.growth_by_year_added` also counts matched titles only, for global and Indonesia alike | Section 5 makes matched titles the analysis population. One base n for Indonesia keeps the dashboard consistent |
| 2026-10-11 | Clarifications of section 5: `share_of_catalog` = segment's share of matched titles. Median share is computed per dimension over ranked segments only. `small_n` segments get neither a rank nor a quadrant. Coverage-gap `small_n` uses all matched titles with the IMDb genre in the type group. The gap is NULL when Netflix has no high-rated title in the genre (3 movie rows, all small_n). The sensitivity baseline reads `mart.params` | Section 5 did not pin these down |
| 2026-10-11 | Finding, no rule change: low country indices mix low ratings with low IMDb visibility. Taiwan (index 0.35): 58.0% rated 7+, but only 16.1% have 1,000+ votes. Nigeria (index 0.00): 7.7% have 1,000+ votes and 12.1% are rated 7+, so both. Indonesia: median 780 votes vs 2,924 overall. (Corrects an earlier draft that put Nigeria down to the vote threshold alone) | Added to the README Limitations. It bears on limitation 1 (votes are a popularity proxy) |
| 2026-10-11 | Added `mart.country_votes_context` (exported to `dashboard/data/`): per country with >= `min_n` matched titles, `n_matched`, `median_votes`, `pct_titles_over_1000_votes`, `pct_rated_7plus_regardless_of_votes`, and `quality_index` / `qi_rank` / `not_ranked` copied from `mart.quality_index`. Accepted tiers only. Countries below `min_n` are left out rather than flagged. Unknown is included as `not_ranked` | Supports the limitations page: shows which low indices come from low IMDb visibility rather than low ratings |
| 2026-10-11 | `mart.country_votes_context`: `pct_rated_7plus_regardless_of_votes` renamed to `pct_rated_at_or_above_min_rating`. Its column comment carries the `min_rating` in force at build time (7.0), written by a `DO` block | The old name hard-coded 7, and the value comes from `mart.params` |
| 2026-10-11 | `mart.country_votes_context.visibility_penalty` = `pct_rated_at_or_above_min_rating` - `quality_index.high_rate`. A P4 check asserts it is never negative and equals that difference. Range 1.2%-48.1%; 9.4% for the whole matched catalog. Taiwan 48.1% (visibility-driven), Nigeria 12.1%, Indonesia 7.6% | Isolates how much of a country's low index comes from the vote threshold rather than from ratings |
