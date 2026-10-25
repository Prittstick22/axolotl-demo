# Axolotl demo build: instructions for agents

This repository is the **demo build** of Axolotl, not the product. It's [Prittstick22/axolotl](https://github.com/Prittstick22/axolotl) plus a replay mode: Argon's answers come from a recorded live run (`demo/replays/run_c86aff1bea77.json`), so the chess migration demo makes **no Gemini calls**. Every screen is the product's.

## "Spin it up", "run the demo" or "start it"

Run the one-command start script from the repository root. It is safe to run again, and it skips whatever is already done.

- **Windows:** `powershell -ExecutionPolicy Bypass -File demo\start.ps1`
- **macOS/Linux:** `bash demo/start.sh`

**What it does:**
- checks Docker, uv and npm, and starts the local MongoDB container (`axolotl-atlas-local`);
- builds any missing sandbox images;
- creates `.env` from `demo/demo.env.example` if there isn't one;
- installs dependencies, and loads the team's chess data (`app.demo_seed load --if-missing`);
- starts the backend (port 8000) and the frontend (port 5173) in the background, logging to `demo/.logs/`;
- checks the status chips, and opens http://localhost:5173/repos/repo_3852f5968630.

**The demo is up when** all four status chips are green and the Gemini chip reads **`gemini-4-argon (replay of run_c86aff1bea77)`**.

- **Other ports** (for example beside a running product): `-BackendPort 8001 -FrontendPort 5174` on Windows, or `BACKEND_PORT=8001 FRONTEND_PORT=5174` on macOS/Linux.
- **Stop:** `powershell -ExecutionPolicy Bypass -File demo\stop.ps1`, or `bash demo/stop.sh`.

**Do not follow the README's "Quick start" here.** That's the product's setup: the team's Atlas cluster and live Gemini calls. Here, the setup is `demo/DEMO_BUILD.md`, which the scripts implement.

## Rules
- **This laptop's MongoDB only.** Never put a `mongodb+srv://` (team cluster) URI in this repository's `.env`; the start script refuses one.
- **No live Gemini calls.**
  - Keep `ARGON_REPLAY_FILE` set.
  - Don't start live migrations.
  - Don't trigger re-indexing (`POST /repositories/{id}/index`) or docs generation (`POST /repositories/{id}/docs`): both spend a key, and the data they'd produce is already loaded.
- **Never push to, or open pull requests into, `Prittstick22/axolotl`, and never merge this repository into the product.** Product changes flow one way only: fetch the product's `main` and merge it here.
- Never print or commit `.env` values.

## Where things are
- **`demo/DEMO_BUILD.md`:** what's replayed and what's live, manual setup, the demo path, the two recorded Ask questions, a checklist, troubleshooting and re-recording.
- **`demo/replays/`:** recorded runs. **`demo/seed/`:** the team cluster's chess data and the recorded run's files (`backend/app/demo_seed.py`).
- **`backend/app/agents/replay.py`:** the replay mode and the recorders.
