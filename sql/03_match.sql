-- Match Netflix titles to IMDb titles (IMPLEMENTATION_GUIDE section 5, PRD section 6).
-- Tiers T1 exact and T2 year_pm1 only; T3 fuzzy is not built.
-- Each tier considers only Netflix titles not matched by an earlier tier, keeps the
-- candidate with the most votes (tconst breaks ties), and records how many
-- candidates passed. ambiguous = more than one candidate passed the tier's rules.
-- Ends with one 'unmatched' row per remaining title, so title_match has exactly
-- one row per netflix.titles row. Run by scripts/03_run_match.py in one transaction.

TRUNCATE netflix.title_match;

-- T1 exact: same normalized name, compatible type, exact year rule.
INSERT INTO netflix.title_match (show_id, tconst, match_tier, candidate_count, ambiguous, similarity)
SELECT show_id, tconst, 'exact', candidate_count, candidate_count > 1, NULL
FROM (
    SELECT n.show_id, i.tconst,
           count(*)     OVER (PARTITION BY n.show_id) AS candidate_count,
           row_number() OVER (PARTITION BY n.show_id ORDER BY i.num_votes DESC, i.tconst) AS rn
    FROM netflix.titles n
    JOIN imdb.title_names nm ON nm.name_norm = n.title_norm AND n.title_norm <> ''
    JOIN imdb.titles i       ON i.tconst = nm.tconst
    WHERE (    (n.type = 'Movie'   AND i.title_type IN ('movie','tvMovie','tvSpecial')
                AND i.start_year = n.release_year)
            OR (n.type = 'TV Show' AND i.title_type IN ('tvSeries','tvMiniSeries')
                AND n.release_year BETWEEN i.start_year AND COALESCE(i.end_year, 9999)))
      AND NOT EXISTS (SELECT 1 FROM netflix.title_match m WHERE m.show_id = n.show_id)
) c
WHERE rn = 1;

-- T2 year_pm1: same as T1 with the year rule widened by 1.
INSERT INTO netflix.title_match (show_id, tconst, match_tier, candidate_count, ambiguous, similarity)
SELECT show_id, tconst, 'year_pm1', candidate_count, candidate_count > 1, NULL
FROM (
    SELECT n.show_id, i.tconst,
           count(*)     OVER (PARTITION BY n.show_id) AS candidate_count,
           row_number() OVER (PARTITION BY n.show_id ORDER BY i.num_votes DESC, i.tconst) AS rn
    FROM netflix.titles n
    JOIN imdb.title_names nm ON nm.name_norm = n.title_norm AND n.title_norm <> ''
    JOIN imdb.titles i       ON i.tconst = nm.tconst
    WHERE (    (n.type = 'Movie'   AND i.title_type IN ('movie','tvMovie','tvSpecial')
                AND abs(i.start_year - n.release_year) <= 1)
            OR (n.type = 'TV Show' AND i.title_type IN ('tvSeries','tvMiniSeries')
                AND n.release_year BETWEEN i.start_year - 1 AND COALESCE(i.end_year, 9999) + 1))
      AND NOT EXISTS (SELECT 1 FROM netflix.title_match m WHERE m.show_id = n.show_id)
) c
WHERE rn = 1;

-- Everything left is unmatched.
INSERT INTO netflix.title_match (show_id, tconst, match_tier, candidate_count, ambiguous, similarity)
SELECT n.show_id, NULL, 'unmatched', 0, false, NULL
FROM netflix.titles n
WHERE NOT EXISTS (SELECT 1 FROM netflix.title_match m WHERE m.show_id = n.show_id);

ANALYZE netflix.title_match;
