-- Phase 4 analysis marts (IMPLEMENTATION_GUIDE section 6, definitions in PRD section 5).
-- Run by scripts/04_build_marts.py in one transaction, followed by sql/04_sensitivity.sql.
-- Thresholds come from mart.params. Every rating-based mart is built on the analysis population:
-- Netflix titles matched by a tier in mart.params.accepted_tiers. Unmatched titles are
-- counted in mart.catalog_summary, as n_titles in mart.quality_index, as total_titles in
-- mart.country_votes_context, and in mart.growth_by_year_added, which counts the full catalog.

DROP TABLE IF EXISTS mart.catalog_summary, mart.quality_index, mart.country_votes_context, mart.coverage_gap_genre,
                     mart.growth_by_year_added, mart.indonesia_vs_global, mart.sensitivity_genre;
DROP FUNCTION IF EXISTS mart.qi_counts(numeric, int, boolean);
DROP VIEW IF EXISTS mart.analysis_titles;

-- ------------------------------------------------------------------ analysis population
CREATE VIEW mart.analysis_titles AS
SELECT n.show_id, n.type, n.rating_group, n.year_added, m.match_tier, m.ambiguous,
       i.tconst, i.title_type, i.avg_rating, i.num_votes
FROM netflix.titles n
JOIN netflix.title_match m USING (show_id)
JOIN imdb.titles i USING (tconst)
WHERE EXISTS (SELECT 1 FROM mart.params p WHERE m.match_tier = ANY (p.accepted_tiers));

COMMENT ON VIEW mart.analysis_titles IS
    'Matched Netflix titles in accepted tiers (PRD section 5 analysis population). Title-level: never exported.';

-- ------------------------------------------------------------------ quality-index counts
-- One function feeds both mart.quality_index (thresholds from mart.params) and
-- mart.sensitivity_genre (other thresholds), so every scenario uses the same SQL.
-- n_titles counts all Netflix titles in the segment, matched or not.
CREATE FUNCTION mart.qi_counts(p_min_rating numeric, p_min_votes int, p_exclude_ambiguous boolean)
RETURNS TABLE (dimension text, segment text, n_titles bigint, n_matched bigint, n_high bigint)
LANGUAGE sql STABLE AS $$
    WITH pop AS (
        SELECT a.show_id, (a.avg_rating >= p_min_rating AND a.num_votes >= p_min_votes) AS is_high
        FROM mart.analysis_titles a
        WHERE NOT (p_exclude_ambiguous AND a.ambiguous)
    ), seg AS (
        SELECT 'genre' AS dimension, g.genre AS segment, g.show_id FROM netflix.title_genre g
        UNION ALL
        SELECT 'country', c.country, c.show_id FROM netflix.title_country c
        UNION ALL
        SELECT 'rating_group', t.rating_group, t.show_id FROM netflix.titles t
    )
    SELECT s.dimension, s.segment,
           count(DISTINCT s.show_id),
           count(DISTINCT p.show_id),
           count(DISTINCT p.show_id) FILTER (WHERE p.is_high)
    FROM seg s LEFT JOIN pop p USING (show_id)
    GROUP BY s.dimension, s.segment
    UNION ALL
    SELECT 'catalog', 'all matched titles',
           (SELECT count(*) FROM netflix.titles), count(*), count(*) FILTER (WHERE is_high)
    FROM pop
$$;

-- ------------------------------------------------------------------ catalog_summary
CREATE TABLE mart.catalog_summary AS
WITH p AS (SELECT * FROM mart.params),
c AS (SELECT * FROM mart.qi_counts((SELECT min_rating FROM p), (SELECT min_votes FROM p), false)
      WHERE dimension = 'catalog'),
indo AS (
    SELECT count(DISTINCT tc.show_id) AS titles,
           count(DISTINCT a.show_id)  AS matched
    FROM netflix.title_country tc LEFT JOIN mart.analysis_titles a USING (show_id)
    WHERE tc.country = 'Indonesia'
)
SELECT c.n_titles                                   AS titles,
       c.n_matched                                  AS matched,
       c.n_titles - c.n_matched                     AS unmatched,
       round(c.n_matched::numeric / c.n_titles, 4)  AS match_rate,
       c.n_high                                     AS high_rated_n,
       round(c.n_high::numeric / c.n_matched, 4)    AS overall_high_rate,
       array_to_string(p.accepted_tiers, ',')       AS accepted_tiers,
       p.min_rating, p.min_votes, p.min_n, p.universe_start_year,
       indo.titles                                  AS indonesia_titles,
       indo.matched                                 AS indonesia_matched,
       indo.titles - indo.matched                   AS indonesia_unmatched
FROM c, p, indo;

-- ------------------------------------------------------------------ quality_index
-- quality_index = segment high-rated rate / high-rated rate of all matched titles.
-- share_of_catalog = segment's matched titles / all matched titles (shares of titles).
-- Ranked = not small_n and not not_ranked. qi_rank 1 = highest index. The median share
-- for quadrant labels is taken per dimension over ranked segments only; segments that
-- are not ranked get no quadrant.
CREATE TABLE mart.quality_index AS
WITH p AS (SELECT * FROM mart.params),
c AS (SELECT * FROM mart.qi_counts((SELECT min_rating FROM p), (SELECT min_votes FROM p), false)),
overall AS (SELECT n_matched AS total_matched, n_high::numeric / n_matched AS rate
            FROM c WHERE dimension = 'catalog'),
seg AS (
    SELECT c.dimension, c.segment, c.n_titles, c.n_matched, c.n_high,
           c.n_high::numeric / nullif(c.n_matched, 0)              AS high_rate,
           c.n_high::numeric / nullif(c.n_matched, 0) / o.rate     AS quality_index,
           c.n_matched::numeric / o.total_matched                  AS share_of_catalog,
           c.n_matched < p.min_n                                   AS small_n,
           (c.dimension = 'country' AND c.segment = 'Unknown')     AS not_ranked
    FROM c CROSS JOIN overall o CROSS JOIN p
    WHERE c.dimension <> 'catalog'
),
med AS (
    SELECT dimension, percentile_cont(0.5) WITHIN GROUP (ORDER BY share_of_catalog) AS median_share
    FROM seg WHERE NOT small_n AND NOT not_ranked
    GROUP BY dimension
)
SELECT s.dimension, s.segment, s.n_titles, s.n_matched, s.n_high,
       round(s.high_rate, 4)          AS high_rate,
       round(s.quality_index, 4)      AS quality_index,
       round(s.share_of_catalog, 4)   AS share_of_catalog,
       round(m.median_share::numeric, 4) AS median_share,
       s.small_n, s.not_ranked,
       CASE WHEN s.small_n OR s.not_ranked THEN NULL
            ELSE row_number() OVER (PARTITION BY s.dimension, (s.small_n OR s.not_ranked)
                                    ORDER BY s.quality_index DESC, s.n_matched DESC, s.segment) END AS qi_rank,
       CASE WHEN s.small_n OR s.not_ranked THEN NULL
            WHEN s.quality_index >= 1.10 AND s.share_of_catalog <  m.median_share THEN 'Scale-up candidate'
            WHEN s.quality_index >= 1.10 AND s.share_of_catalog >= m.median_share THEN 'Core strength'
            WHEN s.quality_index <= 0.90 AND s.share_of_catalog >= m.median_share THEN 'Volume without quality'
            WHEN s.quality_index <= 0.90 AND s.share_of_catalog <  m.median_share THEN 'Weak and small'
            ELSE 'Average' END AS quadrant
FROM seg s LEFT JOIN med m USING (dimension)
ORDER BY s.dimension, s.segment;

COMMENT ON COLUMN mart.quality_index.not_ranked IS
    'Country Unknown: matches at 55.2% vs 82-92% for named countries, so its matched titles are not representative. Shown, never ranked, left out of the median share.';

-- ------------------------------------------------------------------ country_votes_context
-- Limitations-page support: is a low country index driven by low IMDb visibility (few votes)
-- or by low ratings? Countries with n_matched >= min_n only (Unknown included, flagged not_ranked).
-- pct_rated_at_or_above_min_rating uses the min_rating threshold with no vote condition.
-- visibility_penalty = pct_rated_at_or_above_min_rating - high_rate (from mart.quality_index): the share of
-- titles rated high enough that fail only the vote threshold. Never negative, since high-rated titles are a subset.
CREATE TABLE mart.country_votes_context AS
WITH p AS (SELECT * FROM mart.params),
t AS (
    SELECT DISTINCT tc.country, a.show_id, a.avg_rating, a.num_votes
    FROM mart.analysis_titles a JOIN netflix.title_country tc USING (show_id)
)
SELECT t.country,
       count(*)                                                          AS n_matched,
       q.n_matched                                                       AS matched_titles,
       q.n_titles                                                        AS total_titles,
       round(q.n_matched::numeric / q.n_titles, 4)                       AS match_rate,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY t.num_votes)          AS median_votes,
       round(avg((t.num_votes >= p.min_votes)::int), 4)                  AS pct_titles_over_1000_votes,
       round(avg((t.avg_rating >= p.min_rating)::int), 4)                AS pct_rated_at_or_above_min_rating,
       round(avg((t.avg_rating >= p.min_rating)::int), 4) - q.high_rate  AS visibility_penalty,
       q.quality_index, q.qi_rank, q.not_ranked
FROM t CROSS JOIN p
JOIN mart.quality_index q ON q.dimension = 'country' AND q.segment = t.country
GROUP BY t.country, p.min_n, q.n_matched, q.n_titles, q.high_rate, q.quality_index, q.qi_rank, q.not_ranked
HAVING count(*) >= p.min_n
ORDER BY t.country;

COMMENT ON TABLE mart.country_votes_context IS
    'Per country with >= min_n matched titles: IMDb visibility (votes) vs ratings, next to the Quality index. Supports the limitations page.';
COMMENT ON COLUMN mart.country_votes_context.pct_titles_over_1000_votes IS
    'Share of matched titles with num_votes >= mart.params.min_votes (1,000 by default).';
COMMENT ON COLUMN mart.country_votes_context.match_rate IS
    'matched_titles / total_titles: share of the country''s Netflix titles matched in accepted tiers. matched_titles = n_matched.';
COMMENT ON COLUMN mart.country_votes_context.visibility_penalty IS
    'pct_rated_at_or_above_min_rating - quality_index.high_rate: share of titles that clear the rating threshold but not the vote threshold.';

-- Column comment carries the min_rating value in force when the mart was built.
DO $$
BEGIN
    EXECUTE format(
        'COMMENT ON COLUMN mart.country_votes_context.pct_rated_at_or_above_min_rating IS %L',
        format('Share of matched titles with avg_rating >= min_rating (= %s at build time), with no vote condition.',
               (SELECT min_rating FROM mart.params)));
END $$;

-- ------------------------------------------------------------------ coverage_gap_genre
-- IMDb genres on both sides. Type group: movie = movie/tvMovie/tvSpecial, series = tvSeries/tvMiniSeries.
-- netflix_high_share = Netflix high-rated titles with the genre / all Netflix high-rated titles in the group.
-- world_high_share   = same for IMDb titles with start_year >= universe_start_year.
-- coverage_gap = world_high_share / netflix_high_share (NULL when Netflix has no high-rated title in the genre).
-- gap_rank 1 = Netflix thinnest compared with the world, among segments that are not small_n.
CREATE TABLE mart.coverage_gap_genre AS
WITH p AS (SELECT * FROM mart.params),
grp(title_type, type_group) AS (VALUES ('movie', 'movie'), ('tvMovie', 'movie'), ('tvSpecial', 'movie'),
                                       ('tvSeries', 'series'), ('tvMiniSeries', 'series')),
nf AS (
    SELECT a.show_id, a.tconst, g.type_group,
           (a.avg_rating >= p.min_rating AND a.num_votes >= p.min_votes) AS is_high
    FROM mart.analysis_titles a JOIN grp g USING (title_type) CROSS JOIN p
),
nf_total AS (SELECT type_group, count(DISTINCT show_id) FILTER (WHERE is_high) AS high_total
             FROM nf GROUP BY type_group),
nf_genre AS (
    SELECT nf.type_group, tg.genre,
           count(DISTINCT nf.show_id)                      AS n_matched,
           count(DISTINCT nf.show_id) FILTER (WHERE is_high) AS netflix_high_n
    FROM nf JOIN imdb.title_genres tg USING (tconst)
    GROUP BY nf.type_group, tg.genre
),
world AS (
    SELECT i.tconst, g.type_group
    FROM imdb.titles i JOIN grp g USING (title_type) CROSS JOIN p
    WHERE i.start_year >= p.universe_start_year
      AND i.avg_rating >= p.min_rating AND i.num_votes >= p.min_votes
),
world_total AS (SELECT type_group, count(*) AS high_total FROM world GROUP BY type_group),
world_genre AS (
    SELECT w.type_group, tg.genre, count(*) AS world_high_n
    FROM world w JOIN imdb.title_genres tg USING (tconst)
    GROUP BY w.type_group, tg.genre
),
joined AS (
    SELECT coalesce(n.type_group, w.type_group) AS type_group,
           coalesce(n.genre, w.genre)           AS genre,
           coalesce(n.n_matched, 0)             AS n_matched,
           coalesce(n.netflix_high_n, 0)        AS netflix_high_n,
           coalesce(w.world_high_n, 0)          AS world_high_n
    FROM nf_genre n FULL JOIN world_genre w USING (type_group, genre)
),
calc AS (
    SELECT j.*,
           j.netflix_high_n::numeric / nt.high_total AS netflix_high_share,
           j.world_high_n::numeric / wt.high_total   AS world_high_share,
           nt.high_total AS netflix_high_total,
           wt.high_total AS world_high_total,
           j.n_matched < p.min_n AS small_n
    FROM joined j
    JOIN nf_total nt USING (type_group)
    JOIN world_total wt USING (type_group)
    CROSS JOIN p
)
SELECT type_group, genre, n_matched, netflix_high_n, netflix_high_total,
       round(netflix_high_share, 4) AS netflix_high_share,
       world_high_n, world_high_total,
       round(world_high_share, 4)   AS world_high_share,
       round(world_high_share / nullif(netflix_high_share, 0), 4) AS coverage_gap,
       small_n,
       CASE WHEN small_n OR netflix_high_share = 0 THEN NULL
            ELSE row_number() OVER (PARTITION BY type_group, (small_n OR netflix_high_share = 0)
                                    ORDER BY world_high_share / nullif(netflix_high_share, 0) DESC, genre) END AS gap_rank
FROM calc
ORDER BY type_group, genre;

-- ------------------------------------------------------------------ growth_by_year_added
-- Growth is a catalog fact, so this mart counts the full Netflix catalog, matched or not.
-- matched_titles (accepted tiers) sits next to each total for comparison.
CREATE TABLE mart.growth_by_year_added AS
WITH t AS (
    SELECT n.show_id, n.year_added, n.type,
           a.show_id IS NOT NULL AS is_matched,
           EXISTS (SELECT 1 FROM netflix.title_country tc
                   WHERE tc.show_id = n.show_id AND tc.country = 'Indonesia') AS is_indonesia
    FROM netflix.titles n LEFT JOIN mart.analysis_titles a USING (show_id)
    WHERE n.year_added IS NOT NULL
)
SELECT year_added, type,
       count(*)                                           AS total_titles,
       count(*) FILTER (WHERE is_matched)                 AS matched_titles,
       count(*) FILTER (WHERE is_indonesia)               AS indonesia_total_titles,
       count(*) FILTER (WHERE is_indonesia AND is_matched) AS indonesia_matched_titles
FROM t
GROUP BY year_added, type
ORDER BY year_added, type;

COMMENT ON TABLE mart.growth_by_year_added IS
    'Full Netflix catalog by year added and type, matched or not; matched_titles counts accepted tiers. Titles with no date_added are excluded.';

-- ------------------------------------------------------------------ indonesia_vs_global
-- Descriptive only (PRD section 5): counts and percentages, no index. Both sides are
-- matched titles; base n = matched Indonesian titles and all matched titles.
CREATE TABLE mart.indonesia_vs_global AS
WITH indo AS (
    SELECT DISTINCT a.show_id
    FROM mart.analysis_titles a JOIN netflix.title_country tc USING (show_id)
    WHERE tc.country = 'Indonesia'
),
seg AS (
    SELECT 'genre' AS dimension, g.genre AS segment, a.show_id
    FROM mart.analysis_titles a JOIN netflix.title_genre g USING (show_id)
    UNION ALL
    SELECT 'rating_group', a.rating_group, a.show_id FROM mart.analysis_titles a
),
base AS (SELECT (SELECT count(*) FROM indo) AS indonesia_base_n,
                (SELECT count(*) FROM mart.analysis_titles) AS global_base_n)
SELECT s.dimension, s.segment,
       count(DISTINCT s.show_id) FILTER (WHERE i.show_id IS NOT NULL)      AS indonesia_n,
       round(count(DISTINCT s.show_id) FILTER (WHERE i.show_id IS NOT NULL)::numeric
             / b.indonesia_base_n, 4)                                       AS indonesia_pct,
       count(DISTINCT s.show_id)                                            AS global_n,
       round(count(DISTINCT s.show_id)::numeric / b.global_base_n, 4)      AS global_pct,
       b.indonesia_base_n, b.global_base_n
FROM seg s LEFT JOIN indo i USING (show_id) CROSS JOIN base b
GROUP BY s.dimension, s.segment, b.indonesia_base_n, b.global_base_n
ORDER BY s.dimension, s.segment;

COMMENT ON TABLE mart.indonesia_vs_global IS
    'Matched titles only. Indonesia base n = matched Indonesian titles (79 of 90 at build time; the rest could not be matched to IMDb, see mart.catalog_summary.indonesia_unmatched).';
