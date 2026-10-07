-- Secondary indexes, created after the bulk load (IMPLEMENTATION_GUIDE section 3.3).
-- Primary keys already index (tconst, ...) and (show_id, ...).

CREATE INDEX IF NOT EXISTS title_names_name_norm_idx    ON imdb.title_names (name_norm);
CREATE INDEX IF NOT EXISTS title_names_name_norm_trgm   ON imdb.title_names USING gin (name_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS titles_start_year_type_idx   ON imdb.titles (start_year, title_type);
CREATE INDEX IF NOT EXISTS title_genres_genre_idx       ON imdb.title_genres (genre);
CREATE INDEX IF NOT EXISTS title_country_country_idx    ON netflix.title_country (country);
CREATE INDEX IF NOT EXISTS title_genre_genre_idx        ON netflix.title_genre (genre);
