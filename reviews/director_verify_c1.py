"""Director check of C1 holdout: recompute coverage / accuracy / false-match from the raw trial table + frozen thresholds."""
import json, os, pandas as pd
# runs inside the release repo: the C1 trial table and frozen thresholds are committed
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "c1_enfwhu_unseen_holdout")
t = pd.read_parquet(os.path.join(D, "trials", "final_w16_q_clip05_holdout.parquet"))
fz = json.load(open(os.path.join(D, "frozen.json")))
thr = {int(k): v for k, v in fz["thresholds"].items()}
print("columns:", list(t.columns))
print(t.head(3).to_string())
print("trial kinds:", t.iloc[:, :4].nunique().to_dict())
t["issued"] = t.apply(lambda r: r["peak"] >= thr[int(r["L"])], axis=1)
h1 = t[(t.kind == "h1_true") & (~t.gt_ambiguous)].copy()
for name, exp in (("gt+start", h1.gt_readme + h1.start), ("gt", h1.gt_readme)):
    err = (h1.lag - exp).abs()
    print(f"formula {name}: median |err| of issued 300s = {err[(h1.L==300)&h1.issued].median():.2f}")
h1["err"] = (h1.lag - h1.gt_readme).abs()  # gt_readme is already the excerpt's expected offset
for L in sorted(t.L.unique()):
    a = h1[h1.L == L]; iss = a[a.issued]
    w = t[(t.kind == "h1_wrong") & (t.L == L)]; h0 = t[(t.kind.str.startswith("h0")) & (t.L == L)]
    print(f"L={L:>3}: coverage {len(iss)}/{len(a)}  within5s {int((iss.err<=5).sum())}/{len(iss)}  "
          f"wrongday_FM {int(w.issued.sum())}/{len(w)}  h0_FM {int(h0.issued.sum())}/{len(h0)}")
