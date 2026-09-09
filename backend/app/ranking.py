import math
import re
from collections import Counter
from collections.abc import Sequence

K1 = 1.5  # Controls how quickly repeated term frequency saturates.
B = 0.75  # Controls how strongly document length normalises term frequency.
STOP_WORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are aren as at
    be because been before being below between both but by
    can cannot could couldn
    did didn do does doesn doing don down during
    each few for from further
    had hadn has hasn have haven having he her here hers herself him himself his how
    i if in into is isn it its itself just know
    ll me might mightn more most must mustn my myself
    needn no nor not now of off on once only or other ought our ours ourselves out over own
    re same shan she should shouldn so some such
    tell than that the their theirs them themselves then there these they this those
    through to too under until up ve very
    was wasn we were weren what when where which while who whom why will with won
    would wouldn you your yours yourself yourselves
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric characters, and drop common English words.

    Unicode letters and numbers are kept; there is no stemming or synonym expansion.
    """
    # Drop all single-character tokens, including digits; keep longer numeric tokens.
    return [
        token
        for token in re.split(r"[\W_]+", text.lower())
        if len(token) > 1 and token not in STOP_WORDS
    ]


def rank(query: str, documents: Sequence[str]) -> list[tuple[str, float]]:
    """Score with BM25, preserving input order for ties, including zero scores."""
    terms = sorted(set(tokenize(query)))
    if not documents or not terms:
        return [(document, 0.0) for document in documents]

    frequencies = [Counter(tokenize(document)) for document in documents]
    lengths = [sum(frequency.values()) for frequency in frequencies]
    average_length = sum(lengths) / len(documents)
    if not average_length:
        return [(document, 0.0) for document in documents]

    document_frequency: Counter[str] = Counter()
    for frequency in frequencies:
        document_frequency.update(frequency.keys())
    idf = {
        term: math.log1p(
            (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
        )
        for term in terms
    }

    scored: list[tuple[str, float]] = []
    for document, frequency, length in zip(documents, frequencies, lengths):
        normalisation = K1 * (1 - B + B * length / average_length)
        score = sum(
            (
                idf[term] * frequency[term] * (K1 + 1) / (frequency[term] + normalisation)
                for term in terms
                if frequency[term]
            ),
            start=0.0,
        )
        scored.append((document, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)
