"""Stage 2: fix thresholds on DEV only, then report on HOLDOUT.

  python tune_and_report.py tune     -> speed_params.json, splice_params.json, eval/tuning.json
  python tune_and_report.py report   -> RESULTS.json (dev + holdout, Wilson 95% CIs)

All rows come from eval/features.jsonl (run_eval.py). Labels:
  method=orig  : real ENF-WHU clip, unmodified
  method=rate  : SYNTHETIC ffmpeg asetrate/aresample speed change (pitch+tempo)
  method=tempo : SYNTHETIC ffmpeg atempo (tempo only, pitch preserved)
  task=splice  : SYNTHETIC deletion/insertion (kind=delete/insert), kind=none is unmodified
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import speed_check as sc  # noqa: E402

FEAT = os.path.join(HERE, "eval", "features.jsonl")
FAR_TARGET = 0.05
LOC_TOL_S = 1.5


def wilson(k, n, z=1.96):
    if n == 0:
        return dict(k=k, n=n, rate=None, ci95=None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return dict(k=k, n=n, rate=round(p, 4), ci95=[round(max(0, c - h), 4), round(min(1, c + h), 4)])


def load_rows():
    return [json.loads(l) for l in open(FEAT)]


# ---------------------------------------------------------------- speed
def speed_decision(row, p):
    return sc.decide(row["f"][str(p["lam"])], p)


def speed_eval(rows, p, split):
    R = [r for r in rows if r["task"] == "speed" and r["split"] == split]
    dec = {}
    for r in R:
        dec[id(r)] = speed_decision(r, p)
    return R, dec


def tune_speed(rows):
    base = sc.load_params()
    dev = [r for r in rows if r["task"] == "speed" and r["split"] == "dev"]
    h1o = [r for r in dev if r["cls"] == "H1" and r["method"] == "orig"]
    h0 = [r for r in dev if r["cls"] == "H0"]
    alt = [r for r in dev if r["cls"] == "H1" and r["method"] == "rate"]
    grid = dict(lam=[0.5, 1.5, 3.0], s_k1=[6, 8, 10, 12, 15, 20, 25], s_alt=[10, 15, 20, 25, 30, 40, 50, 60, 80],
                margin=[1e9, 40, 25, 15], min_lines_alt=[2, 3])
    best, table = None, []
    for vals in itertools.product(*grid.values()):
        p = dict(base, **dict(zip(grid.keys(), vals)))
        if p["s_alt"] < p["s_k1"]:
            continue
        fa = sum(speed_decision(r, p) == "SPEED_ALTERED_REVIEW" for r in h1o) / len(h1o)
        fa0 = sum(speed_decision(r, p) == "SPEED_ALTERED_REVIEW" for r in h0) / max(1, len(h0))
        tpr = sum(speed_decision(r, p) == "SPEED_ALTERED_REVIEW" for r in alt) / len(alt)
        cons = sum(speed_decision(r, p) == "CONSISTENT_WITH_REALTIME" for r in h1o) / len(h1o)
        table.append(dict(zip(grid.keys(), vals), far_h1=round(fa, 4), far_h0=round(fa0, 4), tpr=round(tpr, 4),
                          consistent_h1=round(cons, 4)))
        if fa <= FAR_TARGET and fa0 <= FAR_TARGET:
            key = (round(tpr, 4), round(cons, 4), -fa)
            if best is None or key > best[0]:
                best = (key, p)
    p = best[1]
    chosen = {k: p[k] for k in grid}
    return chosen, table, dict(n_dev_h1_orig=len(h1o), n_dev_h0=len(h0), n_dev_rate=len(alt))


# ---------------------------------------------------------------- splice
def splice_decision(row, theta, t_line):
    f = row["f"]
    if f["line_snr"] is None or f["line_snr"] < t_line or f["max_J"] is None:
        return "NO_GRID_SIGNAL", False
    flagged = f["max_J"] > theta
    loc = False
    if flagged and row.get("t_splice") is not None:
        targets = [row["t_splice"]] + ([row["t_splice_end"]] if row.get("t_splice_end") is not None else [])
        loc = any(J > theta and min(abs(t - tt) for tt in targets) <= LOC_TOL_S for t, J in f["peaks"])
    return ("SPLICE_SUSPECTED" if flagged else "NO_SPLICE_DETECTED"), loc


def tune_splice(rows):
    dev = [r for r in rows if r["task"] == "splice" and r["split"] == "dev" and r["cls"] == "H1"]
    none = [r for r in dev if r["kind"] == "none"]
    man = [r for r in dev if r["kind"] != "none"]
    best, table = None, []
    for t_line in [12.0, 15.0, 20.0, 25.0, 30.0]:
        for theta in [x / 20 for x in range(4, 63)]:
            nn = [r for r in none if splice_decision(r, theta, t_line)[0] != "NO_GRID_SIGNAL"]
            if len(nn) < 20:
                continue
            fa = sum(splice_decision(r, theta, t_line)[0] == "SPLICE_SUSPECTED" for r in nn) / len(nn)
            loc = sum(splice_decision(r, theta, t_line)[1] for r in man) / len(man)
            table.append(dict(t_line=t_line, theta=theta, far=round(fa, 4), n_none_with_grid=len(nn),
                              tpr_localised_all=round(loc, 4)))
            if fa <= FAR_TARGET and (best is None or loc > best[0]):
                best = (loc, dict(theta=theta, t_line=t_line))
    return best[1], table, dict(n_dev_none=len(none), n_dev_manip=len(man))


# ---------------------------------------------------------------- report
def report(rows):
    sp = sc.load_params()
    spl = json.load(open(os.path.join(HERE, "splice_params.json")))
    res = dict(labels="real = unmodified ENF-WHU clips; synthetic = ffmpeg asetrate/atempo speed changes and "
                      "numpy sample-exact splices of real ENF-WHU audio",
               speed_params={k: sp[k] for k in ["lam", "s_k1", "s_alt", "margin", "min_lines_alt", "k_tol",
                                                "amb_margin", "t_line", "t_present", "n_harm"]},
               splice_params=spl, far_target=FAR_TARGET)
    for split in ["dev", "holdout"]:
        R = [r for r in rows if r["task"] == "speed" and r["split"] == split]
        dec = {id(r): speed_decision(r, sp) for r in R}
        S = res.setdefault(split, {})
        # originals -> per-recording CONSISTENT status for conditional TPR
        orig_ok = {(r["rec"], r["start_idx"], r["L"]): dec[id(r)] == "CONSISTENT_WITH_REALTIME"
                   for r in R if r["method"] == "orig"}
        # --- unmodified H1: decision distribution + FAR
        u = defaultdict(lambda: defaultdict(int))
        for r in R:
            if r["cls"] == "H1" and r["method"] == "orig":
                u[r["L"]][dec[id(r)]] += 1
                u["all"][dec[id(r)]] += 1
        S["h1_unmodified"] = {str(L): dict(counts=dict(c), n=sum(c.values()),
                                           false_alarm_speed_altered=wilson(c["SPEED_ALTERED_REVIEW"], sum(c.values())),
                                           consistent=wilson(c["CONSISTENT_WITH_REALTIME"], sum(c.values())))
                              for L, c in u.items()}
        # --- H0
        h = defaultdict(lambda: defaultdict(int))
        for r in R:
            if r["cls"] == "H0":
                key = f"{r['method']}_k{r['k']}_L{r['L']}"
                h[key][dec[id(r)]] += 1
                h[f"{r['method']}_k{r['k']}_all"][dec[id(r)]] += 1
        S["h0"] = {k: dict(counts=dict(c), n=sum(c.values()),
                           no_grid_signal=wilson(c["NO_GRID_SIGNAL"], sum(c.values())),
                           speed_altered=wilson(c["SPEED_ALTERED_REVIEW"], sum(c.values())))
                   for k, c in sorted(h.items())}
        # --- manipulated
        for method in ["rate", "tempo"]:
            tab = {}
            for r in R:
                if r["cls"] != "H1" or r["method"] != method:
                    continue
                key = (r["k"], r["L"])
                t = tab.setdefault(key, dict(n=0, det=0, n_cond=0, det_cond=0, k_ok=0, k_oct=0, cons=0, nogrid=0))
                d = dec[id(r)]
                t["n"] += 1
                t["det"] += d == "SPEED_ALTERED_REVIEW"
                t["cons"] += d == "CONSISTENT_WITH_REALTIME"
                t["nogrid"] += d == "NO_GRID_SIGNAL"
                if orig_ok.get((r["rec"], r["start_idx"], r["L"])):
                    t["n_cond"] += 1
                    t["det_cond"] += d == "SPEED_ALTERED_REVIEW"
                if d == "SPEED_ALTERED_REVIEW":
                    kh = r["f"][str(sp["lam"])]["bbest"] / 50.0
                    t["k_ok"] += abs(kh - r["k"]) / r["k"] <= 0.01
                    t["k_oct"] += abs(kh / 2 - r["k"]) / r["k"] <= 0.01 or abs(kh * 2 - r["k"]) / r["k"] <= 0.01
            S[f"speed_{method}"] = {f"k{k}_L{L}": dict(
                tpr=wilson(t["det"], t["n"]),
                tpr_given_original_consistent=wilson(t["det_cond"], t["n_cond"]),
                consistent_with_realtime=wilson(t["cons"], t["n"]),
                no_grid_signal=wilson(t["nogrid"], t["n"]),
                k_within_1pct_among_detections=wilson(t["k_ok"], t["det"]),
                k_octave_error_among_detections=wilson(t["k_oct"], t["det"]))
                for (k, L), t in sorted(tab.items())}
        # pooled per k (rate) and per L
        for method in ["rate", "tempo"]:
            byk, byL = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
            for r in R:
                if r["cls"] == "H1" and r["method"] == method:
                    d = dec[id(r)] == "SPEED_ALTERED_REVIEW"
                    byk[r["k"]][0] += d; byk[r["k"]][1] += 1
                    byL[r["L"]][0] += d; byL[r["L"]][1] += 1
            S[f"speed_{method}_by_k"] = {str(k): wilson(*v) for k, v in sorted(byk.items())}
            S[f"speed_{method}_by_L"] = {str(L): wilson(*v) for L, v in sorted(byL.items())}
        # --- splices
        Q = [r for r in rows if r["task"] == "splice" and r["split"] == split and r["cls"] == "H1"]
        st = defaultdict(lambda: dict(n=0, nogrid=0, flag=0, loc=0, n_grid=0, flag_grid=0, loc_grid=0))
        for r in Q:
            d, loc = splice_decision(r, spl["theta"], spl["t_line"])
            key = f"{r['kind']}_{r['d']}s_L{r['L']}" if r["kind"] != "none" else f"none_L{r['L']}"
            for kk in (key, f"{r['kind']}_all"):
                t = st[kk]
                t["n"] += 1
                t["nogrid"] += d == "NO_GRID_SIGNAL"
                t["flag"] += d == "SPLICE_SUSPECTED"
                t["loc"] += loc
                if d != "NO_GRID_SIGNAL":
                    t["n_grid"] += 1
                    t["flag_grid"] += d == "SPLICE_SUSPECTED"
                    t["loc_grid"] += loc
        S["splice"] = {k: dict(n=t["n"], no_grid_signal=wilson(t["nogrid"], t["n"]),
                               flagged=wilson(t["flag"], t["n"]),
                               flagged_and_localised_1p5s=wilson(t["loc"], t["n"]),
                               flagged_given_grid=wilson(t["flag_grid"], t["n_grid"]),
                               localised_given_grid=wilson(t["loc_grid"], t["n_grid"]))
                       for k, t in sorted(st.items())}
        Q0 = [r for r in rows if r["task"] == "splice" and r["split"] == split and r["cls"] == "H0"]
        c = defaultdict(int)
        for r in Q0:
            c[splice_decision(r, spl["theta"], spl["t_line"])[0]] += 1
        S["splice_h0"] = dict(counts=dict(c), n=len(Q0), no_grid_signal=wilson(c["NO_GRID_SIGNAL"], len(Q0)))
        # --- headline scenario
        sc8 = S["speed_rate"].get("k1.75_L8")
        S["scenario_8s_at_1.75x"] = sc8
    json.dump(res, open(os.path.join(HERE, "RESULTS.json"), "w"), indent=1)
    return res


def main():
    rows = load_rows()
    if sys.argv[1] == "tune":
        sp, tab, nn = tune_speed(rows)
        spl, tab2, nn2 = tune_splice(rows)
        json.dump(sp, open(os.path.join(HERE, "speed_params.json"), "w"), indent=1)
        json.dump(spl, open(os.path.join(HERE, "splice_params.json"), "w"), indent=1)
        json.dump(dict(speed_chosen=sp, speed_counts=nn, splice_chosen=spl, splice_counts=nn2,
                       speed_grid=tab, splice_grid=tab2), open(os.path.join(HERE, "eval", "tuning.json"), "w"))
        print("speed:", sp, nn)
        print("splice:", spl, nn2)
        best = [t for t in tab if all(t[k] == sp[k] for k in sp)][0]
        print("dev at chosen speed params:", best)
        print("dev at chosen splice params:", [t for t in tab2 if t["theta"] == spl["theta"] and t["t_line"] == spl["t_line"]][0])
    else:
        res = report(rows)
        for split in ["dev", "holdout"]:
            print(split, "8s@1.75:", json.dumps(res[split]["scenario_8s_at_1.75x"]["tpr"]),
                  "FAR all:", json.dumps(res[split]["h1_unmodified"]["all"]["false_alarm_speed_altered"]))


if __name__ == "__main__":
    main()
