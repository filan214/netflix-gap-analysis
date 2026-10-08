"""Match audit: export a sample to check by hand, then summarize precision per tier.

    python scripts/03_audit.py export                       # writes docs/match_audit_sample.csv
    python scripts/03_audit.py review                       # rows to check by hand first
    python scripts/03_audit.py summary                      # precision from human answers only
    python scripts/03_audit.py summary --use-ai-for-blank   # blank `correct` falls back to ai_label

export samples up to 30 matches per built tier with a fixed seed and refuses to
overwrite a file that already has answers in `correct` (pass --force to do it anyway).
Existing ai_label / ai_evidence values are carried over by (show_id, tconst).
review and summary only read the file; they change nothing in the database or on disk.

`correct` is the human answer (y or n). `ai_label` (y / n / unsure) and `ai_evidence`
are an AI pre-check that only guides which rows to check by hand first.
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
N_REVIEW_Y = 10
PRECISION_BAR = 0.90
COLUMNS = ["show_id", "netflix_title", "netflix_year", "netflix_type", "netflix_country",
           "netflix_director", "netflix_description", "netflix_genres", "netflix_duration",
           "imdb_title", "imdb_original_title", "imdb_start_year", "imdb_end_year", "imdb_type",
           "imdb_genres", "imdb_runtime_min",
           "tconst", "imdb_url", "tier", "candidate_count", "ai_label", "ai_evidence", "correct"]
AI_LABELS = {"y", "n", "unsure"}


def read_audit():
    # utf-8-sig: the export writes a BOM so Excel shows accents; tolerate files without one.
    with AUDIT.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def human(r):
    return (r.get("correct") or "").strip().lower()


def ai(r):
    return (r.get("ai_label") or "").strip().lower()


def export(force):
    from lib.db import connect

    previous_ai = {}
    if AUDIT.exists():
        old = read_audit()
        filled = [r for r in old if human(r)]
        if filled and not force:
            sys.exit(f"{AUDIT} already has {len(filled)} filled answers. "
                     "Use --force to overwrite it.")
        previous_ai = {(r["show_id"], r["tconst"]): (r.get("ai_label", ""), r.get("ai_evidence", ""))
                       for r in old}

    rng = random.Random(SEED)
    sample = []
    with connect() as conn:
        for tier in TIERS:
            rows = conn.execute("""
                SELECT n.show_id, n.title, n.release_year, n.type, coalesce(n.country, 'Unknown'),
                       n.director, left(n.description, 200), n.listed_in, n.duration,
                       i.primary_title, i.original_title, i.start_year, i.end_year, i.title_type,
                       i.genres, i.runtime_min,
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

    tconst_at = COLUMNS.index("tconst")
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in sample:
            w.writerow([*r, *previous_ai.get((r[0], r[tconst_at]), ("", "")), ""])
    print(f"Wrote {len(sample)} rows to {AUDIT} (seed {SEED}). Fill `correct` with y or n.")


def load_or_exit():
    if not AUDIT.exists():
        sys.exit(f"{AUDIT} not found. Run: python scripts/03_audit.py export")
    return read_audit()


def summary(use_ai_for_blank):
    rows = load_or_exit()
    mode = "human answers, blank -> ai_label" if use_ai_for_blank else "human answers only"
    print(f"=== Audit precision per tier ({AUDIT}; {mode}) ===")
    print(f"{'tier':<10}{'sampled':>8}{'human y/n':>11}{'AI y/n':>8}{'unsure':>8}{'blank':>7}{'other':>7}  precision")
    totals = {"human": 0, "ai": 0}
    for tier in TIERS:
        tier_rows = [r for r in rows if r["tier"] == tier]
        y = n = h_used = a_used = unsure = blank = other = 0
        for r in tier_rows:
            label, source = human(r), "human"
            if not label and use_ai_for_blank:
                label, source = ai(r), "ai"
            if label in ("y", "n"):
                y += label == "y"
                n += label == "n"
                h_used += source == "human"
                a_used += source == "ai"
            elif label == "unsure":
                unsure += 1
            elif label == "":
                blank += 1
            else:
                other += 1
        totals["human"] += h_used
        totals["ai"] += a_used
        if y + n:
            p = y / (y + n)
            verdict = "meets 90%" if p >= PRECISION_BAR else "BELOW 90% -> drop from accepted_tiers"
            prec = f"{p:.1%} = {y}/{y + n} ({verdict})"
        else:
            prec = "n/a (no answers yet)"
        print(f"{tier:<10}{len(tier_rows):>8}{h_used:>11}{a_used:>8}{unsure:>8}{blank:>7}{other:>7}  {prec}")
    print(f"Labels used: {totals['human']} human, {totals['ai']} AI.")
    print("Precision = y / (y + n); unsure, blank and other values are left out. Nothing was changed.")


def review():
    rows = load_or_exit()
    missing = [r["show_id"] for r in rows if ai(r) not in AI_LABELS]
    if missing:
        print(f"Warning: {len(missing)} rows have no valid ai_label: {', '.join(missing)}")

    def show(r):
        h = human(r) or "-"
        return (f"  {r['show_id']:<6} {r['tier']:<9} ai={ai(r):<7} human={h:<2} "
                f"{r['netflix_title']} ({r['netflix_year']}, {r['netflix_type']}) -> "
                f"{r['imdb_title']} ({r['imdb_start_year']}, {r['imdb_type']}) {r['imdb_url']}\n"
                f"         {r['ai_evidence']}")

    flagged = [r for r in rows if ai(r) in ("n", "unsure")]
    print(f"=== Check by hand: ai_label n or unsure ({len(flagged)}) ===")
    for r in flagged:
        print(show(r))
    yes = [r for r in rows if ai(r) == "y"]
    spot = random.Random(SEED).sample(yes, min(N_REVIEW_Y, len(yes)))
    spot.sort(key=lambda r: (TIERS.index(r["tier"]), int(r["show_id"][1:])))
    print(f"\n=== Spot-check: {len(spot)} random ai_label y of {len(yes)} (seed {SEED}) ===")
    for r in spot:
        print(show(r))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["export", "review", "summary"])
    parser.add_argument("--force", action="store_true", help="export: overwrite a file that has answers")
    parser.add_argument("--use-ai-for-blank", action="store_true",
                        help="summary: count blank `correct` rows as their ai_label")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.mode == "export":
        export(args.force)
    elif args.mode == "review":
        review()
    else:
        summary(args.use_ai_for_blank)


if __name__ == "__main__":
    main()
