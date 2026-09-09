import math

import pytest

from app.ranking import K1, B, rank, tokenize


def test_rare_term_outranks_common_term() -> None:
    documents = ["common apple", "common pear", "common plum", "rare peach", "unrelated"]

    ranked = rank("common rare", documents)

    assert ranked[0][0] == "rare peach"
    assert ranked[0][1] > ranked[1][1] > 0
    assert ranked[-1] == ("unrelated", 0.0)


def test_ties_preserve_input_order_and_are_deterministic() -> None:
    documents = ["Python blue", "Python red", "Python blue", "unrelated"]
    expected = rank("python blue red", documents)

    for _ in range(3):
        assert rank("red blue python", documents) == expected
    tied = rank("python", documents)
    assert [document for document, _ in tied] == documents
    assert tied[0][1] == tied[1][1] == tied[2][1]


@pytest.mark.parametrize("query", ["", "  ", "the and of", "!?!"])
def test_empty_query_scores_zero(query: str) -> None:
    assert rank(query, ["Python", "Rust"]) == [("Python", 0.0), ("Rust", 0.0)]


def test_empty_documents() -> None:
    assert rank("Python", []) == []
    assert rank("", []) == []
    assert rank("Python", ["", "the and", "!?"]) == [("", 0.0), ("the and", 0.0), ("!?", 0.0)]


def test_tokenize_case_punctuation_stop_words_and_numbers() -> None:
    assert tokenize("The PYTHON, and Rust! is at Café_42-version2.") == [
        "python",
        "rust",
        "café",
        "42",
        "version2",
    ]


def test_conversational_stop_words_do_not_match_unrelated_facts() -> None:
    corgi = "The user has a corgi named Biscuit"
    spending = "The user is cost sensitive about API spending"

    ranked = rank("tell me about Biscuit", [corgi, spending])

    assert ranked[0][0] == corgi
    assert ranked[0][1] > 0
    assert ranked[1] == (spending, 0.0)


def test_tokenize_possessive_drops_single_character_tokens() -> None:
    tokens = tokenize("the user's corgi")

    assert tokens == ["user", "corgi"]
    assert all(len(token) > 1 for token in tokens)


def test_tokenize_drops_single_characters_including_digits() -> None:
    assert tokenize("x 3 42 version2") == ["42", "version2"]


def test_bm25_formula_saturates_frequency_and_normalises_length() -> None:
    documents = ["python python", "python filler", "python filler filler filler", ""]
    scores = dict(rank("python", documents))
    idf = math.log1p(1.5 / 3.5)
    average_length = 2.0
    for document, frequency, length in zip(documents[:3], [2, 1, 1], [2, 2, 4]):
        expected = (
            idf * frequency * (K1 + 1) / (frequency + K1 * (1 - B + B * length / average_length))
        )
        assert scores[document] == pytest.approx(expected)
    assert scores[documents[1]] < scores[documents[0]] < 2 * scores[documents[1]]
    assert scores[documents[1]] > scores[documents[2]] > scores[""] == 0
