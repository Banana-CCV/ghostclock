"""Map each H0 crop (01..40.wav) to its source recording (O01..O10.wav) by exact sample search.
Writes work/C1/h0_groups.json. Deterministic, no tuning."""
import soundfile as sf, numpy as np, glob, os, json
B='datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H0'
src={os.path.basename(f)[:-4]: sf.read(f,dtype='int16')[0] for f in sorted(glob.glob(B+'/O*.wav'))}
out={}
for f in sorted(glob.glob(B+'/[0-9]*.wav')):
    x=sf.read(f,dtype='int16')[0]
    # pick a probe with energy, search exact match of 64 samples via rolling compare on candidates
    p=x[8000:8064]
    hit=None
    for name,s in src.items():
        # candidate positions where first sample matches, then verify
        cand=np.flatnonzero(s[:len(s)-len(x)+8000+1]==p[0])
        for c in cand:
            if np.array_equal(s[c:c+64],p):
                st=c-8000
                if st>=0 and np.array_equal(s[st:st+len(x)],x):
                    hit=(name,int(st)); break
        if hit: break
    out[os.path.basename(f)[:-4]]={'source':hit[0] if hit else None,'start_sample':hit[1] if hit else None,
                                   'start_s':hit[1]/8000 if hit else None}
    print(os.path.basename(f), out[os.path.basename(f)[:-4]])
json.dump(out,open('work/C1/h0_groups.json','w'),indent=1)
