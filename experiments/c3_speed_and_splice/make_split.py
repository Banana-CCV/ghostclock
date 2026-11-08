"""Freeze a seeded, session-grouped ~60/40 dev/holdout split of ENF-WHU H1 and H0.

H1 groups = recording day, taken from the H1_ref_one_day file names
("003-004_ref.wav" -> recordings 003 and 004 share a day). 28 groups.
H0 groups = source long recording O01..O10; crops 01..40 are assigned to their
source via h0_crop_map.json (normalised cross-correlation, _map_h0.py), so a crop
never lands on the other side of its source.
"""
import json, os, random, re, glob

ROOT = r"<WORKSPACE>\datasets\raw\enf-whu\repo\ENF-WHU-Dataset"
HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261108


def groups_h1():
    g = []
    for f in sorted(os.listdir(os.path.join(ROOT, "H1_ref_one_day"))):
        m = re.match(r"(\d+)(?:-(\d+))?_ref\.wav", f)
        a = int(m.group(1)); b = int(m.group(2) or a)
        g.append([f"{i:03d}" for i in range(a, b + 1)])
    return g


def split_groups(groups, frac, rng):
    order = list(range(len(groups)))
    rng.shuffle(order)
    total = sum(len(x) for x in groups)
    dev, n = [], 0
    for i in order:
        if n < frac * total:
            dev.append(i); n += len(groups[i])
    return sorted(dev), sorted(set(order) - set(dev))


def main():
    rng = random.Random(SEED)
    g1 = groups_h1()
    assert sum(len(x) for x in g1) == 130
    d1, h1 = split_groups(g1, 0.6, rng)
    cmap = json.load(open(os.path.join(HERE, "h0_crop_map.json")))
    srcs = [f"O{i:02d}" for i in range(1, 11)]
    rng2 = random.Random(SEED + 1)
    srcs_sh = srcs[:]; rng2.shuffle(srcs_sh)
    h0_dev_src, h0_hold_src = sorted(srcs_sh[:6]), sorted(srcs_sh[6:])
    out = dict(
        seed=SEED, frac_dev_target=0.6,
        note="Grouped by recording day (H1) and by source recording (H0). Frozen before any tuning.",
        H1=dict(dev=sorted(r for i in d1 for r in g1[i]), holdout=sorted(r for i in h1 for r in g1[i]),
                dev_groups=[g1[i] for i in d1], holdout_groups=[g1[i] for i in h1]),
        H0=dict(dev_sources=h0_dev_src, holdout_sources=h0_hold_src,
                dev_crops=sorted(k for k, v in cmap.items() if v["source"] in h0_dev_src),
                holdout_crops=sorted(k for k, v in cmap.items() if v["source"] in h0_hold_src),
                crop_map_min_ncc=min(v["ncc"] for v in cmap.values())),
    )
    out["counts"] = dict(H1_dev=len(out["H1"]["dev"]), H1_holdout=len(out["H1"]["holdout"]),
                         H1_dev_groups=len(d1), H1_holdout_groups=len(h1),
                         H0_dev_sources=6, H0_holdout_sources=4,
                         H0_dev_crops=len(out["H0"]["dev_crops"]), H0_holdout_crops=len(out["H0"]["holdout_crops"]))
    path = os.path.join(HERE, "split.json")
    if os.path.exists(path):
        raise SystemExit("split.json already frozen; refusing to overwrite")
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out["counts"]))


if __name__ == "__main__":
    main()
