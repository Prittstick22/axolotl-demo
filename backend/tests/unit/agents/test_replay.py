"""Demo replay of a recorded Argon run (demo branch only). Offline: no Gemini, no network."""

import json
from unittest.mock import AsyncMock

import pytest

from app.agents import health, replay, sessions
from app.agents.contexts import UnitSessionContext
from app.agents.gemini_client import GeminiClient, ModelUnavailable
from app.config import get_settings
from app.models.contracts import MigrationTarget, MigrationUnit, PatchAck

pytestmark = pytest.mark.anyio


def interaction(interaction_id, *, calls=(), text="", previous=None):
    steps = [
        {"type": "function_call", "id": f"call_{n}", "name": name, "arguments": args}
        for n, (name, args) in enumerate(calls)
    ]
    if text:
        steps.append({"type": "text", "text": text})
    return {
        "id": interaction_id,
        "status": "requires_action" if calls else "completed",
        "steps": steps,
        "previous_interaction_id": previous,
    }


PATCH = {
    "files": [{"path": "chess.py", "new_content": "print('board')\n"}],
    "summary": "Modernise print",
    "rationale": "Same output",
}
ORDER = {"suggested_order": ["unit_chess"], "rationale": "one unit", "risks": [],
         "coverage_gaps": []}

INTERACTIONS = {
    "plan_1": interaction("plan_1", calls=[("submit_plan", ORDER)]),
    "plan_2": interaction("plan_2", text="Accepted.", previous="plan_1"),
    "u1": interaction("u1", calls=[("propose_patch", PATCH)]),
    "u2": interaction("u2", calls=[("run_verification", {})]),
}
EVENTS = [
    {"sequence": 4, "event_type": "agent_turn", "unit_id": "unit_chess",
     "payload": {"interaction_id": "u2"}},
    {"sequence": 2, "event_type": "agent_turn", "unit_id": "unit_chess",
     "payload": {"interaction_id": "u1"}},
    {"sequence": 3, "event_type": "agent_tool_call", "unit_id": "unit_chess", "payload": {}},
]
RUN = {"run_id": "run_recorded", "repository_id": "repo_x", "model": "gemini-4-argon",
       "state": "completed"}


async def fetch(interaction_id):
    return INTERACTIONS[interaction_id]


async def test_a_recording_holds_each_session_s_turns_in_order():
    recording = await replay.build_recording(
        RUN, {"plan_id": "plan_x", "interaction_id": "plan_2"}, EVENTS,
        {"verdict": "completed", "narrative": "Two units passed."}, fetch,
    )

    scripts = recording["scripts"]
    assert [t["id"] for t in scripts["plan"]] == ["plan_1", "plan_2"]
    assert [t["id"] for t in scripts["unit:unit_chess"]] == ["u1", "u2"]
    assert scripts["unit:unit_chess"][0]["calls"][0]["arguments"] == PATCH
    assert scripts["report"][0]["text"] == "Two units passed."
    assert recording["source_run_id"] == "run_recorded"


@pytest.fixture
async def replaying(tmp_path, monkeypatch):
    recording = await replay.build_recording(
        RUN, {"plan_id": "plan_x", "interaction_id": "plan_2"}, EVENTS, None, fetch,
    )
    path = tmp_path / "run_recorded.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    settings = get_settings()
    monkeypatch.setattr(settings, "argon_replay_file", str(path))
    monkeypatch.setattr(settings, "argon_replay_delay_seconds", 0)
    monkeypatch.setattr(settings, "gemini_api_key", "")  # replay needs no key
    replay._load.cache_clear()
    health.reset_cache()
    yield path
    replay._load.cache_clear()
    health.reset_cache()


class Controller:
    def __init__(self):
        self.verified = False
        self.patches = []
        self.emit = AsyncMock()
        self.get_counterexamples = AsyncMock(return_value=[])

    async def submit_patch(self, patch):
        self.patches.append(patch)
        return PatchAck(accepted=True, workspace_revision="rev_new")

    async def run_verification(self):
        self.verified = True  # the real verifier decides this in a run
        return {"ok": True, "gates": []}

    def is_verified(self):
        return self.verified

    def patch_attempts_remaining(self):
        return 3 - len(self.patches)


def context(unit_id="unit_chess"):
    return UnitSessionContext(
        run_id="run_new", repository_id="repo_x",
        unit=MigrationUnit(unit_id=unit_id, module_ids=["module_chess"],
                           file_paths=["chess.py"], depends_on_unit_ids=[],
                           dependant_unit_ids=[]),
        target=MigrationTarget(target_id="python2_to_3", label="Python 2 to 3",
                               supported=True, description=""),
        plan_notes="", max_patch_attempts=3, max_tool_calls=25,
    )


async def test_a_replayed_session_runs_the_recorded_tool_calls_for_real(replaying):
    controller = Controller()

    outcome = await sessions.run_unit_session(context(), controller)

    assert outcome.ended_because == "verified"
    assert outcome.interaction_ids == ["u1", "u2"]
    assert controller.patches[0].files[0].new_content == "print('board')\n"


async def test_a_session_with_no_recording_fails_instead_of_calling_gemini(replaying):
    outcome = await sessions.run_unit_session(context("unit_unrecorded"), Controller())

    assert outcome.ended_because == "error"
    assert "has no turn 1 for unit:unit_unrecorded" in outcome.final_message


async def test_the_replayed_plan_is_the_recorded_one(replaying):
    client = GeminiClient(script=replay.PLAN)
    first = await client.turn("ignored", instruction="", tools=[])
    second = await client.turn("ignored", instruction="", tools=[])
    assert first.calls[0].name == "submit_plan"
    assert first.calls[0].arguments == ORDER
    assert second.text == "Accepted." and not second.calls
    with pytest.raises(ModelUnavailable):
        await client.turn("ignored", instruction="", tools=[])
    await client.close()


async def test_replay_is_labelled_wherever_the_model_is_named(replaying):
    assert replay.model_label() == "gemini-4-argon (replay of run_recorded)"
    status = await health.gemini_status(use_cache=False)
    assert status["reachable"] is True
    assert status["model"] == "gemini-4-argon (replay of run_recorded)"
    assert "no Gemini calls" in status["detail"]


async def test_a_replayed_report_says_whose_narrative_it_is(tmp_path, monkeypatch):
    recording = await replay.build_recording(
        RUN, {"plan_id": "plan_x", "interaction_id": "plan_2"}, EVENTS,
        {"narrative": "Two units passed."}, fetch,
    )
    path = tmp_path / "r.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "argon_replay_file", str(path))
    monkeypatch.setattr(get_settings(), "argon_replay_delay_seconds", 0)
    replay._load.cache_clear()
    try:
        text = await sessions.narrate_report({"run_id": "run_new"})
    finally:
        replay._load.cache_clear()
    assert text.startswith("_Narrative replayed from run_recorded._")
    assert text.endswith("Two units passed.")


def test_live_mode_is_unchanged_without_a_replay_file():
    assert not replay.active()
    assert replay.model_label() == get_settings().gemini_model
