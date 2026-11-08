"""Director check of C4: recompute r between the saved RS video trace and the reference ENF trace over all lags."""
import os, numpy as np, pandas as pd
# runs inside the release repo: the saved C4 traces are committed
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiments", "c4_video_rolling_shutter")
v = pd.read_csv(os.path.join(D, "real_MOV2_rolling_shutter_trace.csv"))
r = pd.read_csv(os.path.join(D, "ref_MOV2_enf_trace.csv"))
print("video cols", list(v.columns)[:6], "ref cols", list(r.columns)[:6])
tv, fv = v.iloc[:, 0].to_numpy(float), v.iloc[:, 1].to_numpy(float)
tr, fr = r.iloc[:, 0].to_numpy(float), r.iloc[:, 1].to_numpy(float)
res = []
for lag in np.arange(0, 253, 0.5):
    fi = np.interp(tv + lag, tr, fr, left=np.nan, right=np.nan)
    m = np.isfinite(fi) & np.isfinite(fv)
    if m.sum() < 300:
        continue
    res.append((lag, np.corrcoef(fv[m], fi[m])[0, 1], m.sum(), np.sqrt(np.mean(((fv[m]-fv[m].mean())-(fi[m]-fi[m].mean()))**2))*1000))
res = np.array(res)
i = res[:, 1].argmax()
far = res[np.abs(res[:, 0] - res[i, 0]) > 10]
print(f"best lag={res[i,0]} r={res[i,1]:.4f} n={int(res[i,2])} demeaned_rmse={res[i,3]:.2f} mHz; best r >10 s away={far[:,1].max():.3f}")
