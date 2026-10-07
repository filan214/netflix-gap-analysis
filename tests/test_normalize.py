import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.normalize import normalize_title  # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    ("Amélie", "amelie"),
    ("Pokémon: Detective Pikachu", "pokemon detective pikachu"),
    ("Ça", "ca"),
    ("Straße", "strasse"),
])
def test_accents_and_casefold(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Love & Anarchy", "love and anarchy"),
    ("Tom&Jerry", "tom and jerry"),
])
def test_ampersand(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Mission: Impossible - Fallout", "mission impossible fallout"),
    ("Don't Look Up!", "don t look up"),
    ("  Spider-Man:   Far From Home  ", "spider man far from home"),
    ("WALL·E", "wall e"),
])
def test_punctuation_and_whitespace(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("1917", "1917"),
    ("Ocean's 11", "ocean s 11"),
    ("2001: A Space Odyssey", "2001 a space odyssey"),
    ("Area ⁵¹", "area 51"),  # superscripts fold to plain digits under NFKD
])
def test_digits(raw, expected):
    assert normalize_title(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("기생충", unicodedata.normalize("NFKD", "기생충")),  # Hangul syllables decompose to jamo
    ("千と千尋の神隠し", "千と千尋の神隠し"),
    ("Сталкер", "сталкер"),
    ("बाहुबली", "बहबल"),  # vowel signs are combining marks and are dropped, word stays whole
])
def test_non_latin_stays_non_empty(raw, expected):
    assert normalize_title(raw) == expected
    assert normalize_title(raw) != ""


@pytest.mark.parametrize("raw", ["?!", "#*@", "...", "   ", ""])
def test_all_symbol_title_is_empty(raw):
    assert normalize_title(raw) == ""


def test_lone_ampersand_is_not_symbol_only():
    assert normalize_title("#&*") == "and"


def test_none_is_empty():
    assert normalize_title(None) == ""


def test_leading_article_kept():
    assert normalize_title("The Irishman") == "the irishman"


def test_idempotent():
    s = "Amélie & Ça: 2001!"
    assert normalize_title(normalize_title(s)) == normalize_title(s)
