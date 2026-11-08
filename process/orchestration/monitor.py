"""Emits one line per meaningful swarm change (for the director's Monitor). Polls every 45 s."""
import json, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
seen = {}


def launcher_alive():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'launch.py run' } | Measure-Object | Select-Object -ExpandProperty Count"],
                         capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


def snapshot():
    snap = {}
    for f in (ROOT / "orchestration" / "state").glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        wid = s["id"]
        snap[(wid, "state")] = s["state"]
        snap[(wid, "rounds")] = len(s["rounds"])
        snap[(wid, "denied")] = len(s["denied_actions"])
        if s["rounds"]:
            r = s["rounds"][-1]
            snap[(wid, "lastround")] = f"{r.get('status')} steps={r.get('steps')} err={str(r.get('error') or '')[:120]}"
    for f in (ROOT / "agents" / "status").glob("*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            snap[(f.stem, "worker")] = f"{j.get('status')} / {str(j.get('milestone'))[:60]}"
        except Exception:
            pass
    return snap


alive_prev = True
while True:
    cur = snapshot()
    for k, v in cur.items():
        if seen.get(k) != v:
            wid, field = k
            if field == "denied" and v:
                d = json.loads((ROOT / "orchestration" / "state" / f"{wid}.json").read_text(encoding="utf-8"))["denied_actions"][-1]
                print(f"{wid} DENIED {d.get('tool')} {json.dumps(d.get('params'))[:160]}", flush=True)
            elif field != "denied":
                print(f"{wid} {field}: {v}", flush=True)
    seen.update(cur)
    alive = launcher_alive()
    if alive != alive_prev:
        print(f"LAUNCHER {'ALIVE' if alive else 'DEAD'}", flush=True)
        alive_prev = alive
    time.sleep(45)
