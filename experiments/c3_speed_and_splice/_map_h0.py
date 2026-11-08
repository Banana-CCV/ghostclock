# One-off helper: map H0 crops (01-40) to their source O01-O10 recording by
# normalised cross-correlation of a 4 s snippet (signals decimated to 1 kHz for speed).
import soundfile as sf, numpy as np, glob, json, os, sys
from scipy.signal import fftconvolve, resample_poly
D='datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H0'
O={os.path.basename(f)[:-4]:resample_poly(sf.read(f)[0],1,8) for f in sorted(glob.glob(D+'/O*.wav'))}
res={}
for i in range(1,41):
    x=resample_poly(sf.read(f'{D}/{i:02d}.wav')[0],1,8); s=x[1000:5000]; s=s-s.mean()
    best=None
    for k,o in O.items():
        c=fftconvolve(o,s[::-1],mode='valid'); e=np.sqrt(np.maximum(fftconvolve(o**2,np.ones(len(s)),mode='valid'),1e-20))*np.linalg.norm(s)
        r=c/e; j=int(np.argmax(r))
        if best is None or r[j]>best[1]: best=(k,float(r[j]),(j-1000)/1000)
    res[f'{i:02d}']={'source':best[0],'ncc':round(best[1],4),'offset_s':round(best[2],3),'dur_s':len(x)/1000}
    print(i,res[f'{i:02d}'],flush=True)
json.dump(res,open('work/C3/h0_crop_map.json','w'),indent=1)
