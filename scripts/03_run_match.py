"""Run the Netflix -> IMDb matcher (sql/03_match.sql) and write the match report.

Tiers T1 exact and T2 year_pm1 only. Rebuilds netflix.title_match from scratch,
runs the P3 checks, prints the report and saves it to docs/match_report.md.

Run from the repo root:
    python scripts/03_run_match.py
"""
import random
import sys
from datetime import date
from pathlib import Path

from lib.db import connect

SQL_FILE = Path("sql/03_match.sql")
REPORT = Path("docs/match_report.md")
TIERS = ["exact", "year_pm1", "unmatched"]
SEED = 42
N_UNMATCHED_SAMPLE = 30


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v).replace("|", "\\|") for v in r) + " |")
    return "\n".join(out)


def tier_section(cur, total):
    rows = dict(cur.execute(
        "SELECT match_tier, count(*) FROM netflix.title_match GROUP BY 1").fetchall())
    matched = rows.get("exact", 0) + rows.get("year_pm1", 0)
    body = [(t, f"{rows.get(t, 0):,}", pct(rows.get(t, 0), total)) for t in TIERS]
    body.append(("**matched (exact + year_pm1)**", f"**{matched:,}**", f"**{pct(matched, total)}**"))
    body.append(("total", f"{sum(rows.values()):,}", pct(sum(rows.values()), total)))
    return rows, table(["tier", "titles", "% of all titles"], body)


def type_section(cur):
    data = cur.execute("""
        SELECT n.type,
               count(*) AS n,
               count(*) FILTER (WHERE m.match_tier = 'exact')     AS exact,
               count(*) FILTER (WHERE m.match_tier = 'year_pm1')  AS pm1,
               count(*) FILTER (WHERE m.match_tier = 'unmatched') AS unmatched
        FROM netflix.titles n JOIN netflix.title_match m USING (show_id)
        GROUP BY 1 ORDER BY 1""").fetchall()
    body = [(t, f"{n:,}", f"{e:,} ({pct(e, n)})", f"{p:,} ({pct(p, n)})",
             f"{u:,} ({pct(u, n)})", pct(e + p, n)) for t, n, e, p, u in data]
    return data, table(["type", "titles", "exact", "year_pm1", "unmatched", "match rate"], body)


def country_section(cur):
    data = cur.execute("""
        WITH c AS (
            SELECT tc.country, tc.show_id, m.match_tier
            FROM netflix.title_country tc JOIN netflix.title_match m USING (show_id)
        ), ranked AS (
            SELECT country, count(DISTINCT show_id) AS n,
                   rank() OVER (ORDER BY count(DISTINCT show_id) DESC, country) AS rk
            FROM c WHERE country <> 'Unknown' GROUP BY country
        )
        SELECT c.country,
               count(DISTINCT c.show_id) AS n,
               count(DISTINCT c.show_id) FILTER (WHERE c.match_tier = 'exact')    AS exact,
               count(DISTINCT c.show_id) FILTER (WHERE c.match_tier = 'year_pm1') AS pm1,
               min(r.rk) AS rk
        FROM c LEFT JOIN ranked r USING (country)
        WHERE r.rk <= 10 OR c.country IN ('Indonesia', 'Unknown')
        GROUP BY c.country
        ORDER BY min(r.rk) NULLS LAST, c.country""").fetchall()
    body = [(country, f"{n:,}", f"{e:,}", f"{p:,}", f"{n - e - p:,}", pct(e + p, n))
            for country, n, e, p, _ in data]
    return data, table(["country", "titles", "exact", "year_pm1", "unmatched", "match rate"], body)


def year_added_section(cur):
    data = cur.execute("""
        SELECT coalesce(n.year_added::text, 'missing') AS year_added, count(*) AS n,
               count(*) FILTER (WHERE m.match_tier <> 'unmatched') AS matched
        FROM netflix.titles n JOIN netflix.title_match m USING (show_id)
        GROUP BY 1 ORDER BY 1""").fetchall()
    body = [(y, f"{n:,}", f"{k:,}", pct(k, n)) for y, n, k in data]
    return table(["year_added", "titles", "matched", "match rate"], body)


def shared_tconst_section(cur):
    data = cur.execute("""
        SELECT m.tconst, i.primary_title, i.start_year, count(*) AS n_netflix,
               string_agg(n.title || ' (' || n.show_id || ', ' || n.type || ', ' || n.release_year || ')',
                          '; ' ORDER BY n.show_id) AS netflix_titles
        FROM netflix.title_match m
        JOIN netflix.titles n USING (show_id)
        JOIN imdb.titles i USING (tconst)
        WHERE m.tconst IS NOT NULL
        GROUP BY m.tconst, i.primary_title, i.start_year
        HAVING count(*) > 1
        ORDER BY count(*) DESC, m.tconst""").fetchall()
    n_titles = sum(r[3] for r in data)
    return len(data), n_titles, table(["tconst", "IMDb title", "start_year", "Netflix titles", "which"], data)


def ambiguous_section(cur):
    data = cur.execute("""
        SELECT match_tier, count(*) FILTER (WHERE ambiguous) AS amb, count(*) AS n,
               max(candidate_count) AS max_cand
        FROM netflix.title_match WHERE match_tier <> 'unmatched'
        GROUP BY 1 ORDER BY array_position(ARRAY['exact','year_pm1'], match_tier)""").fetchall()
    body = [(t, f"{a:,}", f"{n:,}", pct(a, n), mc) for t, a, n, mc in data]
    return sum(r[1] for r in data), table(
        ["tier", "ambiguous", "matched", "% ambiguous", "max candidates"], body)


def near_miss_section(cur):
    # Diagnostic only, not a tier: unmatched titles whose exact normalized name exists in
    # IMDb with a compatible type, but every such candidate falls outside the T2 year window.
    data = cur.execute("""
        WITH cand AS (
            SELECT n.show_id, n.type,
                   min(CASE WHEN n.type = 'Movie' THEN abs(i.start_year - n.release_year)
                            WHEN n.release_year < i.start_year THEN i.start_year - n.release_year
                            ELSE n.release_year - coalesce(i.end_year, 9999) END) AS gap
            FROM netflix.titles n
            JOIN netflix.title_match m USING (show_id)
            JOIN imdb.title_names nm ON nm.name_norm = n.title_norm AND n.title_norm <> ''
            JOIN imdb.titles i ON i.tconst = nm.tconst
            WHERE m.match_tier = 'unmatched'
              AND CASE n.type WHEN 'Movie'   THEN i.title_type = ANY ('{movie,tvMovie,tvSpecial}')
                              WHEN 'TV Show' THEN i.title_type = ANY ('{tvSeries,tvMiniSeries}') END
            GROUP BY n.show_id, n.type
        )
        SELECT type, count(*) AS n,
               count(*) FILTER (WHERE gap = 2)            AS gap2,
               count(*) FILTER (WHERE gap BETWEEN 3 AND 5) AS gap3_5,
               count(*) FILTER (WHERE gap > 5)             AS gap6p
        FROM cand GROUP BY type ORDER BY type""").fetchall()
    unmatched = dict(cur.execute("""
        SELECT n.type, count(*) FROM netflix.titles n JOIN netflix.title_match m USING (show_id)
        WHERE m.match_tier = 'unmatched' GROUP BY 1""").fetchall())
    body = [(t, f"{unmatched.get(t, 0):,}", f"{n:,}", f"{g2:,}", f"{g35:,}", f"{g6:,}")
            for t, n, g2, g35, g6 in data]
    return table(["type", "unmatched", "same name + type in IMDb", "nearest year off by 2",
                  "off by 3-5", "off by 6+"], body)


def unmatched_sample(cur):
    rows = cur.execute("""
        SELECT n.show_id, n.title, n.release_year, n.type, coalesce(n.country, 'Unknown')
        FROM netflix.titles n JOIN netflix.title_match m USING (show_id)
        WHERE m.match_tier = 'unmatched' ORDER BY n.show_id""").fetchall()
    sample = random.Random(SEED).sample(rows, min(N_UNMATCHED_SAMPLE, len(rows)))
    sample.sort(key=lambda r: int(r[0][1:]))
    return table(["show_id", "title", "release_year", "type", "country"], sample)


def checks(cur, total, tier_rows):
    n_rows, n_ids = cur.execute(
        "SELECT count(*), count(DISTINCT show_id) FROM netflix.title_match").fetchone()
    missing = cur.execute("""
        SELECT count(*) FROM netflix.titles n
        WHERE NOT EXISTS (SELECT 1 FROM netflix.title_match m WHERE m.show_id = n.show_id)""").fetchone()[0]
    empty_join = cur.execute("""
        SELECT count(*) FROM netflix.title_match m JOIN netflix.titles n USING (show_id)
        WHERE m.tconst IS NOT NULL AND n.title_norm = ''""").fetchone()[0]
    # Re-check every accepted match against the rules, written independently of 03_match.sql.
    rule_breaks = cur.execute("""
        SELECT count(*) FROM netflix.title_match m
        JOIN netflix.titles n USING (show_id)
        JOIN imdb.titles i USING (tconst)
        WHERE NOT (
              EXISTS (SELECT 1 FROM imdb.title_names nm WHERE nm.tconst = i.tconst AND nm.name_norm = n.title_norm)
          AND CASE n.type WHEN 'Movie'   THEN i.title_type = ANY ('{movie,tvMovie,tvSpecial}')
                          WHEN 'TV Show' THEN i.title_type = ANY ('{tvSeries,tvMiniSeries}') END
          AND CASE
                WHEN n.type = 'Movie' AND m.match_tier = 'exact'    THEN i.start_year = n.release_year
                WHEN n.type = 'Movie' AND m.match_tier = 'year_pm1' THEN abs(i.start_year - n.release_year) = 1
                WHEN m.match_tier = 'exact'
                  THEN n.release_year >= i.start_year AND n.release_year <= coalesce(i.end_year, 9999)
                ELSE n.release_year >= i.start_year - 1 AND n.release_year <= coalesce(i.end_year, 9999) + 1
                     AND NOT (n.release_year >= i.start_year AND n.release_year <= coalesce(i.end_year, 9999))
              END)""").fetchone()[0]
    result = [
        (f"title_match rows = {total:,} (got {n_rows:,})", n_rows == total),
        (f"one row per show_id ({n_ids:,} distinct)", n_ids == n_rows),
        (f"no Netflix title without a row (got {missing})", missing == 0),
        (f"tier counts add up to {total:,} (got {sum(tier_rows.values()):,})", sum(tier_rows.values()) == total),
        (f"no match made on an empty title_norm (got {empty_join})", empty_join == 0),
        (f"every match satisfies name + type + year rule of its tier (violations: {rule_breaks})", rule_breaks == 0),
        ("no fuzzy tier rows (T3 not built)", tier_rows.get("fuzzy", 0) == 0),
    ]
    return result


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SQL_FILE.read_text(encoding="utf-8"))
        total = cur.execute("SELECT count(*) FROM netflix.titles").fetchone()[0]

        tier_rows, tier_md = tier_section(cur, total)
        _, type_md = type_section(cur)
        _, country_md = country_section(cur)
        year_md = year_added_section(cur)
        n_shared, n_shared_titles, shared_md = shared_tconst_section(cur)
        n_amb, amb_md = ambiguous_section(cur)
        near_md = near_miss_section(cur)
        sample_md = unmatched_sample(cur)
        check_rows = checks(cur, total, tier_rows)

    check_md = "\n".join(f"- [{'PASS' if ok else 'FAIL'}] {label}" for label, ok in check_rows)
    report = f"""# Match report — Netflix to IMDb

Generated {date.today().isoformat()} by `scripts/03_run_match.py` from `sql/03_match.sql`.
Tiers built: T1 `exact`, T2 `year_pm1`. T3 `fuzzy` is not built. Rules: PRD section 6.
Audit precision per tier: pending (fill `docs/match_audit_sample.csv`, then run `python scripts/03_audit.py summary`).

## Checks

{check_md}

## Tiers, overall ({total:,} Netflix titles)

{tier_md}

## Tiers by type

{type_md}

## Match rate by country

Ten biggest countries by Netflix title count, plus Indonesia and Unknown (no country listed).
A title counts once in each of its countries.

{country_md}

## Match rate by year added

{year_md}

## IMDb titles matched by more than one Netflix title

{n_shared} tconst are matched by more than one Netflix title ({n_shared_titles} Netflix titles in total).

{shared_md}

## Ambiguous matches

{n_amb:,} matches had more than one candidate passing the tier's rules; the one with the most votes was kept.

{amb_md}

## Unmatched near misses (diagnostic, no rule applied)

Unmatched titles whose normalized name exists in IMDb with a compatible type, but outside the T2 year window.
Year distance for TV shows is measured to the IMDb startYear-endYear span.

{near_md}

## 30 random unmatched titles (seed {SEED})

{sample_md}
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    print(f"Saved {REPORT}")
    if not all(ok for _, ok in check_rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
