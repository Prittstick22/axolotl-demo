"""The demo seed (#138, demo branch only). Offline: no MongoDB, no network."""

import zipfile

import pytest

from app import demo_seed
from app.config import get_settings

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("uri", [
    "mongodb://localhost:27017/?directConnection=true",
    "mongodb://127.0.0.1:27017",
    "mongodb://user:pass@localhost:27017/axolotl",
])
def test_a_local_mongodb_is_local(uri):
    assert demo_seed.is_local(uri)


@pytest.mark.parametrize("uri", [
    "mongodb+srv://user:pass@cluster0.example.mongodb.net/?retryWrites=true",
    "mongodb://db.example.com:27017",
    "mongodb://localhost:27017,db.example.com:27017",
    "",
])
def test_anything_else_is_not(uri):
    assert not demo_seed.is_local(uri)


async def test_load_refuses_the_team_cluster_before_touching_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "mongodb_uri", "mongodb+srv://u:p@cluster0.x.mongodb.net/")
    with pytest.raises(SystemExit, match="not a MongoDB on this machine"):
        await demo_seed.load(tmp_path)  # no seed files needed: it stops first


def test_the_seed_carries_chess_and_the_recorded_run_only():
    selected = demo_seed.filters()
    assert selected["code_chunks"] == {"repository_id": "repo_3852f5968630"}
    assert selected["module_docs"] == {"repository_id": "repo_3852f5968630"}
    assert selected["run_events"] == {"run_id": "run_c86aff1bea77"}
    assert selected["migration_plans"] == {"plan_id": "plan_fcff6aced2f5"}
    assert "artefacts" not in selected  # absolute paths on the recording machine


def test_the_workspace_zip_leaves_out_the_case_inputs(tmp_path):
    run = tmp_path / "run"
    (run / "rev_1" / "local_chess").mkdir(parents=True)
    (run / "rev_1" / "local_chess" / "cli.py").write_text("x = 1\n", encoding="utf-8")
    (run / "cases").mkdir()
    (run / "cases" / "baseline.json").write_text("[held-out inputs]", encoding="utf-8")

    out = tmp_path / "workspace.zip"
    assert demo_seed.write_workspace_zip(run, out) == 1
    assert zipfile.ZipFile(out).namelist() == ["rev_1/local_chess/cli.py"]

    restored = tmp_path / "laptop" / "runs" / "run_x"
    assert demo_seed.restore_workspace(out, restored) == 1
    assert (restored / "rev_1" / "local_chess" / "cli.py").read_text(encoding="utf-8") == "x = 1\n"


def test_restore_never_writes_outside_the_run_folder(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escape.py", "boom")
    with pytest.raises(ValueError, match="outside"):
        demo_seed.restore_workspace(bad, tmp_path / "runs" / "run_x")
    assert not (tmp_path / "runs" / "escape.py").exists()
