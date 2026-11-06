"""Not experiment data. One slot, one member, in order: what does a warm run cost with less in it?"""
import asyncio, contextlib, statistics as st, sys, time
from pathlib import Path
from vora import Vora
from vora_arc.client import PoolMode, batch_request, open_pool
from vora_arc.corpus import load_solutions, warmup_candidates
from vora_arc.profile import load_profile
from vora_arc.tasks import load_task

N = 200

async def once(pool, profile, cmd, args, stdin):
    start = time.perf_counter(); wall = None; code = None
    async with contextlib.aclosing(aiter(pool.stream_run(cmd, args, stdin=stdin, timeout_seconds=profile.batch_timeout_seconds))) as chunks:
        async for c in chunks:
            if c.kind == "exit":
                wall = (time.perf_counter() - start) * 1000; code = c.exit.exit_code
    return wall, code

async def main(path):
    profile = load_profile(Path(path))
    c = warmup_candidates(load_solutions(Path("solutions")), 1)[0]
    task = load_task(next(Path("data").rglob(f"{c.task_id}.json")))
    stdin, _ = batch_request(profile, c.program, task)
    runner, *rargs = profile.runner_command
    cases = [
        ("true", "true", [], None),
        ("python3 -c pass", "python3", ["-c", "pass"], None),
        ("python3 -S -c pass", "python3", ["-S", "-c", "pass"], None),
        ("runner with a hand-written solution", runner, rargs, stdin),
    ]
    async with Vora() as vora:
        async with open_pool(vora, profile, "vora-arc-limiter", PoolMode.WARM, 1, borrow_timeout_ms=60000) as pool:
            for _ in range(600):
                s = await pool.stats()
                if s and s.idle >= 1: break
                await asyncio.sleep(0.1)
            for label, cmd, args, data in cases:
                walls = []; codes = set()
                for _ in range(N):
                    w, code = await once(pool, profile, cmd, args, data)
                    walls.append(w); codes.add(code)
                walls.sort()
                print(f"{profile.name:18} {label:38} n={N} p50={st.median(walls):7.1f} p90={walls[int(N*.9)]:7.1f} exit={sorted(codes)}")

asyncio.run(main(sys.argv[1]))
