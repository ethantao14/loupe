import json
from pathlib import Path

import pytest

SETS = sorted((Path(__file__).parents[1] / "eval" / "sets").glob("*.json"))


@pytest.mark.parametrize("path", SETS, ids=lambda path: path.stem)
def test_eval_set_structure(path: Path) -> None:
    data = json.loads(path.read_text())
    assert isinstance(data["description"], str) and data["description"].strip()
    facts = data["facts"]
    assert isinstance(facts, list) and facts
    assert all(isinstance(fact, str) and fact.strip() for fact in facts)
    assert len(facts) == len(set(facts))
    cases = data["cases"]
    assert isinstance(cases, list) and cases
    queries = []
    for case in cases:
        assert isinstance(case["query"], str) and case["query"].strip()
        assert type(case["target"]) is int
        assert 0 <= case["target"] < len(facts)
        queries.append(case["query"])
    assert len(queries) == len(set(queries))
