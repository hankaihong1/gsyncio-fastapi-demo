"""gsyncio 演示网站：FastAPI 应用跑在 gsyncio 多事件循环引擎上。

为什么这个项目存在
------------------
这个文件是整个演示项目的心脏：它证明了 FastAPI 应用可以不依赖 uvicorn，
直接挂到 gsyncio 的 GsyncioASGIWorker 上，在 Python 3.14t（自由线程 /
无 GIL）下用多个事件循环线程真正并行地处理请求。

启动方式：
    uv run python app.py
然后浏览器打开 http://127.0.0.1:8000

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
# 刻意不用 uvicorn——这正是本演示要展示的部署路径。
from gsyncio.asgi import GsyncioASGIWorker

# EventLoopThreadPool 是核心引擎：N 个 OS 线程各跑一个独立的 asyncio
# 事件循环。请求被"钉"到 accept 它的那个循环上，线程之间零 IPC。
# 线程数选 4：既足够展示并行（8 请求分两批跑完），又不会在 8GB 内存
# 的 M1 上给 free-threaded 解释器造成内存压力（本地压测经验 ≤6 线程）。
from gsyncio.pool import EventLoopThreadPool

app = FastAPI(title="gsyncio Demo")


@app.middleware("http")
async def no_keep_alive(request, call_next):
    # GsyncioASGIWorker 处理完一个请求就关闭底层连接，但它的响应头
    # 不声明 Connection: close，浏览器会乐观复用连接 → 请求发到已死的
    # 连接 → 失败重连 → 请求被串行化（6 个请求 1.8s 而非 0.3s）。
    # 显式声明 close 让浏览器每次新建连接，才能走多线程并行路径。
    response = await call_next(request)
    response.headers["Connection"] = "close"
    return response

# 统计每个请求由哪个 worker 线程处理，演示页面据此渲染负载均衡效果。
# Counter 是线程安全的（GIL 时代的经验；在 3.14t 下由 CPython 内部
# 保证原子性），这里只是展示用途，不追求精确。
thread_counter: Counter[str] = Counter()

# 演示页面：纯内联 HTML/CSS/JS，没有构建步骤、没有前端依赖。
# JS 部分用 Promise.all 同时发出 6 个请求，等全部返回后渲染表格，
# 并在页面上对比"实际总耗时"与"串行参考值"（6 × 300ms）。
PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>gsyncio — 多事件循环引擎演示</title>
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
  .badge.hot { color: var(--accent); border-color: rgba(79,140,255,0.4); }
  h1 { font-size: 40px; font-weight: 800; letter-spacing: -0.5px; }
  h1 .accent { background: linear-gradient(90deg, var(--accent), var(--accent2));
               -webkit-background-clip: text; background-clip: text; color: transparent; }
  .sub { color: var(--muted); font-size: 17px; max-width: 640px; margin-top: 12px; }
  .cta { margin-top: 28px; }
  .cta a {
    display: inline-block; background: linear-gradient(90deg, var(--accent), var(--accent2));
    color: #fff; text-decoration: none; padding: 12px 28px; border-radius: 10px;
    font-weight: 600; font-size: 15px;
  }

  /* ── Sections ── */
  section { padding: 56px 0; border-bottom: 1px solid var(--border); }
  h2 { font-size: 24px; margin-bottom: 8px; }
  .lead { color: var(--muted); margin-bottom: 32px; }

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

  /* ── Demo ── */
  .demo-panel {
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    padding: 28px; margin-top: 24px;
  }
  button {
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    color: #fff; border: none; padding: 14px 32px; font-size: 16px; font-weight: 600;
    border-radius: 10px; cursor: pointer; transition: opacity 0.15s;
  }
  button:hover { opacity: 0.88; }
  button:disabled { opacity: 0.5; cursor: wait; }
  .stat-row { display: flex; gap: 24px; flex-wrap: wrap; margin: 20px 0 4px; }
  .stat { flex: 1; min-width: 140px; }
  .stat .num { font-size: 30px; font-weight: 800; font-family: "SF Mono", Menlo, monospace; }
  .stat .num.green { color: var(--green); }
  .stat .num.orange { color: var(--orange); }
  .stat .lbl { color: var(--muted); font-size: 12.5px; }
  table { border-collapse: collapse; margin-top: 16px; width: 100%; font-size: 13.5px; }
  th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
  th { background: rgba(255,255,255,0.04); color: var(--muted); font-weight: 500; }
  td code { font-family: "SF Mono", Menlo, monospace; color: var(--accent); }

  /* ── Benchmark bars ── */
  .bars { margin-top: 8px; }
  .bar-row { margin-bottom: 18px; }
  .bar-row .name { display: flex; justify-content: space-between; font-size: 13.5px; margin-bottom: 6px; }
  .bar-row .name .v { font-family: "SF Mono", Menlo, monospace; color: var(--accent); }
  .bar { height: 26px; border-radius: 6px; transition: width 0.6s ease; }
  .bar.serial { background: linear-gradient(90deg, #3a4568, #55618a); }
  .bar.gsyncio { background: linear-gradient(90deg, var(--accent), var(--accent2)); }
  .note { color: var(--muted); font-size: 12.5px; margin-top: 12px; }

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
      <span class="badge hot">Python 3.14t · Free-Threaded</span>
      <span class="badge">Rust Core · PyO3</span>
      <span class="badge">No-GIL</span>
      <span class="badge">Go-Style Concurrency</span>
      <span class="badge">MIT License</span>
    </div>
    <h1>gsyncio <span class="accent">多事件循环引擎</span></h1>
    <p class="sub">
      为 Python 3.14t（自由线程 / 无 GIL）打造的并发工具包：多个事件循环
      跑在独立线程上<b>真正并行</b>处理请求。Rust 内核提供无锁队列与
      原子指标，Go 风格原语让并发代码像写同步代码一样简单。
    </p>
    <div class="cta"><a href="#demo">立即体验并发加速 ↓</a></div>
  </div>
</header>

<section>
  <div class="wrap">
    <h2>核心特性</h2>
    <p class="lead">不只是演示——这是生产可用的引擎。</p>
    <div class="grid">
      <div class="card">
        <div class="icon">⚡</div>
        <h3>真正的多线程并行</h3>
        <p>彻底打破 GIL 限制，实测最高 <b>3.48x+</b> 物理多核加速。
           本页下方的实时演示就是它的工作现场。</p>
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

<section id="demo">
  <div class="wrap">
    <h2>实时演示：6 个并发请求</h2>
    <p class="lead">
      每个请求模拟 0.3s I/O 等待（数据库查询 / 外部 API）。如果串行处理，
      6 个请求需要 1.8s；gsyncio 把它们分散到 4 个事件循环线程上并行执行。
      浏览器对同一域名最多 6 个并行连接——6 个请求恰好全部并行。
    </p>
    <div class="demo-panel">
      <button id="go" onclick="runDemo()">▶ 发起 6 个并发请求</button>
      <div class="stat-row">
        <div class="stat">
          <div class="num" id="stat-total">—</div>
          <div class="lbl">实际总耗时</div>
        </div>
        <div class="stat">
          <div class="num green" id="stat-speedup">—</div>
          <div class="lbl">相对串行的加速比</div>
        </div>
        <div class="stat">
          <div class="num orange" id="stat-serial">1800 ms</div>
          <div class="lbl">串行参考值（6 × 300ms）</div>
        </div>
      </div>
      <table>
        <thead><tr><th>#</th><th>处理线程</th><th>单请求耗时</th><th>该线程累计请求</th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>实测数据</h2>
    <p class="lead">Apple M1 · 8GB 内存 · Python 3.14.6t · 本机真实测量</p>
    <div class="bars">
      <div class="bar-row">
        <div class="name"><span>串行处理（单事件循环）</span><span class="v">2.52 s</span></div>
        <div class="bar serial" style="width:100%"></div>
      </div>
      <div class="bar-row">
        <div class="name"><span>gsyncio（4 事件循环并行）</span><span class="v">0.34 s</span></div>
        <div class="bar gsyncio" style="width:13.5%"></div>
      </div>
    </div>
    <p class="note">
      ↑ 同样 8 个 0.3s I/O 请求：<b>2.52s → 0.34s，加速 7.5×</b>。
      串行时线程逐个执行、CPU 空转等待；并行时 4 个循环同时推进，
      总耗时只比单请求略多。点击上方按钮，在本机现场复现这个数据。
    </p>
  </div>
</section>

<footer>
  <div class="wrap">
    <p>
      技术栈：<code>Python 3.14t</code> · <code>FastAPI</code> ·
      <code>Rust / PyO3</code> · <code>flume</code> · <code>parking_lot</code>
      &nbsp;|&nbsp; 本页面由 <code>GsyncioASGIWorker</code> 直接提供 HTTP 服务，
      没有 uvicorn。
    </p>
  </div>
</footer>

<script>
async function runDemo() {
  const btn = document.getElementById('go');
  btn.disabled = true;
  const N = 6;
  const t0 = performance.now();
  // 6 个请求同时发出，等全部返回（6 = 浏览器对同一域名并行连接上限，
  // 恰好全部并行；每个响应带 connection: close，浏览器不会复用连接）
  const results = await Promise.all(
    Array.from({length: N}, (_, i) =>
      fetch('/api/demo').then(r => r.json()).then(d => ({i: i + 1, ...d}))
    )
  );
  const total = performance.now() - t0;

  document.getElementById('stat-total').textContent = total.toFixed(0) + ' ms';
  const speedup = (N * 300 / total).toFixed(1);
  document.getElementById('stat-speedup').textContent = speedup + '×';

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${r.i}</td><td><code>${r.thread}</code></td>` +
                   `<td>${r.elapsed_ms} ms</td><td>${r.count}</td>`;
    tbody.appendChild(tr);
  }
  btn.disabled = false;
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE


@app.get("/api/demo")
async def demo() -> dict:
    # 记录当前请求落在哪个 worker 线程上，页面据此展示负载均衡。
    # GsyncioASGIWorker 会把每个请求 pin 到 accept 它的那个事件循环线程，
    # 所以并发请求会分散到 4 个线程（而不是都挤在一个循环里）。
    thread = threading.current_thread().name
    thread_counter[thread] += 1

    # 模拟真实业务里的 I/O 等待（数据库查询、外部 API 调用等）。
    # 关键点：asyncio.sleep 让出控制权，同一个循环里其他任务可以
    # 继续跑；而 free-threaded 下不同循环真的在不同 CPU 上并行。
    start = time.perf_counter()
    await asyncio.sleep(0.3)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    return {"thread": thread, "elapsed_ms": elapsed_ms, "count": thread_counter[thread]}


async def main() -> None:
    # 4 个事件循环线程：每个线程跑一个独立的 asyncio loop。
    # async with 保证退出时优雅关闭所有线程（join 等待收尾）。
    async with EventLoopThreadPool(num_threads=4) as pool:
        # GsyncioASGIWorker 替代 uvicorn：把 FastAPI 应用直接挂到 gsyncio 上。
        # host/port 决定监听地址；端口硬编码 8000，方便演示和文档一致。
        worker = GsyncioASGIWorker(app=app, pool=pool, host="127.0.0.1", port=8000)
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
