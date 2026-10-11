-- Phase 4 sensitivity of the genre Quality index (IMPLEMENTATION_GUIDE section 6).
-- Runs after sql/04_marts.sql and reuses mart.qi_counts, so every scenario uses the same SQL.
-- Scenarios: baseline (thresholds from mart.params, 7.0 / 1,000 by default), lenient 6.5 / 500,
-- strict 7.5 / 5,000, and baseline_no_ambiguous (baseline thresholds, matches with more than
-- one candidate excluded). rank 1 = highest index, among genres that are not small_n in that scenario.

DROP TABLE IF EXISTS mart.sensitivity_genre;

CREATE TABLE mart.sensitivity_genre AS
WITH p AS (SELECT * FROM mart.params),
scenario AS (
    SELECT * FROM (VALUES
        (1, 'baseline',              (SELECT min_rating FROM p), (SELECT min_votes FROM p), false),
        (2, 'lenient',               6.5::numeric,               500,                       false),
        (3, 'strict',                7.5::numeric,               5000,                      false),
        (4, 'baseline_no_ambiguous', (SELECT min_rating FROM p), (SELECT min_votes FROM p), true)
    ) AS s (scenario_order, scenario, min_rating, min_votes, exclude_ambiguous)
),
c AS (
    SELECT s.scenario_order, s.scenario, s.min_rating, s.min_votes, s.exclude_ambiguous, q.*
    FROM scenario s
    CROSS JOIN LATERAL mart.qi_counts(s.min_rating, s.min_votes, s.exclude_ambiguous) q
),
overall AS (
    SELECT scenario, n_high::numeric / n_matched AS rate FROM c WHERE dimension = 'catalog'
),
g AS (
    SELECT c.scenario_order, c.scenario, c.min_rating, c.min_votes, c.exclude_ambiguous,
           c.segment AS genre, c.n_matched, c.n_high,
           c.n_high::numeric / nullif(c.n_matched, 0) / o.rate AS quality_index,
           c.n_matched < p.min_n AS small_n
    FROM c JOIN overall o USING (scenario) CROSS JOIN p
    WHERE c.dimension = 'genre'
)
SELECT scenario_order, scenario, min_rating, min_votes, exclude_ambiguous,
       genre, n_matched, n_high,
       round(quality_index, 4) AS quality_index,
       small_n,
       CASE WHEN small_n THEN NULL
            ELSE row_number() OVER (PARTITION BY scenario, small_n
                                    ORDER BY quality_index DESC, n_matched DESC, genre) END AS rank
FROM g
ORDER BY scenario_order, genre;
