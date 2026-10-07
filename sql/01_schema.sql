-- Schema for the Netflix catalog gap analysis (IMPLEMENTATION_GUIDE section 3.3).
-- scripts/02_load_postgres.py drops schemas netflix and imdb before running this file.
-- Schema mart and mart.params are created only if missing, so audit decisions
-- stored in mart.params survive a reload.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS imdb;
CREATE SCHEMA IF NOT EXISTS netflix;
CREATE SCHEMA IF NOT EXISTS mart;

-- ---------------------------------------------------------------- imdb
CREATE TABLE imdb.titles (
    tconst          text PRIMARY KEY,
    title_type      text NOT NULL
                    CHECK (title_type IN ('movie','tvMovie','tvSpecial','tvSeries','tvMiniSeries')),
    primary_title   text NOT NULL,
    original_title  text,
    start_year      int  NOT NULL,
    end_year        int,
    runtime_min     int  CHECK (runtime_min > 0),
    genres          text,
    avg_rating      numeric(3,1) NOT NULL CHECK (avg_rating BETWEEN 1.0 AND 10.0),
    num_votes       int  NOT NULL CHECK (num_votes >= 0),
    CHECK (end_year IS NULL OR end_year >= start_year)
);

CREATE TABLE imdb.title_names (
    tconst     text NOT NULL REFERENCES imdb.titles (tconst),
    name_norm  text NOT NULL CHECK (name_norm <> ''),
    PRIMARY KEY (tconst, name_norm)
);

CREATE TABLE imdb.title_genres (
    tconst  text NOT NULL REFERENCES imdb.titles (tconst),
    genre   text NOT NULL CHECK (genre <> ''),
    PRIMARY KEY (tconst, genre)
);

-- ---------------------------------------------------------------- netflix
CREATE TABLE netflix.titles (
    show_id               text PRIMARY KEY,
    type                  text NOT NULL CHECK (type IN ('Movie','TV Show')),
    title                 text NOT NULL,
    title_norm            text NOT NULL,          -- '' allowed, never joined on
    director              text,
    cast_members          text,                   -- CSV column "cast" (reserved word)
    country               text,
    date_added            date,
    release_year          int  NOT NULL CHECK (release_year BETWEEN 1900 AND 2100),
    rating                text NOT NULL,
    duration              text NOT NULL,
    listed_in             text NOT NULL,
    description           text,
    duration_min          int  CHECK (duration_min > 0),
    seasons               int  CHECK (seasons > 0),
    rating_group          text NOT NULL
                          CHECK (rating_group IN ('Kids','Teen/Family','Adult','Not Rated / Unknown')),
    year_added            int,
    added_before_release  boolean NOT NULL,
    country_known         boolean NOT NULL,
    CHECK (year_added IS NULL OR year_added = extract(year FROM date_added)::int)
);

CREATE TABLE netflix.title_country (
    show_id  text NOT NULL REFERENCES netflix.titles (show_id),
    country  text NOT NULL,
    PRIMARY KEY (show_id, country)
);

CREATE TABLE netflix.title_genre (
    show_id  text NOT NULL REFERENCES netflix.titles (show_id),
    genre    text NOT NULL,
    PRIMARY KEY (show_id, genre)
);

-- Filled by Phase 3. One row per Netflix title, including unmatched ones.
CREATE TABLE netflix.title_match (
    show_id          text PRIMARY KEY REFERENCES netflix.titles (show_id),
    tconst           text REFERENCES imdb.titles (tconst),
    match_tier       text NOT NULL
                     CHECK (match_tier IN ('exact','year_pm1','fuzzy','unmatched')),
    candidate_count  int  NOT NULL CHECK (candidate_count >= 0),
    ambiguous        boolean NOT NULL,
    similarity       numeric CHECK (similarity BETWEEN 0 AND 1),
    CHECK ((match_tier = 'unmatched') = (tconst IS NULL))
);

-- ---------------------------------------------------------------- mart
CREATE TABLE IF NOT EXISTS mart.params (
    id                   boolean PRIMARY KEY DEFAULT true CHECK (id),   -- forces a single row
    min_rating           numeric NOT NULL DEFAULT 7.0 CHECK (min_rating BETWEEN 1 AND 10),
    min_votes            int     NOT NULL DEFAULT 1000 CHECK (min_votes >= 0),
    min_n                int     NOT NULL DEFAULT 30 CHECK (min_n > 0),
    universe_start_year  int     NOT NULL DEFAULT 2000,
    accepted_tiers       text[]  NOT NULL DEFAULT '{exact,year_pm1}'
                         CHECK (accepted_tiers <@ ARRAY['exact','year_pm1','fuzzy']::text[])
);

INSERT INTO mart.params DEFAULT VALUES ON CONFLICT (id) DO NOTHING;
