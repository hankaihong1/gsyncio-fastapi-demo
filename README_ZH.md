# gsyncio-fastapi-demo：用 gsyncio 多事件循环引擎部署 FastAPI

**[English (英文版)](README.md)**

一个最小可运行的演示项目：把 **FastAPI** 应用跑在
[gsyncio](https://github.com/hankaihong1/gsyncio)（面向 **Python 3.14t
自由线程 / 无 GIL** 的多事件循环引擎）上，**而不是 uvicorn**。

浏览器打开演示页面，点一个按钮，就能看到 8 个并发请求被分散到 4 个
worker 事件循环线程上并行处理，总耗时约 0.34s——而串行服务器需要约
2.4s。

---

## 目录

- [这个项目是什么](#这个项目是什么)
- [为什么不用 uvicorn？](#为什么不用-uvicorn)
- [工作原理](#工作原理)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [验证它能工作](#验证它能工作)
- [给 AI 代理的注意事项](#给-ai-代理的注意事项)

---

## 这个项目是什么

这是**演示项目**，不是生产模板。它唯一的目的就是展示 gsyncio 的核心
价值：在自由线程 Python 3.14t 下，多个运行在独立 OS 线程上的 asyncio
事件循环可以**真正并行**地处理请求，没有 GIL 争抢。

网站本身刻意保持简单：一个带按钮的 HTML 页面 + 一个模拟 0.3s I/O
延迟的 JSON 接口（`asyncio.sleep` 代替真实的数据库查询或外部 API 调用）。

## 为什么不用 uvicorn？

本演示刻意走 `gsyncio.asgi.GsyncioASGIWorker` 这条部署路径。它是
`gsyncio` 自带的一个小型 ASGI 3.0 HTTP 服务器，构建在
`ConnectionPinningServer` 之上：

- 一个共享监听 socket 由**多个 acceptor 循环同时 accept**
  （惊群模式，macOS/Linux；Windows 用单 acceptor）。
- 每个被接受的连接**固定（pin）到 accept 它的那个事件循环**——处理
  协程就跑在该循环所在的线程上，零跨线程 IPC。
- FastAPI/Starlette 应用作为普通 ASGI callable 被调用。

它支持演示所需的 HTTP/1.1 子集（GET/POST、Content-Length 请求体、
简单响应）。它**不是** uvicorn 的生产替代品——没有 HTTP/2、没有
chunked 传输编码、没有 TLS。

> ⚠️ 给 AI 代理：**不要**把这个项目"修复"成用 uvicorn。这个项目存在
> 的意义就是让 FastAPI 跑在 gsyncio 自己的 worker 上。

## 工作原理

```
浏览器 ──HTTP──▶ ConnectionPinningServer（共享 socket）
                      │ accept（惊群）
                      ▼
              EventLoopThread-0 ◀──┐  每个 loop 在自己的 OS 线程上
              EventLoopThread-1 ◀──┤  跑独立的 asyncio 事件循环；
              EventLoopThread-2 ◀──┤  被 accept 的连接固定到该 loop
              EventLoopThread-3 ◀──┘
                      │
                      ▼
              GsyncioASGIWorker._handle_connection
                      │  从原始 HTTP 请求构建 ASGI scope
                      ▼
              FastAPI 应用（纯 ASGI callable）
```

`app.py` 里的关键部件：

| 部件 | 作用 |
|---|---|
| `EventLoopThreadPool(num_threads=4)` | 4 个 OS 线程，各跑一个隔离的 asyncio 循环 |
| `GsyncioASGIWorker(app, pool, host, port)` | 把 FastAPI 应用挂到线程池上；替代 uvicorn |
| `async with pool` + `await worker.start()` | 上下文管理生命周期：Ctrl+C 时干净关闭 |
| `await asyncio.Event().wait()` | 挂起主协程，让服务器持续运行 |

`app.py` 里的 `thread_counter` 记录每个请求由哪个 worker 线程处理——
演示页面会渲染这个数据，让你**亲眼看到**负载均衡。

## 环境要求

- **Python 3.14t（自由线程）**——由 `.python-version`（`3.14t`）固定。
  如果改成 `3.14`（GIL 版），本演示要展示的并行能力会被静默禁用。
- **uv**——唯一使用的包管理器。
- **gsyncio**——声明为指向 `../gsyncio` 的 editable 路径依赖，本地改
  gsyncio 源码无需重新 `uv sync` 即可生效。
- macOS / Linux / Windows（macOS/Linux 用多 acceptor 惊群；Windows
  按设计只用单 acceptor——见 `gsyncio/server.py`）。

## 快速开始

```bash
cd gsyncio-fastapi-demo
uv sync                     # 安装 fastapi + gsyncio (editable) 到 .venv
uv run python app.py        # 启动服务器，监听 http://127.0.0.1:8000
```

然后打开 <http://127.0.0.1:8000>，点击 **发起 8 个并发请求**。

> **Hermes/macOS 提示：** 如果服务器启动时 import 报错
> `ModuleNotFoundError: pydantic_core._pydantic_core` 或导入了错误的
> `fastapi`，说明你的 shell 会话带着被污染的 `PYTHONPATH`（Hermes
> Agent 会话的已知怪癖）。清空环境变量再跑：
> `PYTHONPATH='' uv run python app.py`。

## 目录结构

```
gsyncio-fastapi-demo/
├── .python-version          # 3.14t — 必须保持自由线程版
├── pyproject.toml           # fastapi 依赖 + gsyncio editable 路径源
├── app.py                   # 整个演示：FastAPI 应用 + gsyncio 部署
├── README.md                # 英文版
├── README_ZH.md             # 中文镜像 — 内容必须同步
└── .hermes/environment.json # hermes verify 配方（自定义启动命令）
```

## 验证它能工作

自动化（使用 `.hermes/environment.json` 里保存的配方——直接启动
`app.py`，而不是自动检测猜的 uvicorn）：

```bash
hermes verify --json
```

手动：

```bash
# 8 个请求逐个发——预期总耗时约 2.4s
for i in $(seq 1 8); do curl -s http://127.0.0.1:8000/api/demo; echo; done

# 8 个请求同时发——预期总耗时约 0.3–0.6s，且分散在 4 个线程上
for i in $(seq 1 8); do curl -s http://127.0.0.1:8000/api/demo & done; wait
```

API 会返回每个请求的处理线程，例如：

```json
{"thread": "EventLoopThread-2", "elapsed_ms": 301.1, "count": 6}
```

实测数据（Apple M1 8GB，Python 3.14.6t）：

| 场景 | 总耗时 | 加速比 |
|---|---|---|
| 串行（8 × 0.3s） | 2.52 s | 1.0× |
| gsyncio 4 循环并发 | 0.34 s | **7.5×** |

## 给 AI 代理的注意事项

1. **不要把服务器换成 uvicorn。** 这个项目存在的意义就是演示
   `GsyncioASGIWorker`；项目里甚至没有 uvicorn 依赖。
2. **保持 `.python-version` 为 `3.14t`。** 改回 `3.14` 会让 `uv sync`
   创建 GIL venv，演示的并行能力会被静默丢掉。
3. **在本机从 Hermes 会话跑 `uv run` 时加 `PYTHONPATH=''` 前缀**
   （见[快速开始](#快速开始)的说明）。
4. **gsyncio 是 editable 路径依赖。** 修改 `../gsyncio` 立即生效，
   无需重新 sync。
5. **端口 8000 硬编码在 `app.py` 里**；被占用就在那里改。
6. **中英文 README 必须保持同步**——同样的章节、同样的标题、同样的
   代码块；只有语言不同。

---

## License

MIT——与 gsyncio 本身一致。这个演示是为了展示库的能力；部署方式可以
随意借鉴到你自己的实验里。
