# gsyncio-fastapi-demo: FastAPI deployed on gsyncio's Multi-Event-Loop Engine

**[中文版 (Chinese)](README_ZH.md)**

A minimal, runnable demonstration of running a **FastAPI** application on
[gsyncio](https://github.com/hankaihong1/gsyncio) — the multi-event-loop
engine for **Python 3.14t (Free-Threaded / no-GIL)** — **instead of uvicorn**.

Open the demo page in a browser, click one button, and watch 6 concurrent
requests get spread across 4 worker event-loop threads and finish in ~0.31s
instead of the ~1.8s a serial server would take.

---

## Table of Contents

- [What this project is](#what-this-project-is)
- [Why not uvicorn?](#why-not-uvicorn)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Directory layout](#directory-layout)
- [Verifying it works](#verifying-it-works)
- [Notes for AI agents](#notes-for-ai-agents)

---

## What this project is

This is a **demo**, not a production template. Its single purpose is to show
gsyncio's core value proposition: in free-threaded Python 3.14t, multiple
independent asyncio event loops running on separate OS threads can serve
requests **in true parallel**, with no GIL contention.

The web app itself is intentionally trivial: one HTML page with a button,
and one JSON endpoint that simulates 0.3s of I/O latency per request
(`asyncio.sleep`, standing in for a database query or external API call).

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

It supports the HTTP/1.1 subset the demo needs (GET/POST, Content-Length
bodies, simple responses). It is **not** a uvicorn replacement for
production — no HTTP/2, no chunked transfer encoding, no TLS.

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
| `async with pool` + `await worker.start()` | Context-managed lifecycle: clean shutdown on Ctrl+C |
| `await asyncio.Event().wait()` | Holds the main coroutine so the server runs forever |

The `thread_counter` in `app.py` records which worker thread handled each
request — the demo page renders this so you can *see* the load balancing.

## Requirements

- **Python 3.14t (free-threaded)** — pinned via `.python-version`
  (`3.14t`). A plain `3.14` (GIL build) silently disables the parallelism
  this demo exists to show.
- **uv** — the only package manager used.
- **gsyncio** — declared as an editable path dependency pointing at
  `../gsyncio`, so local gsyncio edits take effect without re-`sync`ing.
- macOS / Linux / Windows (macOS/Linux get the multi-acceptor thundering
  herd; Windows runs a single acceptor by design — see
  `gsyncio/server.py`).

## Quick start

```bash
cd gsyncio-fastapi-demo
uv sync                     # installs fastapi + gsyncio (editable) into .venv
uv run python app.py        # start the server on http://127.0.0.1:8000
```

Then open <http://127.0.0.1:8000> and click **发起 6 个并发请求**
("fire 6 concurrent requests").

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
# 8 requests one after another — expect ~2.4s total
for i in $(seq 1 8); do curl -s http://127.0.0.1:8000/api/demo; echo; done

# 8 requests at once — expect ~0.3–0.6s total, spread across 4 threads
for i in $(seq 1 8); do curl -s http://127.0.0.1:8000/api/demo & done; wait
```

The API returns the handling thread per request, e.g.:

```json
{"thread": "EventLoopThread-2", "elapsed_ms": 301.1, "count": 6}
```

Measured on Apple M1 (8 GB), Python 3.14.6t:

| Scenario | Total time | Speedup |
|---|---|---|
| Serial (8 × 0.3s) | 2.52 s | 1.0× |
| gsyncio 4 loops, concurrent | 0.34 s | **7.5×** |

## Notes for AI agents

1. **Do not switch the server to uvicorn.** The project exists to demo
   `GsyncioASGIWorker`; `uvicorn` is not even a dependency.
2. **Keep `.python-version` at `3.14t`.** Changing it back to `3.14` makes
   `uv sync` create a GIL venv and the demo silently loses all parallelism.
3. **Prefix `PYTHONPATH=''`** on this machine when running `uv run` from a
   Hermes session (see the note in [Quick start](#quick-start)).
4. **gsyncio is an editable path dependency.** Edits to `../gsyncio` are
   picked up immediately; no re-sync needed.
5. **Port 8000 is hardcoded** in `app.py`; change it there if occupied.
6. **EN/ZH READMEs must stay in sync** — same sections, same headings,
   same code blocks; only the language differs.

---

## License

MIT — same as gsyncio itself. This demo exists to show the library; steal
the setup for your own experiments.
