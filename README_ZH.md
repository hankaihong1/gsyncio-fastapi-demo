# gsyncio-fastapi-demo：用 gsyncio 多事件循环引擎部署 FastAPI

**[English (英文版)](README.md)**

一个产品展示页演示：把 **FastAPI** 应用跑在
[gsyncio](https://github.com/hankaihong1/gsyncio)（面向 **Python 3.14t
自由线程 / 无 GIL** 的多事件循环引擎）上，**而不是 uvicorn**。

这个页面本身就是"活证据"：它由 `GsyncioASGIWorker` 提供 HTTP 服务，
页面上的状态区每 2 秒从 `EventLoopThreadPool.get_metrics()` 拉取真实
数据——访问者可以实时看到 4 个事件循环线程在计数请求。

---

## 这个项目是什么

一个最小可运行的演示，两个目的：

1. **证明 gsyncio 能跑** —— 你打开的页面就是 gsyncio 自己的 ASGI worker
   在服务，实时状态数字来自引擎本身。
2. **把 README 变成真实页面** —— Hero、特性、代码示例、快速开始；
   一个真能给人看的落地页。

网站本身刻意简单：一个 HTML 页面 + 状态接口（`/api/status`）+ 健康检查
接口（`/api/ping`）。

## 为什么不用 uvicorn？

本演示刻意走 `gsyncio.asgi.GsyncioASGIWorker` 这条部署路径。它是
`gsyncio` 自带的一个小型 ASGI 3.0 HTTP 服务器，构建在
`ConnectionPinningServer` 之上：

- 一个共享监听 socket 由**多个 acceptor 循环同时 accept**
  （惊群模式，macOS/Linux；Windows 用单 acceptor）。
- 每个被接受的连接**固定（pin）到 accept 它的那个事件循环**——处理
  协程就跑在该循环所在的线程上，零跨线程 IPC。
- FastAPI/Starlette 应用作为普通 ASGI callable 被调用。

它支持演示所需的 HTTP/1.1 子集。它**不是** uvicorn 的生产替代品——
没有 HTTP/2、没有 chunked 传输编码、没有 TLS。

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
| `count_requests` middleware | 按 worker 线程计数每个请求（页面上的实时数字） |
| `/api/status` | 返回 `pool.get_metrics()` + 每线程请求计数 + 运行时长 |
| `async with pool` + `await worker.start()` | 上下文管理生命周期：Ctrl+C 时干净关闭 |

一个细节：`GsyncioASGIWorker` 服务的 HTTP 请求是直接 `await` 的，
**不经过** `pool.submit()` 队列，所以 pool metrics 里的
`completed_tasks` 对它们恒为 0。页面因此展示 middleware 的每线程请求
计数，而不是 pool metrics。

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

然后打开 <http://127.0.0.1:8000>——状态区每 2 秒自动刷新。

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
├── benchmark.py             # 开发工具：ab 压测 uvicorn vs gsyncio 对比
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
curl -s http://127.0.0.1:8000/api/ping    # {"pong": true} — 服务器活着
curl -s http://127.0.0.1:8000/api/status  # 实时 pool metrics + 请求计数
```

状态接口返回引擎的真实状态，例如：

```json
{"metrics": {"is_running": true, "thread_count": 4, ...},
 "total_requests": 10, "threads": {"EventLoopThread-0": 5, ...}, "uptime": "42s"}
```

## 给 AI 代理的注意事项

1. **不要把服务器换成 uvicorn。** 这个项目存在的意义就是演示
   `GsyncioASGIWorker`；uvicorn 只是 `benchmark.py` 的 dev 依赖。
2. **保持 `.python-version` 为 `3.14t`。** 改回 `3.14` 会让 `uv sync`
   创建 GIL venv，演示的并行能力会被静默丢掉。
3. **在本机从 Hermes 会话跑 `uv run` 时加 `PYTHONPATH=''` 前缀**
   （见[快速开始](#快速开始)的说明）。
4. **gsyncio 是 editable 路径依赖。** 修改 `../gsyncio` 立即生效，
   无需重新 sync。
5. **状态表用 middleware 计数，不是 pool 的 `completed_tasks`**——
   HTTP 请求不经过 submit 队列（见[工作原理](#工作原理)）。
6. **默认端口 8000**；用 `python app.py --port N` 覆盖。
7. **中英文 README 必须保持同步**——同样的章节、同样的标题、同样的
   代码块；只有语言不同。

---

## License

MIT——与 gsyncio 本身一致。这个演示是为了展示库的能力；部署方式可以
随意借鉴到你自己的实验里。
