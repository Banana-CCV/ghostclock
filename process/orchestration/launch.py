"""GhostClock swarm launcher (exploratory pre-test tooling).

Runs Gemini 4 Argon workers through the Antigravity CLI (`agy`) in headless mode.

* Prompt is passed on stdin (avoids Windows command-line limits / quoting).
* Each worker: cwd = work/<id>/, --add-dir = repo root, stream-json -> agents/logs/<id>.rNN.ndjson
* Status JSON per worker in orchestration/state/<id>.json (launcher-owned) - workers write their
  own agents/status/<id>.json separately.
* Continuation rounds: when a run ends and the worker has not written a DONE/BLOCKED status,
  the launcher resumes the same conversation (--conversation) with a "continue" nudge.
* Transport errors (ERROR status with ~no steps) are retried with bounded backoff.

Usage:
  python orchestration/launch.py run  --spec orchestration/wave1.json [--concurrency 16] [--only W05,W06]
  python orchestration/launch.py status
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGY = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
LOGS = ROOT / "agents" / "logs"
STATE = ROOT / "orchestration" / "state"
WORKER_STATUS = ROOT / "agents" / "status"
PROMPTS = ROOT / "agents" / "prompts"

CONTINUE_NUDGE = (
    "Continue your assigned GhostClock task from where you stopped. First re-read your own "
    "progress.md and agents/status/{id}.json, then carry on with the next unfinished step of the "
    "A-H sequence (orientation, research, plan, implement, execute, critique, iterate, deliver). "
    "Do not redo finished work. If every deliverable in your contract truly exists on disk with real "
    "contents, set status to DONE in agents/status/{id}.json and finish. If you are blocked, set "
    "BLOCKED with a precise reason and complete any other sub-work first. Remember: only use the "
    "allowed commands (python, ffmpeg, ffprobe, git without push, cd, ls/dir, Get-ChildItem, "
    "Get-Content, mkdir); do anything else (downloads, file ops, hashing) from Python scripts."
)


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def build_env() -> dict:
    env = dict(os.environ)
    venv_scripts = ROOT / ".venv" / "Scripts"
    user_path = os.environ.get("PATH", "")
    extra = [str(venv_scripts)]
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in winget.glob("Gyan.FFmpeg*/*/bin"):
        extra.append(str(p))
    env["PATH"] = os.pathsep.join(extra + [user_path])
    env["PYTHONUTF8"] = "1"
    env["MPLBACKEND"] = "Agg"
    if not env.get("GEMINI_API_KEY"):
        # Key is stored as a Windows *user* env var by set_gemini_key.ps1; this process may predate it.
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                env["GEMINI_API_KEY"] = winreg.QueryValueEx(k, "GEMINI_API_KEY")[0]
        except OSError:
            pass
    # agy itself authenticates via the hackathon org account (gcp / uclagentverse26lon-5508) in the
    # OS keyring; GEMINI_API_KEY is only passed through for workers' direct SDK experiments.
    return env


def worker_declared_final(wid: str) -> str | None:
    f = WORKER_STATUS / f"{wid}.json"
    if not f.exists():
        return None
    try:
        st = json.loads(f.read_text(encoding="utf-8", errors="replace")).get("status", "")
    except Exception:
        return None
    st = str(st).upper()
    return st if st in {"DONE", "BLOCKED", "FAILED"} else None


class Worker:
    def __init__(self, spec: dict, defaults: dict):
        self.id = spec["id"]
        self.title = spec.get("title", self.id)
        self.model = spec.get("model", defaults.get("model", "gemini-4-argon-high"))
        self.max_rounds = int(spec.get("max_rounds", defaults.get("max_rounds", 6)))
        self.timeout = spec.get("print_timeout", defaults.get("print_timeout", "90m"))
        self.prompt_file = PROMPTS / spec.get("prompt", f"{self.id}.md")
        self.workdir = ROOT / "work" / self.id
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.state_file = STATE / f"{self.id}.json"
        self.state = {
            "id": self.id, "title": self.title, "model": self.model, "state": "queued",
            "rounds": [], "conversation_id": None, "denied_actions": [], "last_event": None,
            "events": 0, "tokens": 0, "started": None, "ended": None,
        }
        if self.state_file.exists():  # resume support
            try:
                old = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.state.update({k: old[k] for k in ("rounds", "conversation_id", "denied_actions", "tokens") if k in old})
            except Exception:
                pass
        self.save()

    def save(self):
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    async def run_once(self, prompt: str, round_no: int, resume: str | None) -> dict:
        args = [str(AGY), "--model", self.model, "--mode", "accept-edits",
                "--add-dir", str(ROOT), "--output-format", "stream-json",
                "--print-timeout", self.timeout]
        if resume:
            args += ["--conversation", resume]
        log = LOGS / f"{self.id}.r{round_no:02d}.ndjson"
        err = LOGS / f"{self.id}.r{round_no:02d}.stderr.log"
        result: dict = {}
        steps = 0
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(self.workdir), env=build_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(err, "wb"), limit=1 << 24)
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        stall_s = float(os.environ.get("GC_STALL_SECONDS", "900"))

        async def lines():
            while True:
                try:
                    ln = await asyncio.wait_for(proc.stdout.readline(), timeout=stall_s)
                except asyncio.TimeoutError:
                    proc.kill()  # silent too long: kill, the round is resumed via --conversation
                    result["status"] = "STALLED"
                    result["error"] = f"no stream events for {stall_s:.0f}s; killed by watchdog"
                    return
                if not ln:
                    return
                yield ln

        with open(log, "ab") as fh:
            async for line in lines():
                fh.write(line)
                fh.flush()
                self.state["events"] += 1
                self.state["last_event"] = now()
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "init":
                    self.state["conversation_id"] = ev.get("conversation_id") or self.state["conversation_id"]
                elif ev.get("event") == "step_update":
                    su = ev.get("step_update", {})
                    steps += 1
                    self.state["conversation_id"] = su.get("conversation_id") or self.state["conversation_id"]
                    if su.get("state") == "ERROR" and "permission" in json.dumps(su.get("tool_info", {})):
                        ti = su.get("tool_info", {})
                        self.state["denied_actions"].append({"t": now(), "tool": su.get("tool_name"),
                                                             "params": ti.get("parameters")})
                elif ev.get("event") == "result":
                    result.update(ev.get("result", {}))
                if self.state["events"] % 20 == 0:
                    self.save()
        rc = await proc.wait()
        result["_rc"] = rc
        result["_steps"] = steps
        return result

    async def run(self):
        base_prompt = self.prompt_file.read_text(encoding="utf-8")
        self.state["state"] = "running"
        self.state["started"] = self.state["started"] or now()
        self.save()
        start_round = len(self.state["rounds"])
        transport_retries = 0
        r = start_round
        while r < self.max_rounds:
            final = worker_declared_final(self.id)
            if final:
                break
            resume = self.state["conversation_id"]
            nudge_file = ROOT / "orchestration" / "nudge.md"
            nudge = nudge_file.read_text(encoding="utf-8") if nudge_file.exists() else CONTINUE_NUDGE
            extra = ROOT / "orchestration" / "nudges" / f"{self.id}.md"  # per-worker director notes
            if extra.exists():
                nudge += "\n\nDIRECTOR NOTE FOR YOU:\n" + extra.read_text(encoding="utf-8")
            prompt = base_prompt if resume is None else nudge.replace("{id}", self.id)
            t0 = now()
            try:
                res = await self.run_once(prompt, r, resume)
            except Exception as e:  # launcher-level failure
                res = {"status": "LAUNCH_ERROR", "error": repr(e), "_rc": -1, "_steps": 0}
            usage = res.get("usage") or {}
            self.state["tokens"] += int(usage.get("total_tokens") or 0)
            self.state["rounds"].append({
                "round": r, "start": t0, "end": now(), "status": res.get("status"), "rc": res.get("_rc"),
                "steps": res.get("_steps"), "duration_s": res.get("duration_seconds"),
                "tokens": usage.get("total_tokens"), "denied": res.get("denied_actions"),
                "error": (res.get("error") or "")[:500] if isinstance(res.get("error"), str) else res.get("error"),
                "response_head": (res.get("response") or "")[:600],
            })
            self.save()
            transport = res.get("status") in {"ERROR", "LAUNCH_ERROR", "STALLED", None} and (res.get("_steps") or 0) < 3
            if transport:
                transport_retries += 1
                if transport_retries > 3:
                    self.state["state"] = "failed_transport"
                    break
                await asyncio.sleep(min(30 * 2 ** transport_retries, 300))
                if res.get("_steps", 0) == 0 and r == 0:
                    self.state["conversation_id"] = None  # nothing to resume
                    self.state["rounds"].pop()
                    self.save()
                    continue
            r += 1
        final = worker_declared_final(self.id)
        if self.state["state"] == "running":
            self.state["state"] = f"finished:{final}" if final else "finished:rounds_exhausted"
        self.state["ended"] = now()
        self.save()


async def run_all(spec_path: Path, concurrency: int, only: set[str] | None):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    defaults = spec.get("defaults", {})
    workers = [Worker(w, defaults) for w in spec["workers"] if not only or w["id"] in only]
    sem = asyncio.Semaphore(concurrency)
    stagger = float(defaults.get("stagger_seconds", 8))

    async def guarded(i: int, w: Worker):
        await asyncio.sleep(i * stagger)
        async with sem:
            await w.run()

    LOGS.mkdir(parents=True, exist_ok=True)
    print(f"[{now()}] launching {len(workers)} workers, concurrency={concurrency}", flush=True)
    await asyncio.gather(*(guarded(i, w) for i, w in enumerate(workers)))
    print(f"[{now()}] all workers finished", flush=True)


def status():
    rows = []
    for f in sorted(STATE.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        ws = WORKER_STATUS / f"{s['id']}.json"
        wstat = ""
        if ws.exists():
            try:
                j = json.loads(ws.read_text(encoding="utf-8", errors="replace"))
                wstat = f"{j.get('status','?')} | {str(j.get('milestone') or j.get('current_step') or '')[:40]}"
            except Exception:
                wstat = "unparseable"
        files = sum(1 for _ in (ROOT / "work" / s["id"]).rglob("*") if _.is_file()) if (ROOT / "work" / s["id"]).exists() else 0
        rows.append(f"{s['id']:<5} {s['state']:<26} rounds={len(s['rounds']):<2} ev={s['events']:<5} "
                    f"tok={s['tokens']:<9} denied={len(s['denied_actions']):<2} files={files:<4} last={s['last_event']} | {wstat}")
    print("\n".join(rows) if rows else "no state yet")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--spec", required=True)
    r.add_argument("--concurrency", type=int, default=16)
    r.add_argument("--only", default="")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "run":
        only = {x.strip() for x in a.only.split(",") if x.strip()} or None
        asyncio.run(run_all(Path(a.spec), a.concurrency, only))
    else:
        status()
