"""Filter the raw IMDb dumps down to the title types the project can match.

Reads  data/raw/title.basics*.tsv and data/raw/title.ratings*.tsv (never modified).
Writes data/clean/imdb_filtered.csv.

Kept: titleType in KEEP_TYPES, isAdult = 0, startYear present, and a rating row
(inner join with title.ratings). Run from the repo root:
    python scripts/01_filter_imdb.py
"""
import csv
import glob
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
OUT = Path("data/clean/imdb_filtered.csv")
KEEP_TYPES = ["movie", "tvMovie", "tvSpecial", "tvSeries", "tvMiniSeries"]
CHUNK = 500_000


def find_one(pattern):
    hits = sorted(glob.glob(str(RAW / pattern)))
    if len(hits) != 1:
        raise SystemExit(f"Expected exactly one file for {RAW / pattern}, found {hits}")
    return hits[0]


def read_tsv(path, **kw):
    # IMDb TSVs use \N for null and contain bare quote characters in titles.
    return pd.read_csv(path, sep="\t", na_values="\\N", keep_default_na=False,
                       quoting=csv.QUOTE_NONE, dtype=str, **kw)


def main():
    basics_path = find_one("title.basics*.tsv")
    ratings_path = find_one("title.ratings*.tsv")

    usecols = ["tconst", "titleType", "primaryTitle", "originalTitle", "isAdult",
               "startYear", "endYear", "runtimeMinutes", "genres"]
    rows_read = 0
    parts = []
    for chunk in read_tsv(basics_path, usecols=usecols, chunksize=CHUNK):
        rows_read += len(chunk)
        chunk = chunk[chunk["titleType"].isin(KEEP_TYPES)]
        parts.append(chunk)
    basics = pd.concat(parts, ignore_index=True)
    n_type = len(basics)

    basics = basics[basics["isAdult"] == "0"]
    n_not_adult = len(basics)
    basics = basics[basics["startYear"].notna()]
    n_with_year = len(basics)

    ratings = read_tsv(ratings_path)
    df = basics.merge(ratings, on="tconst", how="inner")
    df = df.drop(columns="isAdult")
    for col in ["startYear", "endYear", "runtimeMinutes", "numVotes"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["averageRating"] = pd.to_numeric(df["averageRating"], errors="coerce")
    df = df.sort_values("tconst").reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)

    print("=== 01_filter_imdb summary ===")
    print(f"basics file        : {basics_path}")
    print(f"ratings file       : {ratings_path}")
    print(f"basics rows read   : {rows_read:,}")
    print(f"kept title types   : {n_type:,}  {KEEP_TYPES}")
    print(f"after isAdult = 0  : {n_not_adult:,}")
    print(f"with startYear     : {n_with_year:,}")
    print(f"ratings rows       : {len(ratings):,}")
    print(f"output rows        : {len(df):,}  -> {OUT}")
    print(f"endYear non-null   : {int(df['endYear'].notna().sum()):,}")
    print("by titleType:")
    for t, n in df["titleType"].value_counts().items():
        print(f"  {t:<13}{n:>9,}")
    print(f"columns            : {list(df.columns)}")


if __name__ == "__main__":
    main()
