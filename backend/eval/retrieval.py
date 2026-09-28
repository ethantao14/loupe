"""Measure retrieval ranks on self-authored sanity-check sets, not benchmarks.

Run from backend: .venv/bin/python -m eval.retrieval [set names...]
"""

import json
import sys
from pathlib import Path

from app import embedding
from app.ranking import RECALL_TOP_K, RRF_K, fuse, rank

SETS = Path(__file__).parent / "sets"


def naive_rrf(
    bm25: list[tuple[str, float]], dense: list[tuple[str, float]]
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in (bm25, dense):
        for position, (fact, _) in enumerate(ranking, start=1):
            scores[fact] = scores.get(fact, 0.0) + 1 / (RRF_K + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def evaluate(path: Path, dense_available: bool) -> None:
    data = json.loads(path.read_text())
    facts = data["facts"]
    vectors = embedding.encode_documents(facts) if dense_available else []
    results: dict[str, list[tuple[int | None, str, str]]] = {"bm25": []}
    if dense_available:
        results.update({"dense": [], "naive_rrf": [], "fused": []})
    for case in data["cases"]:
        query = case["query"]
        target = facts[case["target"]]
        bm25 = rank(query, facts)
        systems = {"bm25": bm25}
        if dense_available:
            vector = embedding.encode_query(query)
            dense = sorted(
                [
                    (fact, sum(a * b for a, b in zip(vector, stored, strict=True)))
                    for fact, stored in zip(facts, vectors, strict=True)
                ],
                key=lambda item: item[1],
                reverse=True,
            )
            systems.update(dense=dense, naive_rrf=naive_rrf(bm25, dense), fused=fuse(bm25, dense))
        for name, ranking in systems.items():
            position = next(
                (index for index, (fact, _) in enumerate(ranking, start=1) if fact == target),
                None,
            )
            first = ranking[0][0] if ranking else "(no result)"
            results[name].append((position, query, first))

    top_k = RECALL_TOP_K
    print(f"\n{path.stem}\n{data['description']}")
    print(f"{'system':<12} {'top-1':>7} {'recall@3':>10} {f'recall@{top_k}':>10} {'MRR':>8}")
    for name, rows in results.items():
        positions = [position for position, _, _ in rows]
        total = len(rows)
        hits = f"{sum(position == 1 for position in positions)}/{total}"
        recall3 = sum(p is not None and p <= 3 for p in positions) / total
        recallk = sum(p is not None and p <= top_k for p in positions) / total
        mrr = sum(1 / p if p is not None else 0 for p in positions) / total
        print(f"{name:<12} {hits:>7} {recall3:>10.3f} {recallk:>10.3f} {mrr:>8.3f}")
    for name, rows in results.items():
        print(f"\n{name} top-1 misses:")
        misses = [(query, first) for position, query, first in rows if position != 1]
        for query, first in misses:
            truncated = first[:77] + "..." if len(first) > 80 else first
            print(f"  {query} -> {truncated}")
        if not misses:
            print("  (none)")


def main() -> None:
    paths = [SETS / f"{Path(name).stem}.json" for name in sys.argv[1:]] or sorted(
        SETS.glob("*.json")
    )
    reason = embedding.unavailable_reason()
    if reason is None:
        try:
            embedding.load()
        except RuntimeError as error:
            reason = str(error)
    if reason is not None:
        print(f"Embeddings unavailable: {reason}")
    for path in paths:
        evaluate(path, reason is None)


if __name__ == "__main__":
    main()
