import math

import pytest

from app.ranking import K1, RRF_K, B, fuse, rank, tokenize


def test_fusion_gates_zero_bm25_votes_that_would_demote_dense_hit() -> None:
    facts = ["Python preference", "Lives in Boston", "Has a corgi named Biscuit"]
    bm25 = rank("what breed is my dog", facts)
    dense = [(facts[2], 0.9), (facts[0], 0.3), (facts[1], 0.1)]
    assert all(score == 0 for _, score in bm25)
    naive: dict[str, float] = {}
    for ranking in (bm25, dense):
        for position, (fact, _) in enumerate(ranking, start=1):
            naive[fact] = naive.get(fact, 0) + 1 / (RRF_K + position)
    assert max(naive, key=lambda fact: naive[fact]) == facts[0]
    assert fuse(bm25, dense)[0] == (facts[2], 1 / (RRF_K + 1))


def test_fusion_combines_votes_and_keeps_unembedded_matches() -> None:
    result = fuse([("shared", 2), ("lexical", 1), ("ignored", 0)], [("shared", -0.1)], k=10)
    assert result == [("shared", 2 / 11), ("lexical", 1 / 12)]


def test_fusion_ties_are_stable() -> None:
    assert fuse([("first", 1)], [("second", 1)], k=1) == [("first", 0.5), ("second", 0.5)]
    assert fuse([], []) == []
    assert fuse([("ignored", 0), ("negative", -1)], []) == []


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
