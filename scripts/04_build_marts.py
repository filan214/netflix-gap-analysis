"""Build the Phase 4 analysis marts, check them, export CSVs and print the summary.

Runs sql/04_marts.sql and sql/04_sensitivity.sql in one transaction, runs the P4 checks
(the transaction rolls back if any fails), exports every mart to dashboard/data/<mart>.csv
and prints the analysis-population size, top and bottom 5 segments per dimension with
their n, and the sensitivity overlap. No results file is written.

Run from the repo root:
    python scripts/04_build_marts.py
"""
import sys
from pathlib import Path

from lib.db import connect

SQL_FILES = [Path("sql/04_marts.sql"), Path("sql/04_sensitivity.sql")]
EXPORT_DIR = Path("dashboard/data")
MARTS = {
    "catalog_summary":      "",
    "quality_index":        "ORDER BY dimension, qi_rank NULLS LAST, segment",
    "coverage_gap_genre":   "ORDER BY type_group, gap_rank NULLS LAST, genre",
    "growth_by_year_added": "ORDER BY year_added, type",
    "indonesia_vs_global":  "ORDER BY dimension, segment",
    "sensitivity_genre":    "ORDER BY scenario_order, rank NULLS LAST, genre",
}
TOP = 5


def one(cur, sql, params=None):
    return cur.execute(sql, params).fetchone()


def run_checks(cur):
    p = dict(zip(["min_rating", "min_votes", "min_n", "tiers"],
                 one(cur, "SELECT min_rating, min_votes, min_n, accepted_tiers FROM mart.params")))
    summary = dict(zip(["titles", "matched", "high", "indo_titles", "indo_matched"], one(cur, """
        SELECT titles, matched, high_rated_n, indonesia_titles, indonesia_matched FROM mart.catalog_summary""")))
    checks = []

    # Accepted tiers only.
    tiers_used = [r[0] for r in cur.execute("SELECT DISTINCT match_tier FROM mart.analysis_titles ORDER BY 1")]
    hand_matched = one(cur, "SELECT count(*) FROM netflix.title_match WHERE match_tier = ANY (%s)", (p["tiers"],))[0]
    checks.append((f"analysis uses accepted tiers only {p['tiers']} (found {tiers_used})",
                   set(tiers_used) <= set(p["tiers"])))
    checks.append((f"analysis population = title_match rows in accepted tiers "
                   f"({summary['matched']:,} vs {hand_matched:,})", summary["matched"] == hand_matched))

    # Whole-catalog Quality index = 1.0, recomputed without the marts' view or function.
    hand_rate = one(cur, """
        SELECT avg((i.avg_rating >= %s AND i.num_votes >= %s)::int)::float
        FROM netflix.title_match m JOIN imdb.titles i USING (tconst)
        WHERE m.match_tier = ANY (%s)""", (p["min_rating"], p["min_votes"], p["tiers"]))[0]
    mart_rate = summary["high"] / summary["matched"]
    qi_catalog = hand_rate / mart_rate
    assert abs(qi_catalog - 1.0) < 1e-9, f"whole-catalog Quality index = {qi_catalog}, expected 1.0"
    checks.append((f"whole-catalog Quality index recomputed independently = {qi_catalog:.6f}", True))
    # rating_group partitions the catalog, so its segments must add back up to index 1.0.
    rg_high, rg_matched = one(cur, """
        SELECT sum(n_high)::float, sum(n_matched)::float FROM mart.quality_index WHERE dimension = 'rating_group'""")
    qi_rg = (rg_high / rg_matched) / mart_rate
    assert abs(qi_rg - 1.0) < 1e-9, f"rating_group segments add up to index {qi_rg}, expected 1.0"
    checks.append((f"rating_group segments add back up to Quality index {qi_rg:.6f}", True))

    # One segment recounted with a hand-written query (genre 'Dramas').
    hand = one(cur, """
        SELECT count(DISTINCT g.show_id),
               count(DISTINCT g.show_id) FILTER (WHERE m.match_tier = ANY (%(t)s)),
               count(DISTINCT g.show_id) FILTER (WHERE m.match_tier = ANY (%(t)s)
                                                 AND i.avg_rating >= %(r)s AND i.num_votes >= %(v)s)
        FROM netflix.title_genre g
        JOIN netflix.title_match m ON m.show_id = g.show_id
        LEFT JOIN imdb.titles i ON i.tconst = m.tconst
        WHERE g.genre = 'Dramas'""", {"t": p["tiers"], "r": p["min_rating"], "v": p["min_votes"]})
    hand_qi = round((hand[2] / hand[1]) / mart_rate, 4)
    mart_row = one(cur, """
        SELECT n_titles, n_matched, n_high, quality_index::float
        FROM mart.quality_index WHERE dimension = 'genre' AND segment = 'Dramas'""")
    checks.append((f"hand recount genre 'Dramas': titles/matched/high/index {hand[0]}/{hand[1]}/{hand[2]}/{hand_qi} "
                   f"vs mart {mart_row[0]}/{mart_row[1]}/{mart_row[2]}/{mart_row[3]}",
                   (*hand, hand_qi) == tuple(mart_row)))

    # Small-n rule: nothing below min_n is ranked, and small_n is set exactly when n_matched < min_n.
    bad_qi = one(cur, """SELECT count(*) FROM mart.quality_index
                         WHERE (n_matched < %(n)s) <> small_n OR (small_n AND (qi_rank IS NOT NULL OR quadrant IS NOT NULL))""",
                 {"n": p["min_n"]})[0]
    bad_gap = one(cur, """SELECT count(*) FROM mart.coverage_gap_genre
                          WHERE (n_matched < %(n)s) <> small_n OR (small_n AND gap_rank IS NOT NULL)""",
                  {"n": p["min_n"]})[0]
    bad_sens = one(cur, """SELECT count(*) FROM mart.sensitivity_genre
                           WHERE (n_matched < %(n)s) <> small_n OR (small_n AND rank IS NOT NULL)""",
                   {"n": p["min_n"]})[0]
    checks.append((f"no segment below min_n = {p['min_n']} is ranked without small_n "
                   f"(violations: quality {bad_qi}, coverage {bad_gap}, sensitivity {bad_sens})",
                   bad_qi == bad_gap == bad_sens == 0))

    unknown = one(cur, """SELECT not_ranked, qi_rank, quadrant FROM mart.quality_index
                          WHERE dimension = 'country' AND segment = 'Unknown'""")
    checks.append((f"country Unknown kept but not ranked (not_ranked, rank, quadrant = {unknown})",
                   unknown == (True, None, None)))

    diff = one(cur, """
        SELECT count(*) FROM mart.sensitivity_genre s
        JOIN mart.quality_index q ON q.dimension = 'genre' AND q.segment = s.genre
        WHERE s.scenario = 'baseline'
          AND (s.quality_index IS DISTINCT FROM q.quality_index OR s.rank IS DISTINCT FROM q.qi_rank)""")[0]
    checks.append((f"sensitivity baseline = mart.quality_index genre rows (differences: {diff})", diff == 0))

    indo_base = one(cur, "SELECT DISTINCT indonesia_base_n FROM mart.indonesia_vs_global")[0]
    checks.append((f"Indonesia base n = matched Indonesian titles ({indo_base} of {summary['indo_titles']}, "
                   f"{summary['indo_titles'] - summary['indo_matched']} unmatched)",
                   indo_base == summary["indo_matched"]))
    return checks


def export(cur):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    for mart, order in MARTS.items():
        # PostgreSQL writes booleans as t/f; cast to text so Power BI reads true/false.
        cols = ", ".join(f"{c}::text AS {c}" if t == "boolean" else c for c, t in cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'mart' AND table_name = %s ORDER BY ordinal_position""", (mart,)))
        path = EXPORT_DIR / f"{mart}.csv"
        with path.open("wb") as fh, cur.copy(
                f"COPY (SELECT {cols} FROM mart.{mart} {order}) TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
            for block in cp:
                fh.write(block)
        rows = one(cur, f"SELECT count(*) FROM mart.{mart}")[0]
        print(f"  {path}  ({rows:,} rows)")


def fmt_pct(x):
    return f"{100 * float(x):.1f}%"


def print_summary(cur):
    s = dict(zip([d.name for d in cur.execute("SELECT * FROM mart.catalog_summary").description],
                 cur.fetchone()))
    tiers = cur.execute("""SELECT match_tier, count(*) FROM mart.analysis_titles
                           GROUP BY 1 ORDER BY array_position(ARRAY['exact','year_pm1','fuzzy'], match_tier)""").fetchall()
    print("\n=== Analysis population ===")
    print(f"  matched titles (accepted tiers {s['accepted_tiers']}): {s['matched']:,} of {s['titles']:,} "
          f"({fmt_pct(s['match_rate'])}); unmatched {s['unmatched']:,}")
    print("  by tier: " + ", ".join(f"{t} {n:,}" for t, n in tiers))
    print(f"  high-rated (rating >= {s['min_rating']}, votes >= {s['min_votes']:,}): {s['high_rated_n']:,} "
          f"= {fmt_pct(s['overall_high_rate'])} of matched titles")
    print(f"  Indonesia: {s['indonesia_matched']} of {s['indonesia_titles']} titles matched "
          f"({s['indonesia_unmatched']} could not be matched to IMDb)")

    for dim in ["genre", "country", "rating_group"]:
        ranked = cur.execute("""
            SELECT qi_rank, segment, n_matched, n_high, quality_index, share_of_catalog, quadrant
            FROM mart.quality_index WHERE dimension = %s AND qi_rank IS NOT NULL ORDER BY qi_rank""", (dim,)).fetchall()
        hidden = one(cur, """SELECT count(*) FILTER (WHERE small_n), count(*) FILTER (WHERE not_ranked AND NOT small_n)
                             FROM mart.quality_index WHERE dimension = %s""", (dim,))
        print(f"\n=== Quality index: {dim} ({len(ranked)} ranked; {hidden[0]} small_n"
              + (f", {hidden[1]} not_ranked" if hidden[1] else "") + " left out) ===")
        top = ranked[:TOP]
        bottom = [r for r in ranked[-TOP:] if r not in top] if len(ranked) > TOP else []
        for label, rows in [("top", top), ("bottom", bottom)]:
            if rows:
                print(f"  {label}:")
            for rk, seg, n, h, qi, share, quad in rows:
                print(f"    #{rk:<3} {seg:<32} n={n:<5,} high={h:<5,} index={float(qi):.2f} "
                      f"share={fmt_pct(share):>6}  {quad}")
        if dim == "country":
            u = one(cur, """SELECT n_matched, n_high, quality_index FROM mart.quality_index
                            WHERE dimension = 'country' AND segment = 'Unknown'""")
            print(f"  not ranked: Unknown  n={u[0]:,} high={u[1]:,} index={float(u[2]):.2f}")

    for grp in ["movie", "series"]:
        rows = cur.execute("""
            SELECT gap_rank, genre, n_matched, netflix_high_n, world_high_n, netflix_high_share,
                   world_high_share, coverage_gap
            FROM mart.coverage_gap_genre WHERE type_group = %s AND gap_rank IS NOT NULL ORDER BY gap_rank""",
                           (grp,)).fetchall()
        print(f"\n=== Coverage gap (IMDb genres): {grp} ({len(rows)} ranked) ===")
        top = rows[:TOP]
        bottom = [r for r in rows[-TOP:] if r not in top] if len(rows) > TOP else []
        for label, part in [("Netflix thinnest (gap > 1)", top), ("Netflix over-indexes (gap < 1)", bottom)]:
            if part:
                print(f"  {label}:")
            for rk, g, n, nh, wh, ns, ws, gap in part:
                print(f"    #{rk:<3} {g:<12} n={n:<5,} netflix_high={nh:<4,} ({fmt_pct(ns):>6})  "
                      f"world_high={wh:<6,} ({fmt_pct(ws):>6})  gap={float(gap):.2f}")

    rows = cur.execute("""
        SELECT segment, indonesia_n, indonesia_pct, global_n, global_pct, indonesia_base_n, global_base_n
        FROM mart.indonesia_vs_global WHERE dimension = 'genre' AND indonesia_n > 0
        ORDER BY indonesia_n DESC, segment LIMIT %s""", (TOP,)).fetchall()
    print(f"\n=== Indonesia genre mix, top {TOP} (n = {rows[0][5]} matched Indonesian titles vs "
          f"{rows[0][6]:,} matched titles overall) ===")
    for seg, i_n, i_p, g_n, g_p, _, _ in rows:
        print(f"    {seg:<32} indonesia {i_n:>3} ({fmt_pct(i_p):>6})   global {g_n:>5,} ({fmt_pct(g_p):>6})")

    print("\n=== Sensitivity: genre Quality index, top/bottom 5 kept vs baseline ===")
    base = cur.execute("""SELECT genre, rank FROM mart.sensitivity_genre
                          WHERE scenario = 'baseline' AND rank IS NOT NULL ORDER BY rank""").fetchall()
    base_top = {g for g, _ in base[:TOP]}
    base_bottom = {g for g, _ in base[-TOP:]}
    scenarios = cur.execute("""SELECT DISTINCT scenario_order, scenario, min_rating, min_votes, exclude_ambiguous
                               FROM mart.sensitivity_genre ORDER BY scenario_order""").fetchall()
    for _, sc, r, v, ex in scenarios:
        ranked = cur.execute("""SELECT genre FROM mart.sensitivity_genre
                                WHERE scenario = %s AND rank IS NOT NULL ORDER BY rank""", (sc,)).fetchall()
        genres = [g for (g,) in ranked]
        n_pop = one(cur, "SELECT count(*) FROM mart.analysis_titles WHERE NOT (%s AND ambiguous)", (ex,))[0]
        kept_top = len(base_top & set(genres[:TOP]))
        kept_bottom = len(base_bottom & set(genres[-TOP:]))
        label = f"{sc} ({float(r)} / {v:,}{', ambiguous excluded' if ex else ''})"
        print(f"  {label:<46} top 5 kept {kept_top}/5   bottom 5 kept {kept_bottom}/5   "
              f"ranked genres {len(genres)}   population {n_pop:,}")
        if sc != "baseline":
            lost_top = sorted(base_top - set(genres[:TOP]))
            lost_bottom = sorted(base_bottom - set(genres[-TOP:]))
            if lost_top or lost_bottom:
                print(f"    dropped out: top {lost_top or '-'}; bottom {lost_bottom or '-'}")
    print(f"  baseline top 5: {[g for g, _ in base[:TOP]]}")
    print(f"  baseline bottom 5: {[g for g, _ in base[-TOP:]]}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        for f in SQL_FILES:
            cur.execute(f.read_text(encoding="utf-8"))
        checks = run_checks(cur)
        print("=== P4 checks ===")
        for label, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not all(ok for _, ok in checks):
            sys.exit("P4 checks failed: transaction rolled back, nothing exported.")
        print("=== Export (aggregate marts only) ===")
        export(cur)
        print_summary(cur)


if __name__ == "__main__":
    main()
