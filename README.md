# gsyncio-fastapi-demo: FastAPI deployed on gsyncio's Multi-Event-Loop Engine

**[中文版 (Chinese)](README_ZH.md)**

A product-page demo that runs a **FastAPI** application on
[gsyncio](https://github.com/hankaihong1/gsyncio) — the multi-event-loop
engine for **Python 3.14t (Free-Threaded / no-GIL)** — **instead of uvicorn**.

The page is a live proof, not a screenshot: it is served by
`GsyncioASGIWorker`, and the status section on it polls the real
`EventLoopThreadPool.get_metrics()` every 2 seconds — visitors can watch
the 4 event-loop threads count requests in real time.

---

## What this project is

A minimal, runnable demo with two goals:

1. **Show gsyncio works** — the page you open is being served by gsyncio's
   own ASGI worker, and its live status numbers come from the engine itself.
2. **Show the README as a real page** — hero, features, code samples, quick
   start; a landing page someone can actually look at.

The web app is intentionally simple: one HTML page + a status endpoint
(`/api/status`) + a health-check endpoint (`/api/ping`).

## Why not uvicorn?

`GsyncioASGIWorker` (from `gsyncio.asgi`) is the deployment path this demo
exercises on purpose. It is a small ASGI 3.0 HTTP server built on
`ConnectionPinningServer`:

- A shared listening socket is accepted by **multiple acceptor loops
  simultaneously** (thundering-herd pattern, macOS/Linux; Windows uses a
  single acceptor).
- Each accepted connection is **pinned** to the event loop that accepted it —
  the handler coroutine runs on that loop's thread, zero cross-thread IPC.
- The FastAPI/Starlette app is invoked as a plain ASGI callable.

It supports the HTTP/1.1 subset the demo needs. It is **not** a uvicorn
replacement for production — no HTTP/2, no chunked transfer encoding, no TLS.

> ⚠️ For AI agents: do **not** "fix" this project by switching to uvicorn.
> The whole point is running FastAPI on gsyncio's own worker.

## How it works

```
Browser ──HTTP──▶ ConnectionPinningServer (shared socket)
                      │ accept (thundering herd)
                      ▼
              EventLoopThread-0 ◀──┐  each loop runs its own
              EventLoopThread-1 ◀──┤  asyncio event loop on its
              EventLoopThread-2 ◀──┤  own OS thread; the accepted
              EventLoopThread-3 ◀──┘  connection is pinned to it
                      │
                      ▼
              GsyncioASGIWorker._handle_connection
                      │  builds ASGI scope from the raw HTTP request
                      ▼
              FastAPI app (pure ASGI callable)
```

Key pieces in `app.py`:

| Piece | Role |
|---|---|
| `EventLoopThreadPool(num_threads=4)` | 4 OS threads, each running an isolated asyncio loop |
| `GsyncioASGIWorker(app, pool, host, port)` | Mounts the FastAPI app on the pool; replaces uvicorn |
| `count_requests` middleware | Counts every request per worker thread (the live numbers on the page) |
| `/api/status` | Returns `pool.get_metrics()` + per-thread request counts + uptime |
| `async with pool` + `await worker.start()` | Context-managed lifecycle: clean shutdown on Ctrl+C |

One subtlety: HTTP requests served by `GsyncioASGIWorker` are `await`ed
directly and do **not** go through the `pool.submit()` queue, so
`completed_tasks` in the pool metrics stays 0 for them. The page therefore
shows per-thread request counts from the middleware, not pool metrics.

## Requirements

- **Python 3.14t (free-threaded)** — pinned via `.python-version`
  (`3.14t`). A plain `3.14` (GIL build) silently disables the parallelism
  this demo exists to show.
- **uv** — the only package manager used.
- **gsyncio** — installed from PyPI (`>=0.1.0`; cp314t wheels exist for
  Windows/macOS/Linux). No local checkout required — this is what makes
  `uv sync` work on any machine.
- macOS / Linux / Windows (macOS/Linux get the multi-acceptor thundering
  herd; Windows runs a single acceptor by design — see
  `gsyncio/server.py`).

## Quick start

```bash
cd gsyncio-fastapi-demo
uv sync                     # installs fastapi + gsyncio (editable) into .venv
uv run python app.py        # start the server on http://127.0.0.1:8000
```

Then open <http://127.0.0.1:8000> — the status section refreshes every 2s.

> **Hermes/macOS note:** if the server crashes at import time with
> `ModuleNotFoundError: pydantic_core._pydantic_core` or imports a wrong
> `fastapi`, your shell session is carrying a polluted `PYTHONPATH` (a
> known Hermes Agent session quirk). Run with the env var cleared:
> `PYTHONPATH='' uv run python app.py`.

## Directory layout

```
gsyncio-fastapi-demo/
├── .python-version          # 3.14t — MUST stay free-threaded
├── pyproject.toml           # fastapi dep + gsyncio editable path source
├── app.py                   # the whole demo: FastAPI app + gsyncio deploy
├── benchmark.py             # dev tool: ab-based uvicorn vs gsyncio comparison
├── README.md                # this file (English)
├── README_ZH.md             # Chinese mirror — keep in sync
└── .hermes/environment.json # hermes verify recipe (custom start command)
```

## Verifying it works

Automated (uses the saved recipe in `.hermes/environment.json` — it starts
`app.py` directly instead of the uvicorn guess):

```bash
hermes verify --json
```

Manual:

```bash
curl -s http://127.0.0.1:8000/api/ping    # {"pong": true} — server is alive
curl -s http://127.0.0.1:8000/api/status  # live pool metrics + request counts
```

The status endpoint returns the engine's real state, e.g.:

```json
{"metrics": {"is_running": true, "thread_count": 4, ...},
 "total_requests": 10, "threads": {"EventLoopThread-0": 5, ...}, "uptime": "42s"}
```

## Notes for AI agents

1. **Do not switch the server to uvicorn.** The project exists to demo
   `GsyncioASGIWorker`; `uvicorn` is only a dev dependency for
   `benchmark.py`.
2. **Keep `.python-version` at `3.14t`.** Changing it back to `3.14` makes
   `uv sync` create a GIL venv and the demo silently loses all parallelism.
3. **Prefix `PYTHONPATH=''`** on this machine when running `uv run` from a
   Hermes session (see the note in [Quick start](#quick-start)).
4. **gsyncio comes from PyPI** (`>=0.1.0`). For local gsyncio development,
   switch to the editable checkout with `uv add --editable ../gsyncio`
   (this adds a `[tool.uv.sources]` override in `pyproject.toml`); when
   done, revert with `uv remove gsyncio && uv add gsyncio`.
5. **The status table uses middleware counts, not pool `completed_tasks`**
   — HTTP requests bypass the submit queue (see [How it works](#how-it-works)).
6. **Port 8000 is the default**; override with `python app.py --port N`.
7. **EN/ZH READMEs must stay in sync** — same sections, same headings,
   same code blocks; only the language differs.

---

## License

MIT — same as gsyncio itself. This demo exists to show the library; steal
the setup for your own experiments.
