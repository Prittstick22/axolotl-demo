"""The team cluster's chess data, for a demo laptop with no Atlas access - owner: Dev 1.
**Demo branch only (#138).**

The demo laptop runs against its own local MongoDB (Atlas Local in Docker), because its
IP isn't on the team cluster's access list. This copies what the demo shows, so that
laptop's screens match the cluster's with no Gemini calls:

  chess (`repo_3852f5968630`)  graph, symbols, search chunks with their embeddings, the
                               behaviour cases, the index status and the 14 docs purposes.
  the recorded run             `run_c86aff1bea77` (the run the replay file came from):
                               its plan, run, journal, verifications, baseline, report.
  its files                    the run's revision trees, which the Changes, summary and
                               export read from disk. Not its `cases/` folder: that holds
                               the sandbox's copies of every case input, held-out ones
                               included, and no screen reads it.

Not copied: `artefacts`, whose records hold absolute paths on this machine (the export
zip is built on request from the trees), and the chess snapshot, which every laptop
rebuilds from its own checkout (#83).

    uv run python -m app.demo_seed export --workspace-root <the product's .axolotl_workspaces>
    uv run python -m app.demo_seed load

`load` refuses any MongoDB that isn't on this machine, so it can never write to the
team cluster. It replaces what it brings - the same documents deleted, then inserted -
so it can be run again safely.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from bson import json_util

from app.config import get_settings

REPOSITORY_ID = "repo_3852f5968630"
RUN_ID = "run_c86aff1bea77"
PLAN_ID = "plan_fcff6aced2f5"

REPOSITORY_COLLECTIONS = (
    "repositories", "symbols", "edges", "code_chunks", "behaviour_cases",
    "search_index_status", "module_docs", "docs_generation",
)
RUN_COLLECTIONS = (
    "migration_runs", "run_events", "verification_results", "baseline_outcomes",
    "counterexamples", "run_reports",
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EXCLUDED_FOLDERS = {"cases"}


def filters(repository_id: str = REPOSITORY_ID, run_id: str = RUN_ID,
            plan_id: str = PLAN_ID) -> dict[str, dict[str, Any]]:
    """Each collection the seed carries, and which of its documents."""
    selected: dict[str, dict[str, Any]] = {
        name: {"repository_id": repository_id} for name in REPOSITORY_COLLECTIONS
    }
    selected.update({name: {"run_id": run_id} for name in RUN_COLLECTIONS})
    selected["migration_plans"] = {"plan_id": plan_id}
    selected["counters"] = {"_id": run_id}  # the run's event sequence
    return selected


def seed_dir() -> Path:
    from app.ingestion import repo_root

    return repo_root() / "demo" / "seed"


def is_local(uri: str) -> bool:
    """True only for a MongoDB on this machine: never the team cluster."""
    parts = urlsplit(uri)
    if parts.scheme != "mongodb":
        return False  # mongodb+srv is always a remote cluster
    hosts = [h.rsplit(":", 1)[0].strip("[]") for h in parts.netloc.split("@")[-1].split(",")]
    return bool(hosts) and all(h in LOCAL_HOSTS for h in hosts)


def workspace_members(run_root: Path) -> list[Path]:
    """The run's files to ship: everything but the excluded folders."""
    return sorted(
        path for path in run_root.rglob("*")
        if path.is_file()
        and PurePosixPath(path.relative_to(run_root).as_posix()).parts[0]
        not in EXCLUDED_FOLDERS
    )


def write_workspace_zip(run_root: Path, out: Path) -> int:
    members = workspace_members(run_root)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in members:
            archive.write(path, path.relative_to(run_root).as_posix())
    return len(members)


def restore_workspace(archive_path: Path, run_root: Path) -> int:
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            # Never write outside the run's folder, whatever the archive says.
            target = (run_root / name).resolve()
            if run_root.resolve() not in target.parents:
                raise ValueError(f"refusing to extract {name!r} outside {run_root}")
        archive.extractall(run_root)
        return len(archive.namelist())


async def export(workspace_root: Path, out_dir: Path) -> None:
    from app.persistence import db

    await db.connect(get_settings())
    database = await db.get_db()
    collections = {}
    try:
        for name, query in filters().items():
            collections[name] = await database[name].find(query).to_list(None)
    finally:
        await db.disconnect()

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json_util.dumps(
        {"repository_id": REPOSITORY_ID, "run_id": RUN_ID, "plan_id": PLAN_ID,
         "collections": collections},
        json_options=json_util.CANONICAL_JSON_OPTIONS,
    )
    (out_dir / "chess-seed.json.gz").write_bytes(gzip.compress(payload.encode("utf-8")))
    files = write_workspace_zip(workspace_root / "runs" / RUN_ID,
                                out_dir / f"{RUN_ID}-workspace.zip")
    for name, documents in collections.items():
        print(f"{name:22} {len(documents)}")
    print(f"workspace files: {files} -> {out_dir}")


async def load(in_dir: Path) -> None:
    from app.persistence import db
    from app.sandbox.workspaces import workspace_root

    settings = get_settings()
    if not is_local(settings.mongodb_uri):
        raise SystemExit("refusing to load: MONGODB_URI is not a MongoDB on this machine. "
                         "The seed is for the demo laptop's local database only.")
    data = json_util.loads(gzip.decompress((in_dir / "chess-seed.json.gz").read_bytes()))

    await db.connect(settings)
    database = await db.get_db()
    try:
        for name, query in filters(data["repository_id"], data["run_id"],
                                   data["plan_id"]).items():
            await database[name].delete_many(query)
            documents = data["collections"].get(name, [])
            if documents:
                await database[name].insert_many(documents)
            print(f"{name:22} {len(documents)}")
    finally:
        await db.disconnect()

    files = restore_workspace(in_dir / f"{data['run_id']}-workspace.zip",
                              workspace_root() / "runs" / data["run_id"])
    print(f"workspace files: {files}, into {workspace_root() / 'runs' / data['run_id']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.demo_seed")
    sub = parser.add_subparsers(dest="command", required=True)
    out = sub.add_parser("export", help="team cluster -> demo/seed (run on the product laptop)")
    out.add_argument("--workspace-root", required=True, type=Path,
                     help="the .axolotl_workspaces folder that holds the run's files")
    sub.add_parser("load", help="demo/seed -> this laptop's local MongoDB")
    args = parser.parse_args(argv)
    if args.command == "export":
        asyncio.run(export(args.workspace_root, seed_dir()))
    else:
        asyncio.run(load(seed_dir()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
