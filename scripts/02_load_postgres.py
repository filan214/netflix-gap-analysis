"""Load cleaned Netflix data and filtered IMDb data into PostgreSQL.

Drops and recreates schemas netflix and imdb (derived data, safe to wipe), then
bulk-loads with COPY, builds title_norm / imdb.title_names / imdb.title_genres,
creates indexes, runs ANALYZE and prints row counts plus the P2 checks.
Everything runs in one transaction. Reloading wipes netflix.title_match:
re-run Phase 3 and Phase 4 afterwards.

Run from the repo root:
    python scripts/02_load_postgres.py
"""
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

from lib.normalize import normalize_title

CLEAN = Path("data/clean")
SQL = Path("sql")
EXPECTED_NETFLIX_TITLES = 8807
EXPECTED_INDONESIA = 90


def read_csv(name):
    # keep_default_na=False so titles like "NA" or "None" stay text; only '' is null.
    return pd.read_csv(CLEAN / name, dtype=str, keep_default_na=False, na_values=[""])


def to_int(series):
    return pd.to_numeric(series).astype("Int64")


def copy_df(cur, table, df):
    cols = list(df.columns)
    df = df.astype(object).where(df.notna(), None)
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in df.itertuples(index=False, name=None):
            cp.write_row(row)


def scalar(cur, sql):
    return cur.execute(sql).fetchone()[0]


def build_netflix():
    titles = read_csv("netflix_titles_clean.csv").rename(columns={"cast": "cast_members"})
    for col in ["release_year", "duration_min", "seasons", "year_added"]:
        titles[col] = to_int(titles[col])
    titles.insert(titles.columns.get_loc("title") + 1, "title_norm",
                  titles["title"].map(normalize_title))
    return titles, read_csv("title_country.csv"), read_csv("title_genre.csv")


def build_imdb():
    raw = read_csv("imdb_filtered.csv")
    titles = pd.DataFrame({
        "tconst": raw["tconst"],
        "title_type": raw["titleType"],
        "primary_title": raw["primaryTitle"],
        "original_title": raw["originalTitle"],
        "start_year": to_int(raw["startYear"]),
        "end_year": to_int(raw["endYear"]),
        "runtime_min": to_int(raw["runtimeMinutes"]),
        "genres": raw["genres"],
        "avg_rating": raw["averageRating"],
        "num_votes": to_int(raw["numVotes"]),
    })

    names = pd.concat([
        pd.DataFrame({"tconst": titles["tconst"], "name_norm": titles["primary_title"].map(normalize_title)}),
        pd.DataFrame({"tconst": titles["tconst"], "name_norm": titles["original_title"].map(normalize_title)}),
    ])
    names = names[names["name_norm"] != ""].drop_duplicates().sort_values(["tconst", "name_norm"])

    genres = titles[["tconst", "genres"]].dropna()
    genres = genres.assign(genre=genres["genres"].str.split(",")).explode("genre")[["tconst", "genre"]]
    genres = genres[genres["genre"].str.strip() != ""].drop_duplicates()

    return titles, names, genres


def main():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    nf_titles, nf_country, nf_genre = build_netflix()
    im_titles, im_names, im_genres = build_imdb()

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS netflix CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS imdb CASCADE")
        cur.execute((SQL / "01_schema.sql").read_text(encoding="utf-8"))

        copy_df(cur, "imdb.titles", im_titles)
        copy_df(cur, "imdb.title_names", im_names)
        copy_df(cur, "imdb.title_genres", im_genres)
        copy_df(cur, "netflix.titles", nf_titles)
        copy_df(cur, "netflix.title_country", nf_country)
        copy_df(cur, "netflix.title_genre", nf_genre)

        cur.execute((SQL / "02_indexes.sql").read_text(encoding="utf-8"))
        cur.execute("ANALYZE netflix.titles, netflix.title_country, netflix.title_genre, "
                    "netflix.title_match, imdb.titles, imdb.title_names, imdb.title_genres")

        tables = ["netflix.titles", "netflix.title_country", "netflix.title_genre",
                  "netflix.title_match", "imdb.titles", "imdb.title_names", "imdb.title_genres",
                  "mart.params"]
        counts = {t: scalar(cur, f"SELECT count(*) FROM {t}") for t in tables}
        indonesia = scalar(cur, "SELECT count(*) FROM netflix.title_country WHERE country = 'Indonesia'")
        null_rating = scalar(cur, "SELECT count(*) FROM imdb.titles WHERE avg_rating IS NULL OR num_votes IS NULL")
        empty_names = scalar(cur, "SELECT count(*) FROM imdb.title_names WHERE name_norm = ''")
        empty_norm = scalar(cur, "SELECT count(*) FROM netflix.titles WHERE title_norm = ''")

    print("=== 02_load_postgres row counts ===")
    for t, n in counts.items():
        print(f"  {t:<24}{n:>10,}")

    checks = [
        ("netflix.titles = 8,807", counts["netflix.titles"] == EXPECTED_NETFLIX_TITLES),
        (f"title_country = CSV rows ({len(nf_country):,})", counts["netflix.title_country"] == len(nf_country)),
        (f"title_genre = CSV rows ({len(nf_genre):,})", counts["netflix.title_genre"] == len(nf_genre)),
        (f"Indonesia rows in title_country = {EXPECTED_INDONESIA} (got {indonesia})", indonesia == EXPECTED_INDONESIA),
        (f"imdb.titles = CSV rows ({len(im_titles):,})", counts["imdb.titles"] == len(im_titles)),
        (f"no null avg_rating / num_votes (got {null_rating})", null_rating == 0),
        (f"no empty name_norm in imdb.title_names (got {empty_names})", empty_names == 0),
        ("mart.params has one row", counts["mart.params"] == 1),
    ]
    print("=== P2 checks ===")
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"  [INFO] Netflix titles with empty title_norm: {empty_norm}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
