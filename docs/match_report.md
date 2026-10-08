# Match report — Netflix to IMDb

Generated 2026-10-08 by `scripts/03_run_match.py` from `sql/03_match.sql`.
Tiers built: T1 `exact`, T2 `year_pm1`. T3 `fuzzy` is not built. Rules: PRD section 6.
Audit precision per tier: see the Audit precision section.

## Checks

- [PASS] title_match rows = 8,807 (got 8,807)
- [PASS] one row per show_id (8,807 distinct)
- [PASS] no Netflix title without a row (got 0)
- [PASS] tier counts add up to 8,807 (got 8,807)
- [PASS] no match made on an empty title_norm (got 0)
- [PASS] every match satisfies name + type + year rule of its tier (violations: 0)
- [PASS] no fuzzy tier rows (T3 not built)

## Audit precision

Recorded 2026-10-08 by `python scripts/03_audit.py summary --use-ai-for-blank --record`.
Sample: up to 30 matches per tier, seed 42. Mode: blank `correct` rows count as their `ai_label`. Precision = y / (y + n); `unsure` and blank rows are left out.

| tier | sampled | human-labelled | AI-labelled | unsure | blank | precision |
|---|---|---|---|---|---|---|
| exact | 30 | 7 | 23 | 0 | 0 | 100.0% = 30/30 (meets 90%) |
| year_pm1 | 30 | 5 | 25 | 0 | 0 | 96.7% = 29/30 (meets 90%) |

AI-assisted audit (PRD section 10): the human checked every AI `n` / `unsure` row and 10 random AI `y` rows.
- AI label vs human answer, where both are y/n: 10/10 agree.
- AI `unsure` rows resolved by the human: s630 -> n, s4041 -> y.

## Tiers, overall (8,807 Netflix titles)

| tier | titles | % of all titles |
|---|---|---|
| exact | 7,150 | 81.2% |
| year_pm1 | 342 | 3.9% |
| unmatched | 1,315 | 14.9% |
| **matched (exact + year_pm1)** | **7,492** | **85.1%** |
| total | 8,807 | 100.0% |

## Tiers by type

| type | titles | exact | year_pm1 | unmatched | match rate |
|---|---|---|---|---|---|
| Movie | 6,131 | 4,920 (80.2%) | 299 (4.9%) | 912 (14.9%) | 85.1% |
| TV Show | 2,676 | 2,230 (83.3%) | 43 (1.6%) | 403 (15.1%) | 84.9% |

## Match rate by country

Ten biggest countries by Netflix title count, plus Indonesia and Unknown (no country listed).
A title counts once in each of its countries.

| country | titles | exact | year_pm1 | unmatched | match rate |
|---|---|---|---|---|---|
| United States | 3,690 | 3,166 | 118 | 406 | 89.0% |
| India | 1,046 | 896 | 49 | 101 | 90.3% |
| United Kingdom | 806 | 676 | 36 | 94 | 88.3% |
| Canada | 445 | 376 | 19 | 50 | 88.8% |
| France | 393 | 340 | 22 | 31 | 92.1% |
| Japan | 318 | 255 | 6 | 57 | 82.1% |
| Spain | 232 | 179 | 20 | 33 | 85.8% |
| South Korea | 231 | 197 | 5 | 29 | 87.4% |
| Germany | 226 | 198 | 7 | 21 | 90.7% |
| Mexico | 169 | 136 | 13 | 20 | 88.2% |
| Indonesia | 90 | 76 | 3 | 11 | 87.8% |
| Unknown | 831 | 429 | 30 | 372 | 55.2% |

## Match rate by year added

| year_added | titles | matched | match rate |
|---|---|---|---|
| 2008 | 2 | 0 | 0.0% |
| 2009 | 2 | 1 | 50.0% |
| 2010 | 1 | 0 | 0.0% |
| 2011 | 13 | 9 | 69.2% |
| 2012 | 3 | 2 | 66.7% |
| 2013 | 11 | 8 | 72.7% |
| 2014 | 24 | 18 | 75.0% |
| 2015 | 82 | 67 | 81.7% |
| 2016 | 429 | 348 | 81.1% |
| 2017 | 1,188 | 974 | 82.0% |
| 2018 | 1,649 | 1,367 | 82.9% |
| 2019 | 2,016 | 1,748 | 86.7% |
| 2020 | 1,879 | 1,660 | 88.3% |
| 2021 | 1,498 | 1,281 | 85.5% |
| missing | 10 | 9 | 90.0% |

## IMDb titles matched by more than one Netflix title

7 tconst are matched by more than one Netflix title (14 Netflix titles in total).

| tconst | IMDb title | start_year | Netflix titles | which |
|---|---|---|---|---|
| tt0089108 | Waiting for the Hearse | 1985 | 2 | Esperando la carroza (s304, Movie, 1985); Esperando La Carroza (s6706, Movie, 1985) |
| tt0366621 | InuYasha the Movie 2: The Castle Beyond the Looking Glass | 2002 | 2 | InuYasha the Movie 2: The Castle Beyond the Looking Glass (s52, Movie, 2002); InuYasha: The Movie 2: The Castle Beyond the Looking Glass (s7091, Movie, 2002) |
| tt1602479 | Love in a Puff | 2010 | 2 | Love in a Puff (s160, Movie, 2010); Love In A Puff (s7346, Movie, 2010) |
| tt3176134 | Consequences | 2014 | 2 | Consequences (s3372, Movie, 2014); Consequences (s6530, Movie, 2014) |
| tt5676412 | Sin Senos Sí Hay Paraíso | 2016 | 2 | Sin senos sí hay paraíso (s1271, TV Show, 2018); Sin Senos sí Hay Paraíso (s8023, TV Show, 2018) |
| tt5862312 | Veronica | 2017 | 2 | Veronica (s5026, Movie, 2017); Verónica (s5250, Movie, 2017) |
| tt8860450 | What/If | 2019 | 2 | WHAT / IF (s3802, TV Show, 2019); What If? (s3857, TV Show, 2019) |

## Ambiguous matches

283 matches had more than one candidate passing the tier's rules; the one with the most votes was kept.

| tier | ambiguous | matched | % ambiguous | max candidates |
|---|---|---|---|---|
| exact | 270 | 7,150 | 3.8% | 6 |
| year_pm1 | 13 | 342 | 3.8% | 4 |

## Unmatched near misses (diagnostic, no rule applied)

Unmatched titles whose normalized name exists in IMDb with a compatible type, but outside the T2 year window.
Year distance for TV shows is measured to the IMDb startYear-endYear span.

| type | unmatched | same name + type in IMDb | nearest year off by 2 | off by 3-5 | off by 6+ |
|---|---|---|---|---|---|
| Movie | 912 | 104 | 41 | 23 | 40 |
| TV Show | 403 | 45 | 14 | 9 | 22 |

## 30 random unmatched titles (seed 42)

| show_id | title | release_year | type | country |
|---|---|---|---|---|
| s68 | Saved by the Bell | 1994 | TV Show | United States |
| s306 | Tango Feroz | 1993 | Movie | Argentina, Spain |
| s389 | Plastic Cup Boyz: Laughing My Mask Off! | 2021 | TV Show | Unknown |
| s653 | Osuofia in London II | 2004 | Movie | Unknown |
| s851 | 99 Songs | 2021 | Movie | India |
| s977 | Among Family | 2017 | Movie | Turkey |
| s1055 | Wave of Cinema: One Day We'll Talk About Today | 2020 | Movie | Unknown |
| s1277 | M8 - When Death Rescues Life | 2019 | Movie | Unknown |
| s1290 | Wave of Cinema: Surat dari Timur | 2020 | Movie | Unknown |
| s1380 | Black Rose | 2018 | Movie | Nigeria |
| s1412 | What Would Sophia Loren Do? | 2021 | Movie | United States |
| s2264 | PNL - Dans la légende tour | 2020 | Movie | Unknown |
| s2404 | Menahi | 2008 | Movie | Saudi Arabia |
| s2564 | Luccas Neto em: Acampamento de Férias 2 | 2020 | Movie | Brazil |
| s2642 | DreamWorks Spooky Stories: Volume 2 | 2011 | TV Show | Unknown |
| s3367 | Little Miss Sumo | 2018 | Movie | United Kingdom |
| s4197 | La Grande Chaumière Violette | 2016 | TV Show | Taiwan |
| s4231 | Bill Hicks: Reflections | 2015 | Movie | Unknown |
| s4241 | Sam Kinison: The Scream Continues | 2016 | Movie | United States |
| s4302 | Once in a Lifetime Sessions with Snow Patrol | 2018 | Movie | United States |
| s4512 | Edgar Rice Burroughs' Tarzan and Jane | 2018 | TV Show | Unknown |
| s4893 | Pocoyo & Cars | 2015 | Movie | Unknown |
| s4901 | Spiritual House | 2017 | TV Show | Unknown |
| s6515 | Cold Case Files Classic | 1999 | TV Show | United States |
| s6536 | Cop Watchers | 2016 | Movie | Unknown |
| s7459 | Minnaminugu the FireFly | 2017 | Movie | India |
| s7782 | Power Rangers Super Samurai: Trickster Treat | 2012 | Movie | United States |
| s7971 | Secrets of Althorp - The Spencers | 2013 | Movie | United States |
| s8332 | The Great British Baking Show: Masterclass | 2018 | TV Show | United Kingdom |
| s8348 | The Homecoming | 2015 | TV Show | Unknown |
