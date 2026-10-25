# The demo build

This branch, `demo/argon-replay`, is **main plus a replay mode**. Every screen and feature is the same as the product. The one difference: Argon's answers are **replayed from a recorded live run**, so a full chess migration takes about 2 minutes instead of 15–60, and costs nothing.

**What's replayed, and what runs for real:**

| | Replayed (no Gemini call) | Runs for real |
|---|---|---|
| Plan | Argon's recorded plan for chess | the plan is validated against the dependency graph |
| Migration | each unit's recorded Argon turns | every tool call, every patch applied to a fresh workspace, **every verifier gate in the sandbox** |
| Report | Argon's narrative, labelled "replayed from run_c86aff1bea77" | every number, read from this run's own journal |
| Ask | the two recorded questions below | their searches and file reads, so the citations are real |

The status chip, plans, runs and Ask answers all name the model **`gemini-4-argon (replay of run_c86aff1bea77)`**, so nothing passes for a live call.

**Recording:** `demo/replays/run_c86aff1bea77.json`, from a live run on 25 Oct. 14 of 14 units verified on the first attempt, 288 checks passed, 0 failed, 15 minutes. It also holds the two Ask answers.

**Data:** the demo laptop uses its **own local MongoDB**, since it can't reach the team cluster. `demo/seed/` holds a copy of the cluster's chess data: graph, search index with embeddings, behaviour cases, docs purposes, and the recorded run with its files.

## Set up the demo laptop (once)

You need Docker Desktop (**started**), [uv](https://docs.astral.sh/uv/), Node 20+ and git.

1. **Get this branch:**
   ```bash
   git clone https://github.com/Prittstick22/axolotl.git axolotl-demo
   cd axolotl-demo
   git checkout demo/argon-replay
   ```
2. **Start a local MongoDB** (Atlas Local, which supports the search indexes):
   ```bash
   docker run -d --name axolotl-atlas-local -p 27017:27017 mongodb/mongodb-atlas-local
   ```
3. **Build the sandbox images.** These are the same five as the README, so the verifier can run:
   ```bash
   docker build -t axolotl-runner:latest runner/
   docker build -t axolotl-runner:py2.7  --build-arg PYTHON_VERSION=2.7  --build-arg PYTEST_VERSION=4.6.11 runner/
   docker build -t axolotl-runner:py3.14 --build-arg PYTHON_VERSION=3.14 --build-arg PYTEST_VERSION=8.4.2  runner/
   docker build -f runner/Dockerfile.behaviour --build-arg PYTHON_IMAGE=python:2.7.18-slim -t axolotl-chess-cases:py27  runner/
   docker build -f runner/Dockerfile.behaviour --build-arg PYTHON_IMAGE=python:3.14-slim  -t axolotl-chess-cases:py314 runner/
   ```
4. **Create `.env` in the repository root:** copy `.env.example`, then set these lines.
   ```bash
   MONGODB_URI=mongodb://localhost:27017/?directConnection=true
   MONGODB_DATABASE=axolotl
   ARGON_REPLAY_FILE=../demo/replays/run_c86aff1bea77.json
   ARGON_REPLAY_DELAY_SECONDS=0.5
   INDEX_ON_IMPORT=false
   GEMINI_DESCRIPTION_MODEL=gemini-3.8-flash
   GEMINI_API_KEY=
   ```
   - `ARGON_REPLAY_DELAY_SECONDS` sets the pace. 0.5 gives about a 1.5–2 minute migration; use 1–2 for a slower video.
   - **`GEMINI_API_KEY` is optional.**
     - Empty, the demo makes **no Gemini calls at all**, and searches use keyword matching, labelled as such.
     - With a key, searches use hybrid matching, at one small embedding call per search.
5. **Load the team's chess data:**
   ```bash
   cd backend
   uv sync
   uv run python -m app.demo_seed load
   ```
   It prints a count per collection (122 `code_chunks`, 14 `module_docs`, 392 `run_events`, and so on) and the 255 run files. It refuses to run against anything but a local MongoDB.

## Run it

```bash
cd backend  && uv run uvicorn app.main:app --port 8000      # terminal 1
cd frontend && npm install && npm run dev                    # terminal 2
```

Open **http://localhost:5173**. All four status chips should be green, and Gemini should say *replay of run_c86aff1bea77*.

## The demo path

1. **New migration → chess** is preselected. **Import** opens the existing chess entry at once.
2. **Overview, then Graph:** the dependency graph. Click a module to open its inspector and docs.
3. **Plan:** keep **Python 2 to Python 3** (preselected), then **Create plan** (instant) and **Approve**.
4. **Start migration.** The graph lights up unit by unit, and the terminal shows each recorded Argon turn and every real gate result. **It finishes 14/14 in about 1.5–2 minutes.**
5. **Click a unit** to open its Verification page and diff, then **Changes** for the whole project's git-style diff.
6. **Report:** the verdict, the summary per unit (with Argon's summary labelled model-written), security, and **Download migrated codebase (.zip)**.
7. **Docs:** legacy and migrated pages for each module. The purposes are already there. **Don't click Generate:** it needs a key, and nothing is missing.
8. **Search "checkmate", then Ask.** Paste one of these exactly (case and the `?` don't matter):
   - `Where is checkmate detected?`
   - `How is a move like e2e4 parsed?`

   Any other question gets a clear "this demo build answers only the questions recorded for it" message, and is never sent to Gemini.

**To show the real live run the recording came from,** bookmark these. They work because the seed brings the run and its files:
- http://localhost:5173/repos/repo_3852f5968630/run?plan=plan_fcff6aced2f5&run=run_c86aff1bea77
- http://localhost:5173/repos/repo_3852f5968630/report?plan=plan_fcff6aced2f5&run=run_c86aff1bea77
- http://localhost:5173/repos/repo_3852f5968630/changes?plan=plan_fcff6aced2f5&run=run_c86aff1bea77

## Before the demo
- [ ] Docker Desktop is running, and `docker ps` shows `axolotl-atlas-local`.
- [ ] All four chips are green, and Gemini says *replay of run_c86aff1bea77*.
- [ ] One full rehearsal: plan, approve, start, 14/14, then Report and Ask.
- [ ] The bookmarks open.

## If something's wrong

| You see | Fix |
|---|---|
| Every screen errors with 503 | Docker or the MongoDB container isn't running: `docker start axolotl-atlas-local` |
| The runner chip is red | Build the five images in step 3 |
| Gemini says `gemini-4-argon` without "replay of…" | `ARGON_REPLAY_FILE` is missing or wrong. It's relative to `backend/`, then restart the backend |
| A unit blocks with "no turn N for unit:…" | The plan's units don't match the recording. Use chess with **Python 2 to Python 3** |
| Ask says it answers only the recorded questions | Paste one of the two questions above |
| `demo_seed load` says "refusing to load" | `MONGODB_URI` isn't the local one from step 4 |

## Re-recording (on a laptop with a key and the team cluster)

```bash
cd backend
uv run python -m app.agents.replay record <run_id>                    # a finished live run -> demo/replays/<run_id>.json
uv run python -m app.agents.replay record-ask repo_3852f5968630 "<question>" demo/replays/<run_id>.json
uv run python -m app.demo_seed export --workspace-root <the product's backend/.axolotl_workspaces>
```

`record` reads the run's journal and fetches each Argon turn by id: a read, so nothing is generated. `record-ask` asks the question once, live. `demo_seed`'s `RUN_ID` and `PLAN_ID` name the run the seed carries.
