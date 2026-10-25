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


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    async def find_one(self, query, projection=None):
        return next((d for d in self.documents
                     if all(d.get(k) == v for k, v in query.items())), None)


async def test_if_missing_skips_only_when_both_the_data_and_the_files_are_here(
    tmp_path, monkeypatch
):
    """demo/start.ps1 runs `load --if-missing` on every start; it must reload the
    moment either half is missing."""
    data = {"repository_id": "repo_x", "run_id": "run_x"}
    database = {"repositories": FakeCollection([{"repository_id": "repo_x"}]),
                "migration_runs": FakeCollection([{"run_id": "run_x"}])}
    monkeypatch.setattr(get_settings(), "workspace_root", str(tmp_path))

    assert not await demo_seed._already_loaded(database, data)  # no files yet
    (tmp_path / "runs" / "run_x" / "rev_1").mkdir(parents=True)
    assert await demo_seed._already_loaded(database, data)

    database["migration_runs"] = FakeCollection([])  # files, but no run in the database
    assert not await demo_seed._already_loaded(database, data)
