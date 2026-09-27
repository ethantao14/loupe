"""Record real turns from a running backend as replays for the frontend tour.

Run from backend with the API up on port 8000:
    .venv/bin/python -m scripts.record_replay ../frontend/app/demo/replays.json

Each replay keeps every streamed event with its arrival time, so the tour plays
back exactly what the model did, at the pace it did it. The recording visitor's
conversations and facts are deleted afterwards.
"""

import argparse
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API = "http://localhost:8000"


@dataclass
class Replay:
    id: str
    question: str
    # Setup turns run first and are not recorded; they give recall something to find.
    setup: list[str] = field(default_factory=list)


REPLAYS = [
    Replay(
        id="memory-and-fetch",
        setup=["Please remember that I have a corgi named Biscuit."],
        question=(
            "How much exercise does my dog need? Look it up on "
            "https://en.wikipedia.org/wiki/Pembroke_Welsh_Corgi and keep it short."
        ),
    ),
    Replay(
        id="run-python",
        question="What is the 40th Fibonacci number? Compute it with Python.",
    ),
    Replay(
        id="failure-recovery",
        question=(
            "Summarise https://loupe-demo-missing-page.invalid/ in one sentence. "
            "If that fails, tell me what went wrong."
        ),
    ),
]


def stream_turn(client: httpx.Client, question: str) -> list[dict]:
    events: list[dict] = []
    started = time.monotonic()
    name = None
    with client.stream("POST", "/api/messages/stream", json={"content": question}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: ") and name is not None:
                elapsed = round((time.monotonic() - started) * 1000)
                events.append({"at_ms": elapsed, "event": name, "data": json.loads(line[6:])})
                name = None
    if not events or events[-1]["event"] != "done":
        raise RuntimeError(f"Turn did not finish cleanly: {events[-1:] or 'no events'}")
    return events


def forget_everything(client: httpx.Client) -> None:
    for conversation in client.get("/api/conversations").json():
        client.delete(f"/api/conversations/{conversation['id']}").raise_for_status()
    for memory in client.get("/api/memories").json():
        client.delete(f"/api/memories/{memory['id']}").raise_for_status()


def main(output: Path) -> None:
    recorded = []
    for replay in REPLAYS:
        # A fresh visitor per replay, so one replay's facts never leak into another.
        headers = {"X-Visitor-Id": str(uuid.uuid4())}
        with httpx.Client(base_url=API, headers=headers, timeout=120) as client:
            try:
                for setup in replay.setup:
                    stream_turn(client, setup)
                events = stream_turn(client, replay.question)
            finally:
                forget_everything(client)
        recorded.append({"id": replay.id, "question": replay.question, "events": events})
        kinds = [e["data"]["kind"] for e in events if e["event"] == "step"]
        print(f"{replay.id}: {len(events)} events, steps {kinds}")
    output.write_text(json.dumps(recorded, indent=2) + "\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record demo replays from a running backend.")
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
