"""
Deep probe of live Elexon latency, Continental Europe live frequency (netzfrequenz.info,
energy-charts), additional GB frequency feeds, and high-resolution audio spectrum on
the local microphone.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import time
import numpy as np
import requests
import sounddevice as sd

headers = {"User-Agent": "GhostClock-Research/1.0"}

def test_elexon_live():
    now = datetime.now(timezone.utc)
    t_from = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_to = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://data.elexon.co.uk/bmrs/api/v1/system/frequency?from={t_from}&to={t_to}&format=json"
    t0 = time.time()
    r = requests.get(url, headers=headers, timeout=5)
    t_req = datetime.now(timezone.utc)
    j = r.json()
    data = j.get("data", [])
    if not data:
        return {"status": r.status_code, "count": 0}
    # Sort by measurementTime
    data_sorted = sorted(data, key=lambda x: x["measurementTime"])
    latest = data_sorted[-1]
    latest_dt = datetime.fromisoformat(latest["measurementTime"].replace("Z", "+00:00"))
    latency_s = (t_req - latest_dt).total_seconds()
    # Check diffs
    ts_list = [
        datetime.fromisoformat(x["measurementTime"].replace("Z", "+00:00")).timestamp()
        for x in data_sorted
    ]
    diffs = np.diff(ts_list)
    return {
        "url": url,
        "http_status": r.status_code,
        "elapsed_s": round(time.time() - t0, 3),
        "count": len(data_sorted),
        "first": data_sorted[0],
        "last_5": data_sorted[-5:],
        "request_utc": t_req.isoformat(),
        "latest_measurement_utc": latest["measurementTime"],
        "latency_s": round(latency_s, 3),
        "cadence_min_s": float(np.min(diffs)) if len(diffs) else None,
        "cadence_max_s": float(np.max(diffs)) if len(diffs) else None,
        "cadence_median_s": float(np.median(diffs)) if len(diffs) else None,
    }

def test_netzfrequenz_series():
    samples = []
    for i in range(5):
        t0 = time.time()
        try:
            r = requests.get("https://www.netzfrequenz.info/json/act.json", headers=headers, timeout=3)
            val = float(r.text.strip())
            samples.append({
                "ts_utc": round(time.time(), 3),
                "f_hz": val,
                "http_status": r.status_code,
            })
        except Exception as e:
            samples.append({"ts_utc": round(time.time(), 3), "error": str(e)})
        if i < 4:
            time.sleep(1.2)
    return samples

def inspect_energy_charts():
    try:
        r = requests.get("https://api.energy-charts.info/openapi.json", headers=headers, timeout=4)
        spec = r.json()
        freq_spec = spec.get("paths", {}).get("/v2/frequency", {})
        freq_v1_spec = spec.get("paths", {}).get("/frequency", {})
        return {"v2_frequency": freq_spec, "v1_frequency": freq_v1_spec}
    except Exception as e:
        return {"error": str(e)}

def search_neso_frequency_packages():
    try:
        r = requests.get(
            "https://api.neso.energy/api/3/action/package_search?q=frequency",
            headers=headers,
            timeout=5,
        )
        j = r.json()
        results = j.get("result", {}).get("results", [])
        pkgs = []
        for p in results[:10]:
            pkgs.append({
                "name": p.get("name"),
                "title": p.get("title"),
                "num_resources": len(p.get("resources", [])),
            })
        return pkgs
    except Exception as e:
        return {"error": str(e)}

def analyze_local_mic_8s():
    fs = 8000
    dur = 6.0
    rec = sd.rec(int(dur * fs), samplerate=fs, channels=1, dtype="float64")
    sd.wait()
    x = rec[:, 0]
    # Zero-padded FFT for fine frequency check around 50, 100, 150, 200, 250, 300 Hz
    nfft = 65536
    w = np.hanning(len(x))
    X = np.abs(np.fft.rfft((x - np.mean(x)) * w, n=nfft))**2
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    harmonics = {}
    for h in [50, 100, 150, 200, 250, 300]:
        band = (freqs >= h - 0.5) & (freqs <= h + 0.5)
        noise = ((freqs >= h - 8.0) & (freqs < h - 1.5)) | ((freqs > h + 1.5) & (freqs <= h + 8.0))
        idx_max = np.argmax(X[band])
        f_peak = float(freqs[band][idx_max])
        p_peak = float(X[band][idx_max])
        p_noise_med = float(np.median(X[noise]))
        snr_db = float(10.0 * np.log10((p_peak + 1e-30) / (p_noise_med + 1e-30)))
        harmonics[str(h)] = {
            "f_peak_hz": round(f_peak, 4),
            "f_fund_equiv_hz": round(f_peak / (h / 50.0), 4),
            "snr_db": round(snr_db, 2),
        }
    return {
        "duration_s": dur,
        "fs": fs,
        "rms": round(float(np.sqrt(np.mean(x**2))), 6),
        "peak": round(float(np.max(np.abs(x))), 6),
        "harmonics": harmonics,
    }

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_elex = ex.submit(test_elexon_live)
        f_netz = ex.submit(test_netzfrequenz_series)
        f_ec = ex.submit(inspect_energy_charts)
        f_neso = ex.submit(search_neso_frequency_packages)
        f_mic = ex.submit(analyze_local_mic_8s)
        out = {
            "elexon_live": f_elex.result(),
            "netzfrequenz_live_poll": f_netz.result(),
            "energy_charts_spec": f_ec.result(),
            "neso_frequency_packages": f_neso.result(),
            "local_mic_6s": f_mic.result(),
        }
    with open("work/W12/probe_live_details.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("Saved work/W12/probe_live_details.json")
