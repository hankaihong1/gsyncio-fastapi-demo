"""gsyncio 产品官网演示：README 网站化 + 实时引擎状态。

这个页面本身就是一个"活证据"：它由 gsyncio 的 GsyncioASGIWorker
提供 HTTP 服务（不是 uvicorn），页面上的实时状态区每秒从
EventLoopThreadPool 拉取真实 metrics——用户打开页面就能看到
4 个事件循环线程在工作。

启动方式：
    uv run python app.py            # 默认端口 8000
    uv run python app.py --port 9000

注意：如果 import 报 ModuleNotFoundError: pydantic_core._pydantic_core，
说明 shell 里 PYTHONPATH 被污染（Hermes 会话已知怪癖），请用：
    PYTHONPATH='' uv run python app.py
"""

import asyncio
import threading
import time
from collections import Counter

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# GsyncioASGIWorker 是 gsyncio 自带的 ASGI 3.0 HTTP 服务器：它读原始
# HTTP 请求、构建 ASGI scope、把 FastAPI 应用当作普通 ASGI callable 调用。
# 刻意不用 uvicorn——本页面就是这条部署路径的活演示。
from gsyncio.asgi import GsyncioASGIWorker

# EventLoopThreadPool 是核心引擎：N 个 OS 线程各跑一个独立的 asyncio
# 事件循环。请求被"钉"到 accept 它的那个循环上，线程之间零 IPC。
# 线程数选 4：在 8GB M1 上既展示并行又不给 free-threaded 解释器
# 造成内存压力（本地压测经验 ≤6 线程）。
from gsyncio.pool import EventLoopThreadPool

app = FastAPI(title="gsyncio — Multi-Event-Loop Engine")

# 服务器启动时间（uptime 计算用）——挂在 app.state 上，/api/status 读取。
app.state.started_at = time.monotonic()

# 每个请求由哪个 worker 线程处理——状态区展示负载均衡的直观证据。
# Counter 在 3.14t 下由 CPython 内部保证原子性，展示用途足够。
thread_counter: Counter[str] = Counter()


@app.middleware("http")
async def count_requests(request, call_next):
    # 所有请求计数（/api/status 除外——页面每 2 秒轮询它，若计数会
    # 造成虚假增长）。thread_counter 记录线程分布，状态区据此展示
    # 4 个事件循环线程的负载均衡。
    thread = threading.current_thread().name
    if request.url.path != "/api/status":
        thread_counter[thread] += 1
    return await call_next(request)

# 页面：README 网站化（产品官网风格）。静态 HTML 内联，无前端构建。
# 实时数据区通过 fetch('/api/status') 每 2 秒刷新，数据全部来自
# pool.get_metrics() 与 thread_counter——不是写死的数字。
PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>gsyncio — 多事件循环引擎</title>
<style>
  :root {
    --bg: #0b1020;
    --card: #141a2e;
    --border: #232c48;
    --text: #e8ecf8;
    --muted: #8a94b0;
    --accent: #4f8cff;
    --accent2: #7c5cff;
    --green: #34d399;
    --orange: #fbbf24;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, "PingFang SC", "Segoe UI", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
  }
  .wrap { max-width: 960px; margin: 0 auto; padding: 0 24px; }

  /* ── Hero ── */
  header {
    padding: 72px 0 56px;
    background: radial-gradient(1200px 500px at 20% -10%, #1a2448 0%, var(--bg) 60%);
    border-bottom: 1px solid var(--border);
  }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
  .badge {
    font-size: 12px; padding: 4px 12px; border-radius: 20px;
    border: 1px solid var(--border); color: var(--muted); background: rgba(255,255,255,0.03);
  }
  .badge.hot { color: var(--green); border-color: rgba(52,211,153,0.4); }
  .badge.accent { color: var(--accent); border-color: rgba(79,140,255,0.4); }
  .live-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--green); margin-right: 6px; animation: pulse 1.5s infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  h1 { font-size: 40px; font-weight: 800; letter-spacing: -0.5px; }
  h1 .accent { background: linear-gradient(90deg, var(--accent), var(--accent2));
               -webkit-background-clip: text; background-clip: text; color: transparent; }
  .sub { color: var(--muted); font-size: 17px; max-width: 660px; margin-top: 12px; }
  .cta { margin-top: 28px; display: flex; gap: 12px; flex-wrap: wrap; }
  .cta a, .cta code {
    display: inline-block; padding: 10px 20px; border-radius: 10px;
    font-size: 14px; text-decoration: none;
  }
  .cta a.primary { background: linear-gradient(90deg, var(--accent), var(--accent2)); color: #fff; font-weight: 600; }
  .cta code {
    background: var(--card); border: 1px solid var(--border); color: var(--muted);
    font-family: "SF Mono", Menlo, monospace;
  }

  /* ── Sections ── */
  section { padding: 56px 0; border-bottom: 1px solid var(--border); }
  h2 { font-size: 24px; margin-bottom: 8px; }
  .lead { color: var(--muted); margin-bottom: 32px; }

  /* ── Status grid ── */
  .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
  .status-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    padding: 20px;
  }
  .status-card .num { font-size: 26px; font-weight: 800; font-family: "SF Mono", Menlo, monospace; }
  .status-card .num.green { color: var(--green); }
  .status-card .lbl { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
  table { border-collapse: collapse; margin-top: 16px; width: 100%; font-size: 13.5px; }
  th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
  th { background: rgba(255,255,255,0.04); color: var(--muted); font-weight: 500; }
  td code { font-family: "SF Mono", Menlo, monospace; color: var(--accent); }

  /* ── Feature grid ── */
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    padding: 22px; transition: border-color 0.2s;
  }
  .card:hover { border-color: rgba(79,140,255,0.5); }
  .card .icon { font-size: 22px; }
  .card h3 { font-size: 16px; margin: 10px 0 6px; }
  .card p { color: var(--muted); font-size: 13.5px; }
  .card code {
    background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px;
    font-family: "SF Mono", Menlo, monospace; font-size: 12px; color: var(--accent);
  }

  /* ── Code blocks ── */
  pre {
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    padding: 20px; overflow-x: auto; font-size: 13px; line-height: 1.55;
  }
  pre code { font-family: "SF Mono", Menlo, monospace; color: #c9d4f5; }
  .kw { color: #7c9cff; } .fn { color: #34d399; } .st { color: #fbbf24; }
  .cm { color: #5a6482; }

  /* ── Footer ── */
  footer { padding: 40px 0 64px; color: var(--muted); font-size: 13px; }
  footer code {
    background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px;
    font-family: "SF Mono", Menlo, monospace; font-size: 12px;
  }
</style>
</head>
<body>

<header>
  <div class="wrap">
    <div class="badges">
      <span class="badge hot"><span class="live-dot"></span>本页面由 gsyncio 提供 HTTP 服务</span>
      <span class="badge accent">Python 3.14t · Free-Threaded</span>
      <span class="badge">Rust Core · PyO3</span>
      <span class="badge">Go-Style Concurrency</span>
    </div>
    <h1>gsyncio <span class="accent">多事件循环引擎</span></h1>
    <p class="sub">
      为 Python 3.14t（自由线程 / 无 GIL）打造的并发工具包：多个事件循环跑在
      独立线程上真正并行处理请求。Rust 内核提供无锁队列与原子指标，
      Go 风格原语让并发代码像写同步代码一样简单。你正在看的这个页面，
      就运行在 gsyncio 自己的 ASGI 服务器上。
    </p>
    <div class="cta">
      <a class="primary" href="#status">查看实时运行状态 ↓</a>
      <code>uv sync &amp;&amp; uv run python app.py</code>
    </div>
  </div>
</header>

<section id="status">
  <div class="wrap">
    <h2>实时运行状态</h2>
    <p class="lead">
      数据每 2 秒从 <code>EventLoopThreadPool.get_metrics()</code> 拉取——
      不是写死的数字，是引擎此刻的真实状态。
    </p>
    <div class="status-grid">
      <div class="status-card">
        <div class="num" id="st-threads">—</div>
        <div class="lbl">事件循环线程</div>
      </div>
      <div class="status-card">
        <div class="num green" id="st-requests">—</div>
        <div class="lbl">已处理请求</div>
      </div>
      <div class="status-card">
        <div class="num" id="st-uptime">—</div>
        <div class="lbl">服务器运行时长</div>
      </div>
      <div class="status-card">
        <div class="num" id="st-active">—</div>
        <div class="lbl">当前活跃请求</div>
      </div>
    </div>
    <table>
      <thead><tr><th>线程</th><th>已处理请求</th></tr></thead>
      <tbody id="thread-tbody"></tbody>
    </table>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>核心特性</h2>
    <p class="lead">来自 README 的承诺——状态区上方就是兑现的证据。</p>
    <div class="grid">
      <div class="card">
        <div class="icon">⚡</div>
        <h3>真正的多线程并行</h3>
        <p>彻底打破 GIL 限制，在 Python 3.14t 下实现多核物理并行。
           多个事件循环同时推进，互不阻塞。</p>
      </div>
      <div class="card">
        <div class="icon">🦀</div>
        <h3>Rust 无锁内核</h3>
        <p>队列与指标计数器用 <code>PyO3</code> + <code>flume</code> +
           <code>parking_lot</code> 实现，零忙等（空闲 0% CPU），
           通道吞吐接近硬件极限。</p>
      </div>
      <div class="card">
        <div class="icon">🦫</div>
        <h3>Go 风格并发原语</h3>
        <p><code>FastChannel</code>、<code>select_channel</code>、
           <code>AsyncWaitGroup</code>、<code>AsyncOnce</code>、
           <code>AsyncRWMutex</code>……把 Go 的并发哲学带进 asyncio。</p>
      </div>
      <div class="card">
        <div class="icon">🎯</div>
        <h3>轮询调度 + 工作窃取</h3>
        <p>任务进入共享无锁队列，空闲 worker 按轮询唤醒、按需窃取，
           连接固定（pinning）到专属事件循环，零跨线程 IPC。</p>
      </div>
      <div class="card">
        <div class="icon">🚀</div>
        <h3>FastAPI 原生挂载</h3>
        <p><code>GsyncioASGIWorker</code> 直接替代 uvicorn 部署
           FastAPI / Starlette 应用——本页就运行在它上面。</p>
      </div>
      <div class="card">
        <div class="icon">📊</div>
        <h3>健康指标可观测</h3>
        <p><code>pool.get_metrics()</code> 返回原子计数指标：
           事件循环延迟、任务吞吐、队列水位，随时可查。</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>代码示例</h2>
    <p class="lead">三行挂载，Go 风格原语开箱即用。</p>
<pre><code><span class="cm"># 1. 把 FastAPI 应用挂到 gsyncio 上（替代 uvicorn）</span>
<span class="kw">from</span> gsyncio.asgi <span class="kw">import</span> <span class="fn">GsyncioASGIWorker</span>
<span class="kw">from</span> gsyncio.pool <span class="kw">import</span> <span class="fn">EventLoopThreadPool</span>

<span class="kw">async with</span> <span class="fn">EventLoopThreadPool</span>(num_threads=<span class="st">4</span>) <span class="kw">as</span> pool:
    worker = <span class="fn">GsyncioASGIWorker</span>(app=app, pool=pool, port=<span class="st">8000</span>)
    <span class="kw">await</span> worker.<span class="fn">start</span>()</code></pre>
<pre><code><span class="cm"># 2. Go 风格通道：生产者 / 消费者零锁通信</span>
ch = <span class="fn">gsyncio.FastChannel</span>(capacity=<span class="st">16</span>)

<span class="kw">async def</span> <span class="fn">producer</span>():
    <span class="kw">for</span> i <span class="kw">in range</span>(<span class="st">10</span>):
        <span class="kw">await</span> ch.<span class="fn">send</span>(i)

<span class="kw">async def</span> <span class="fn">consumer</span>():
    <span class="kw">async for</span> item <span class="kw">in</span> ch:
        <span class="fn">print</span>(item)</code></pre>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>快速开始</h2>
    <p class="lead">三行命令，从零到跑起来。</p>
<pre><code>uv sync                     <span class="cm"># 安装依赖（gsyncio 为 editable 路径依赖）</span>
uv run python app.py        <span class="cm"># 启动本页面（GsyncioASGIWorker）</span>
<span class="cm"># 打开 http://127.0.0.1:8000 —— 你正在看的就是它</span></code></pre>
  </div>
</section>

<footer>
  <div class="wrap">
    <p>
      技术栈：<code>Python 3.14t</code> · <code>FastAPI</code> ·
      <code>Rust / PyO3</code> · <code>flume</code> · <code>parking_lot</code>
      &nbsp;|&nbsp; 本页面由 <code>GsyncioASGIWorker</code> 直接提供 HTTP 服务。
      &nbsp;|&nbsp; 源码：<code>github.com/hankaihong1/gsyncio</code>
    </p>
  </div>
</footer>

<script>
// 每 2 秒拉一次 /api/status，刷新实时状态区。
// 数据来自服务器端的 pool.get_metrics()——引擎真实状态，不是页面伪造。
async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    document.getElementById('st-threads').textContent = s.metrics.thread_count;
    document.getElementById('st-requests').textContent = s.total_requests;
    document.getElementById('st-uptime').textContent = s.uptime;
    document.getElementById('st-active').textContent =
      s.metrics.active_tasks.reduce((a, b) => a + b, 0);

    const tbody = document.getElementById('thread-tbody');
    tbody.innerHTML = '';
    // 注意：用 middleware 的请求计数（s.threads），不是 pool 的
    // completed_tasks——GsyncioASGIWorker 直接 await app()，HTTP 请求
    // 不经过 pool.submit() 队列，后者统计的是 submit 的任务。
    for (let i = 0; i < s.metrics.thread_count; i++) {
      const name = `EventLoopThread-${i}`;
      const done = s.threads[name] || 0;
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><code>${name}</code></td><td>${done}</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) { /* 服务器还在启动中，下轮再试 */ }
}
refreshStatus();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE


@app.get("/api/status")
async def status() -> dict:
    """实时状态：pool metrics + 请求计数 + 运行时长。

    页面状态区的数据源——每次请求都从 EventLoopThreadPool 拉取
    真实快照，所以能看到引擎此刻的工作状态。
    """
    pool: EventLoopThreadPool = app.state.pool
    return {
        "metrics": pool.get_metrics(),
        "total_requests": sum(thread_counter.values()),
        "threads": dict(thread_counter),
        "uptime": f"{int(time.monotonic() - app.state.started_at)}s",
    }


@app.get("/api/ping")
async def ping() -> dict:
    # 零延迟健康检查端点：curl http://127.0.0.1:8000/api/ping
    # 返回 {"pong": true} 即服务器活着。
    return {"pong": True}


async def main() -> None:
    # 4 个事件循环线程：每个线程跑一个独立的 asyncio loop。
    # async with 保证退出时优雅关闭所有线程（join 等待收尾）。
    # --port 参数支持多实例并行（benchmark 脚本会用到）。
    import argparse

    parser = argparse.ArgumentParser(description="gsyncio FastAPI demo server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    async with EventLoopThreadPool(num_threads=4) as pool:
        # pool 挂到 app.state，/api/status 需要它拉取 metrics
        app.state.pool = pool

        # GsyncioASGIWorker 替代 uvicorn：把 FastAPI 应用直接挂到 gsyncio 上。
        worker = GsyncioASGIWorker(app=app, pool=pool, host="127.0.0.1", port=args.port)
        await worker.start()
        print(f"gsyncio demo running at http://127.0.0.1:{worker.port}")
        try:
            # 挂起主协程，让服务器持续运行直到 Ctrl+C。
            # Event().wait() 比 while True + sleep 更干净：无忙等、可取消。
            await asyncio.Event().wait()
        finally:
            await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
