"""同场压测对比：uvicorn vs gsyncio（同一个 FastAPI 应用）。

为什么有这个脚本
----------------
浏览器的"点击演示"不可控（keep-alive、连接上限、重试时序都取决于
浏览器实现），不能作为性能证据。性能对比必须用标准压测工具（ab），
在完全相同的负载下对比不同的服务器实现。

对比对象：
  1. uvicorn 单 worker   —— 1 进程 1 事件循环（基线）
  2. uvicorn 4 workers   —— 4 进程（多进程方案）
  3. gsyncio 4 线程      —— 1 进程 4 事件循环线程（本项目的方案）

压测负载：/api/ping（零延迟 JSON 端点，纯 HTTP 吞吐）。
注意：不测 CPU 密集端点——同步 CPU 代码在任何 asyncio 服务器里都会
阻塞事件循环（这是 asyncio 的固有限制，正确做法是 run_in_executor），
它测的是"谁把 CPU 代码放对地方"而非服务器本身。

用法：
  PYTHONPATH='' uv run python benchmark.py

注意：本机是 Apple M1 8GB。4 个 uvicorn 进程 + gsyncio + ab 同时跑
内存压力较大；如遇 OOM 把 uvicorn 4 workers 的对比去掉即可。
"""

import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass

# 三个服务器各占一个端口，避免与默认演示端口 8000 冲突
UVICORN1_PORT = 8101
UVICORN4_PORT = 8103
GSYNCIO_PORT = 8102

# 每台服务器压测轮数；取中位数，避免单轮抖动影响结论
ROUNDS = 3

# Hermes 会话会注入被污染的 PYTHONPATH（指向 hermes-agent 的 3.11
# site-packages），会让 uv run 的进程 import 到错误版本的包。
# 所有子进程统一清空，保证用的是项目 .venv 里的 3.14t 环境。
CLEAN_ENV = {**os.environ, "PYTHONPATH": ""}


@dataclass
class BenchResult:
    server: str
    qps: float
    mean_ms: float
    p95_ms: float
    failed: int


def start_uvicorn(port: int, workers: int) -> subprocess.Popen:
    """启动 uvicorn 子进程（同一 FastAPI 应用 app:app）。"""
    cmd = [
        sys.executable, "-m", "uvicorn", "app:app",
        "--host", "127.0.0.1", "--port", str(port),
        "--workers", str(workers), "--log-level", "warning",
    ]
    return subprocess.Popen(cmd, env=CLEAN_ENV, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def start_gsyncio(port: int) -> subprocess.Popen:
    """启动 gsyncio 子进程（app.py --port，4 事件循环线程）。"""
    cmd = [sys.executable, "app.py", "--port", str(port)]
    return subprocess.Popen(cmd, env=CLEAN_ENV, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def wait_ready(port: int, timeout: float = 30.0) -> bool:
    """轮询等待服务器就绪（TCP 握手成功即视为就绪）。"""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_ab(port: int, n: int = 500, c: int = 50) -> BenchResult:
    """用 ApacheBench 压测 /api/ping，解析 QPS / 延迟 / 失败数。

    ab 参数与 gsyncio 仓库 benchmark 保持一致（-n 500 -c 50），
    保证数字可以跨项目对比。
    """
    url = f"http://127.0.0.1:{port}/api/ping"

    # 预热：让 JIT/连接池/调度器进入稳态，避免首轮冷启动拖低成绩
    subprocess.run(["ab", "-n", "50", "-c", "10", url],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)

    result = subprocess.run(["ab", "-n", str(n), "-c", str(c), url],
                            capture_output=True, text=True, check=False)
    out = result.stdout

    def grab(pattern: str, default: float = 0.0) -> float:
        m = re.search(pattern, out)
        return float(m.group(1)) if m else default

    return BenchResult(
        server="",
        qps=grab(r"Requests per second:\s+([\d.]+)"),
        mean_ms=grab(r"Time per request:\s+([\d.]+)\s+\[ms\] \(mean\)"),
        p95_ms=grab(r"95%\s+(\d+)"),
        failed=int(grab(r"Failed requests:\s+(\d+)")),
    )


def bench_server(port: int, n: int = 500, c: int = 50) -> BenchResult:
    """压测同一台服务器 ROUNDS 轮，返回中位数结果（抗抖动）。"""
    rounds = [run_ab(port, n, c) for _ in range(ROUNDS)]
    return BenchResult(
        server="",
        qps=statistics.median(r.qps for r in rounds),
        mean_ms=statistics.median(r.mean_ms for r in rounds),
        p95_ms=statistics.median(r.p95_ms for r in rounds),
        failed=sum(r.failed for r in rounds),
    )


def main() -> None:
    servers: list[tuple[str, subprocess.Popen]] = []
    try:
        # 启动三台服务器（gsyncio 只有 4 线程一种配置）
        print("启动服务器...")
        uv1 = start_uvicorn(UVICORN1_PORT, workers=1)
        servers.append(("uvicorn (1 worker)", uv1))
        uv4 = start_uvicorn(UVICORN4_PORT, workers=4)
        servers.append(("uvicorn (4 workers)", uv4))
        gs = start_gsyncio(GSYNCIO_PORT)
        servers.append(("gsyncio (4 threads)", gs))

        ports = {"uvicorn (1 worker)": UVICORN1_PORT,
                 "uvicorn (4 workers)": UVICORN4_PORT,
                 "gsyncio (4 threads)": GSYNCIO_PORT}

        for name, proc in servers:
            if not wait_ready(ports[name]):
                print(f"  ✗ {name} 启动失败")
                sys.exit(1)
            print(f"  ✓ {name} 就绪 (port {ports[name]})")

        print("\n压测中（-n 500 -c 50，先预热 50 请求）...\n")
        results: list[BenchResult] = []
        for path in ("/api/ping", "/api/work"):
            for name, proc in servers:
                r = run_ab(ports[name], path)
                r.server = name
                results.append(r)

        # 输出对比表
        print("=" * 78)
        print(f"{'服务器':<22}{'端点':<12}{'QPS':>10}{'均值(ms)':>10}{'P95(ms)':>10}{'失败':>6}")
        print("-" * 78)
        for r in results:
            print(f"{r.server:<22}{r.path:<12}{r.qps:>10.1f}{r.mean_ms:>10.1f}"
                  f"{r.p95_ms:>10.0f}{r.failed:>6}")
        print("=" * 78)

        # 关键对比：CPU 密集负载下 gsyncio 相对 uvicorn 单 worker 的加速
        ping_uv1 = next(r for r in results if r.server == "uvicorn (1 worker)"
                        and r.path == "/api/ping")
        work_uv1 = next(r for r in results if r.server == "uvicorn (1 worker)"
                        and r.path == "/api/work")
        work_gs = next(r for r in results if r.server == "gsyncio (4 threads)"
                       and r.path == "/api/work")
        work_uv4 = next(r for r in results if r.server == "uvicorn (4 workers)"
                        and r.path == "/api/work")
        print(f"\nCPU 密集负载 (/api/work) 加速对比：")
        print(f"  gsyncio 4线程 / uvicorn 1worker : {work_gs.qps / work_uv1.qps:.2f}x")
        print(f"  gsyncio 4线程 / uvicorn 4workers: {work_gs.qps / work_uv4.qps:.2f}x")

    finally:
        print("\n清理服务器进程...")
        for name, proc in servers:
            proc.terminate()
        for name, proc in servers:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
