"""
load_test.py — a lunch-rush rehearsal against a throwaway database.

    python scripts/load_test.py                       # 400 students, 40 at a time
    python scripts/load_test.py --students 1000 --concurrency 100

Starts scripts/e2e_server.py (one uvicorn worker, test sign-in, a fresh
traytrack_e2e_load database) and, at the same time:
  * every student signs in, accepts the privacy notice and files a complaint;
  * public dashboard readers poll /dashboard-status and /alerts;
  * an admin keeps refreshing the complaints and alerts lists.
Prints p50/p95/p99 latency and the error rate per kind of request, and exits
non-zero if errors exceed 1% or the complaint p95 exceeds --p95-budget.
Needs MySQL/MariaDB running as for the tests; drops traytrack_e2e_load.
"""

import argparse
import asyncio
import os
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
CSRF = {"X-TrayTrack": "1"}
timings = defaultdict(list)
errors = defaultdict(int)
first_error = {}


async def timed(kind, call):
    started = time.perf_counter()
    try:
        r = await call
        ok = r.status_code < 400
    except httpx.HTTPError:
        r, ok = None, False
    timings[kind].append(time.perf_counter() - started)
    if not ok:
        errors[kind] += 1
        first_error.setdefault(kind, f"{r.status_code} {r.text[:200]}" if r is not None else "connection error")
    return r


async def student(api, i, mess_ids, categories, version, gate):
    async with gate, httpx.AsyncClient(base_url=api, headers=CSRF, timeout=30) as c:
        await timed("sign in", c.post("/auth/test-login", json={"email": f"load{i}@sample-college.edu", "name": f"Load {i}"}))
        await timed("consent", c.post("/me/consent", json={"version": version}))
        await timed("complaint", c.post("/complaints", data={
            "mess_id": random.choice(mess_ids), "category": random.choice(categories),
            "description": "Load test: rice undercooked", "meal": "lunch"}))


async def reader(api, college_id, stop):
    async with httpx.AsyncClient(base_url=api, timeout=30) as c:
        while not stop.is_set():
            await timed("dashboard", c.get("/dashboard-status", params={"college_id": college_id}))
            await timed("public alerts", c.get("/alerts", params={"college_id": college_id}))
            await asyncio.sleep(0.5)


async def admin(api, stop):
    async with httpx.AsyncClient(base_url=api, headers=CSRF, timeout=30) as c:
        await c.post("/staff/login", json={"email": "admin@e2e.test", "password": "e2e-admin-pass"})
        while not stop.is_set():
            await timed("staff complaints", c.get("/staff/complaints"))
            await timed("staff alerts", c.get("/staff/alerts"))
            await asyncio.sleep(1)


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


async def run(api, students, concurrency, readers):
    async with httpx.AsyncClient(base_url=api, timeout=30) as c:
        college_id = (await c.get("/colleges")).json()[0]["id"]
        mess_ids = [m["id"] for m in (await c.get("/mess-halls", params={"college_id": college_id})).json()]
        categories = [cat["name"] for cat in (await c.get("/categories")).json()]
        version = (await c.get("/privacy")).json()["version"]
    stop = asyncio.Event()
    background = [asyncio.create_task(reader(api, college_id, stop)) for _ in range(readers)]
    background.append(asyncio.create_task(admin(api, stop)))
    gate = asyncio.Semaphore(concurrency)
    started = time.perf_counter()
    await asyncio.gather(*(student(api, i, mess_ids, categories, version, gate) for i in range(students)))
    elapsed = time.perf_counter() - started
    stop.set()
    await asyncio.gather(*background)
    return elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=40, help="students acting at the same moment")
    parser.add_argument("--readers", type=int, default=20, help="people watching the public dashboard")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--p95-budget", type=float, default=1.0, help="seconds")
    args = parser.parse_args()

    api = f"http://127.0.0.1:{args.port}"
    env = {**os.environ, "E2E_DB_NAME": "traytrack_e2e_load", "RATE_LIMIT_SCALE": "1000"}
    server = subprocess.Popen([sys.executable, str(HERE / "e2e_server.py"), "--port", str(args.port)],
                              cwd=HERE.parent, env=env)
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{api}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            sys.exit("Server didn't start")
        elapsed = asyncio.run(run(api, args.students, args.concurrency, args.readers))
    finally:
        server.terminate()
        server.wait()

    print(f"\n{args.students} students ({args.concurrency} at once) + {args.readers} dashboard readers + 1 admin, "
          f"one API worker, {elapsed:.1f}s\n")
    print(f"{'request':<18}{'count':>7}{'errors':>8}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}")
    total = failed = 0
    for kind, values in timings.items():
        total += len(values)
        failed += errors[kind]
        print(f"{kind:<18}{len(values):>7}{errors[kind]:>8}{statistics.median(values) * 1000:>9.0f}"
              f"{pct(values, 0.95) * 1000:>9.0f}{pct(values, 0.99) * 1000:>9.0f}")
    for kind, detail in first_error.items():
        print(f"first {kind} error: {detail}")
    rate = failed / max(total, 1)
    complaint_p95 = pct(timings["complaint"], 0.95)
    print(f"\nerror rate {rate:.2%}; complaints/s {args.students / elapsed:.1f}")
    if rate > 0.01 or complaint_p95 > args.p95_budget:
        sys.exit(f"FAIL: error rate {rate:.2%} or complaint p95 {complaint_p95:.2f}s over budget {args.p95_budget}s")
    print("PASS")


if __name__ == "__main__":
    main()
