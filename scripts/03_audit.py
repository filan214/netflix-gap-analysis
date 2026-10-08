"""Match audit: export a sample to check by hand, then summarize precision per tier.

    python scripts/03_audit.py export    # writes docs/match_audit_sample.csv
    python scripts/03_audit.py summary   # reads the filled file, prints precision per tier

export samples up to 30 matches per built tier with a fixed seed and refuses to
overwrite a file that already has answers in `correct` (pass --force to do it anyway).
summary only reads the file; it changes nothing in the database or on disk.
Fill `correct` with y or n.
"""
import argparse
import csv
import random
import sys
from pathlib import Path

AUDIT = Path("docs/match_audit_sample.csv")
TIERS = ["exact", "year_pm1"]   # tiers built so far; T3 fuzzy is not built
PER_TIER = 30
SEED = 42
PRECISION_BAR = 0.90
COLUMNS = ["show_id", "netflix_title", "netflix_year", "netflix_type", "netflix_country",
           "imdb_title", "imdb_original_title", "imdb_start_year", "imdb_end_year", "imdb_type",
           "tconst", "imdb_url", "tier", "candidate_count", "correct"]


def read_audit():
    # utf-8-sig: the export writes a BOM so Excel shows accents; tolerate files without one.
    with AUDIT.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def export(force):
    from lib.db import connect

    if AUDIT.exists() and not force:
        filled = [r for r in read_audit() if (r.get("correct") or "").strip()]
        if filled:
            sys.exit(f"{AUDIT} already has {len(filled)} filled answers. "
                     "Use --force to overwrite it.")

    rng = random.Random(SEED)
    sample = []
    with connect() as conn:
        for tier in TIERS:
            rows = conn.execute("""
                SELECT n.show_id, n.title, n.release_year, n.type, coalesce(n.country, 'Unknown'),
                       i.primary_title, i.original_title, i.start_year, i.end_year, i.title_type,
                       m.tconst, 'https://www.imdb.com/title/' || m.tconst || '/', m.match_tier,
                       m.candidate_count
                FROM netflix.title_match m
                JOIN netflix.titles n USING (show_id)
                JOIN imdb.titles i USING (tconst)
                WHERE m.match_tier = %s
                ORDER BY n.show_id""", (tier,)).fetchall()
            picked = rng.sample(rows, min(PER_TIER, len(rows)))
            picked.sort(key=lambda r: int(r[0][1:]))
            sample.extend(picked)
            print(f"{tier:<10} {len(picked):>3} of {len(rows):,} matches sampled")

    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in sample:
            w.writerow([*r, ""])
    print(f"Wrote {len(sample)} rows to {AUDIT} (seed {SEED}). Fill `correct` with y or n.")


def summary():
    if not AUDIT.exists():
        sys.exit(f"{AUDIT} not found. Run: python scripts/03_audit.py export")
    rows = read_audit()
    print(f"=== Audit precision per tier ({AUDIT}) ===")
    print(f"{'tier':<10}{'sampled':>8}{'y':>5}{'n':>5}{'blank':>7}{'other':>7}  precision")
    for tier in TIERS:
        answers = [(r.get("correct") or "").strip().lower() for r in rows if r["tier"] == tier]
        y, n = answers.count("y"), answers.count("n")
        blank = answers.count("")
        other = len(answers) - y - n - blank
        if y + n:
            p = y / (y + n)
            verdict = "meets 90%" if p >= PRECISION_BAR else "BELOW 90% -> drop from accepted_tiers"
            prec = f"{p:.1%} ({verdict})"
        else:
            prec = "n/a (no answers yet)"
        print(f"{tier:<10}{len(answers):>8}{y:>5}{n:>5}{blank:>7}{other:>7}  {prec}")
    print("Precision = y / (y + n); blank and other values are left out. Nothing was changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["export", "summary"])
    parser.add_argument("--force", action="store_true", help="export: overwrite a file that has answers")
    args = parser.parse_args()
    if args.mode == "export":
        export(args.force)
    else:
        summary()


if __name__ == "__main__":
    main()
