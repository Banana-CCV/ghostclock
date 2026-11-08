"""Probe: is H1_ref/xxx_ref.wav an exact sample crop of the H1_ref_one_day file? (diagnostic)"""
import soundfile as sf, numpy as np, glob, os, sys
from scipy.signal import fftconvolve
B='datasets/raw/enf-whu/repo/ENF-WHU-Dataset'
for rid in sys.argv[1:]:
    day=[f for f in glob.glob(f'{B}/H1_ref_one_day/*.wav') if (lambda a: int(a[0])<=int(rid)<=int(a[-1]))(os.path.basename(f).split('_')[0].split('-'))][0]
    d,_=sf.read(day,dtype='int16'); r,_=sf.read(f'{B}/H1_ref/{rid}_ref.wav',dtype='int16')
    q=r[:4000].astype(float); dd=d.astype(float)
    c=fftconvolve(dd,q[::-1],mode='valid')
    k=int(np.argmax(c))
    seg=d[k:k+len(r)]
    exact=np.array_equal(seg,r) if len(seg)==len(r) else None
    diff=np.abs(seg[:len(r)].astype(int)-r[:len(seg)].astype(int)).max()
    print(rid, os.path.basename(day), 'lag_samples',k,'lag_s',k/400,'exact',exact,'maxabsdiff',diff, 'daylen',len(d))
