"""Argon replay for demos - owner: Dev 1. **Demo branch only.**

A live chess run takes 30-60 minutes, nearly all of it waiting on Argon. For a live demo
and the video, this replays Argon's answers from one recorded real run instead of asking
Gemini again. Everything else runs for real: the plan is validated, every recorded tool
call is executed by the real dispatcher, every patch is applied to a fresh workspace and
the sandbox verifier decides every verdict. If the verifier disagrees with the recording,
the run says so; nothing here sets a status.

Record once, from a finished run, while the backend that ran it is up:

    uv run python -m app.agents.replay record run_70e126c3acf2

That reads the run's journal from the API and fetches each recorded interaction from
Gemini by id (a read: nothing is generated), then writes `demo/replays/<run_id>.json`.
Replay by setting `ARGON_REPLAY_FILE` to that file. The run, the plan and the status
chip then name the model as a replay of that run, so nobody mistakes it for a live call.

Ask (#123) has no journal to record from, so a question is recorded by asking it once,
live, and keeping Argon's turns:

    uv run python -m app.agents.replay record-ask repo_3852f5968630 "Where is checkmate detected?"

In the demo, the same question (case, spacing and a trailing `?` don't matter) replays
those turns; its searches and file reads still run, so the citations are real. Any other
question is refused with the list of recorded ones, never sent to Gemini.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings

PLAN = "plan"
REPORT = "report"
ASK = "ask:"


def unit_script(unit_id: str) -> str:
    return f"unit:{unit_id}"


def ask_script(question: str) -> str:
    """`ask:` + the question lower-cased, spacing collapsed, trailing punctuation dropped."""
    return ASK + " ".join(question.lower().split()).rstrip("?!. ")


def active() -> bool:
    return bool(get_settings().argon_replay_file)


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def recording() -> dict[str, Any]:
    return _load(str(Path(get_settings().argon_replay_file).expanduser()))


def model_label() -> str:
    """The model name to record on plans and runs, and to show on the status chip."""
    settings = get_settings()
    if not active():
        return settings.gemini_model
    source = recording()
    return f"{source.get('model', settings.gemini_model)} (replay of {source['source_run_id']})"


class Cursor:
    """One session's recorded turns, handed out in order."""

    def __init__(self, script: str) -> None:
        self.script = script
        self.turns = list(recording().get("scripts", {}).get(script, []))
        self.position = 0

    def next(self):
        from app.agents.gemini_client import ModelUnavailable, ToolCall, Turn

        if self.position >= len(self.turns):
            if self.script.startswith(ASK) and not self.turns:
                asked = list(recording().get("questions", {}).values())
                raise ModelUnavailable(
                    "this demo build answers only the questions recorded for it: "
                    + ("; ".join(f'"{q}"' for q in asked) if asked else "none")
                )
            # Never fall back to a live call: the point of replay is spending nothing.
            raise ModelUnavailable(
                f"the replay of {recording()['source_run_id']} has no turn "
                f"{self.position + 1} for {self.script}"
            )
        raw = self.turns[self.position]
        self.position += 1
        text = raw.get("text", "")
        if self.script == REPORT:
            # The narrative names the recorded run; say so on this run's report.
            text = f"_Narrative replayed from {recording()['source_run_id']}._\n\n{text}"
        return Turn(
            id=raw["id"],
            text=text,
            calls=[ToolCall(c["id"], c["name"], c.get("arguments")) for c in raw.get("calls", [])],
        )


# --------------------------------------------------------------------------
# recording
# --------------------------------------------------------------------------

def _turn_record(interaction: Any) -> dict[str, Any]:
    from app.agents.gemini_client import parse_turn

    return _turn_dict(parse_turn(interaction))


def _turn_dict(turn: Any) -> dict[str, Any]:
    return {
        "id": turn.id,
        "text": turn.text,
        "calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.calls],
    }


async def build_recording(run, plan, events, report, fetch) -> dict[str, Any]:
    """The replay file for a finished run. `fetch(id)` returns a raw interaction."""
    scripts: dict[str, list[dict[str, Any]]] = {}

    # The plan's interaction id is the acknowledgement turn; walk back to the first.
    chain = []
    interaction_id = plan.get("interaction_id")
    while interaction_id:
        interaction = await fetch(interaction_id)
        data = interaction if isinstance(interaction, dict) else interaction.model_dump()
        chain.append(_turn_record(data))
        interaction_id = data.get("previous_interaction_id")
    scripts[PLAN] = list(reversed(chain))

    for event in sorted(events, key=lambda e: e["sequence"]):
        if event["event_type"] != "agent_turn" or not event.get("unit_id"):
            continue
        interaction = await fetch(event["payload"]["interaction_id"])
        scripts.setdefault(unit_script(event["unit_id"]), []).append(_turn_record(interaction))

    narrative = (report or {}).get("narrative")
    if narrative:
        scripts[REPORT] = [{"id": f"replay_report_{run['run_id']}", "text": narrative, "calls": []}]

    return {
        "source_run_id": run["run_id"],
        "source_plan_id": plan["plan_id"],
        "repository_id": run["repository_id"],
        "model": run.get("model"),
        "verdict": (report or {}).get("verdict", run.get("state")),
        "recorded_at": datetime.now(UTC).isoformat(),
        "scripts": scripts,
    }


async def record(run_id: str, api: str, out: Path) -> Path:
    import httpx

    from app.agents.gemini_client import GeminiClient

    async with httpx.AsyncClient(base_url=api, timeout=60) as http:
        run = (await http.get(f"/runs/{run_id}")).raise_for_status().json()
        plan = (await http.get(f"/plans/{run['plan_id']}")).raise_for_status().json()
        events, after = [], 0
        while True:
            page = (await http.get(
                f"/runs/{run_id}/events", params={"after_sequence": after, "limit": 500}
            )).raise_for_status().json()
            page = page if isinstance(page, list) else page.get("events", [])
            if not page:
                break
            events.extend(page)
            after = page[-1]["sequence"]
        response = await http.get(f"/runs/{run_id}/report")
        report = response.json() if response.status_code == 200 else None

    client = GeminiClient()
    try:
        recording = await build_recording(
            run, plan, events, report, lambda i: client.client.aio.interactions.get(i)
        )
    finally:
        await client.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recording, indent=1, ensure_ascii=False), encoding="utf-8")
    turns = sum(len(t) for t in recording["scripts"].values())
    print(f"recorded {turns} turns over {len(recording['scripts'])} scripts to {out}")
    return out


class _RecordingClient:
    """A live client that keeps every turn it returns."""

    def __init__(self, live) -> None:
        self.live = live
        self.model = live.model
        self.thinking_level = live.thinking_level
        self.turns: list[dict[str, Any]] = []

    async def turn(self, *args, **kwargs):
        turn = await self.live.turn(*args, **kwargs)
        self.turns.append(_turn_dict(turn))
        return turn

    async def close(self) -> None:
        await self.live.close()


async def capture_ask(repository_id: str, question: str, live) -> tuple[list[dict], Any]:
    """Ask once through `live` (a real client); return its turns and the answer."""
    from app.agents.ask import answer_question

    recorder = _RecordingClient(live)
    try:
        answer = await answer_question(repository_id, question, client=recorder)
    finally:
        await recorder.close()
    return recorder.turns, answer


def save_ask(path: Path, question: str, turns: list[dict]) -> None:
    """Add (or replace) one recorded question in a recording file."""
    recording = json.loads(path.read_text(encoding="utf-8"))
    script = ask_script(question)
    recording.setdefault("scripts", {})[script] = turns
    recording.setdefault("questions", {})[script] = question
    path.write_text(json.dumps(recording, indent=1, ensure_ascii=False), encoding="utf-8")


async def record_ask(repository_id: str, question: str, out: Path) -> Path:
    from app.agents.gemini_client import GeminiClient
    from app.persistence import db

    settings = get_settings()
    settings.argon_replay_file = ""  # recording must ask the live model
    await db.connect(settings)
    try:
        turns, answer = await capture_ask(repository_id, question, GeminiClient())
    finally:
        await db.disconnect()
    if not turns or not answer.answer:
        raise SystemExit(f"nothing recorded for {question!r}")
    save_ask(out, question, turns)
    print(f"recorded {len(turns)} turns for {question!r} (grounded={answer.grounded}, "
          f"{len(answer.citations)} citations) to {out}")
    return out


def main(argv: list[str]) -> int:
    from app.ingestion import repo_root

    replays = repo_root() / "demo" / "replays"
    if len(argv) >= 3 and argv[0] == "record-ask":
        out = Path(argv[3]) if len(argv) > 3 else replays / "run_c86aff1bea77.json"
        asyncio.run(record_ask(argv[1], argv[2], out))
        return 0
    if len(argv) >= 2 and argv[0] == "record":
        run_id = argv[1]
        out = Path(argv[2]) if len(argv) > 2 else replays / f"{run_id}.json"
        api = argv[3] if len(argv) > 3 else "http://localhost:8000/api/v1"
        asyncio.run(record(run_id, api, out))
        return 0
    print("usage: python -m app.agents.replay record <run_id> [out.json] [api]\n"
          '       python -m app.agents.replay record-ask <repo_id> "<question>" [out.json]')
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
