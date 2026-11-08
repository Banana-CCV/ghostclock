"""
Probe local audio hardware, NTP clock offset, and public GB / Continental Europe
grid frequency endpoints for Worker W12 (parallelized to finish <5s).
"""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct
import time
from datetime import datetime, timezone
import numpy as np
import requests
import sounddevice as sd
from scipy import signal

def check_single_ntp(srv):
    NTP_DELTA = 2208988800  # 1970-01-01 - 1900-01-01
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(1.5)
        msg = b'\x1b' + 47 * b'\0'
        t1 = time.time()
        client.sendto(msg, (srv, 123))
        data, _ = client.recvfrom(1024)
        t4 = time.time()
        client.close()
        if len(data) >= 48:
            unpacked = struct.unpack("!12I", data[:48])
            t2 = unpacked[8] + float(unpacked[9]) / 2**32 - NTP_DELTA
            t3 = unpacked[10] + float(unpacked[11]) / 2**32 - NTP_DELTA
            offset_s = ((t2 - t1) + (t3 - t4)) / 2.0
            rtt_s = (t4 - t1) - (t3 - t2)
            return {
                "server": srv,
                "status": "OK",
                "offset_s": round(offset_s, 6),
                "rtt_s": round(rtt_s, 6),
            }
    except Exception as e:
        return {"server": srv, "status": "ERR", "error": str(e)}

def check_ntp(servers=("time.cloudflare.com", "time.windows.com", "pool.ntp.org")):
    with ThreadPoolExecutor(max_workers=3) as ex:
        return list(ex.map(check_single_ntp, servers))

def check_audio_devices():
    devs = sd.query_devices()
    input_devs = []
    for idx, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            input_devs.append({
                "index": idx,
                "name": d.get("name"),
                "hostapi": d.get("hostapi"),
                "max_input_channels": d.get("max_input_channels"),
                "default_samplerate": d.get("default_samplerate"),
            })
    capture_info = {}
    try:
        fs = 8000
        dur = 2.0
        rec = sd.rec(int(dur * fs), samplerate=fs, channels=1, dtype="float64")
        sd.wait()
        x = rec[:, 0]
        rms = float(np.sqrt(np.mean(x**2)))
        peak = float(np.max(np.abs(x)))
        f, Pxx = signal.welch(x, fs=fs, nperseg=min(len(x), fs * 2))
        harmonic_snrs = {}
        for h in [50, 100, 150, 200, 250, 300]:
            sig_mask = (f >= h - 1.5) & (f <= h + 1.5)
            noise_mask = ((f >= h - 10.0) & (f < h - 2.0)) | ((f > h + 2.0) & (f <= h + 10.0))
            p_sig = float(np.max(Pxx[sig_mask])) if np.any(sig_mask) else 0.0
            p_noise = float(np.median(Pxx[noise_mask])) if np.any(noise_mask) else 1e-20
            snr_db = float(10.0 * np.log10((p_sig + 1e-30) / (p_noise + 1e-30)))
            peak_f = float(f[sig_mask][np.argmax(Pxx[sig_mask])]) if np.any(sig_mask) else float(h)
            harmonic_snrs[str(h)] = {"snr_db": round(snr_db, 2), "peak_f_hz": round(peak_f, 3)}
        capture_info = {
            "status": "OK",
            "fs": fs,
            "duration_s": dur,
            "rms": rms,
            "peak": peak,
            "harmonic_snrs": harmonic_snrs,
        }
    except Exception as e:
        capture_info = {"status": "ERR", "error": str(e)}
    return {"input_devices": input_devs, "live_capture_test": capture_info}

def fetch_one(item):
    name, url = item
    headers = {"User-Agent": "GhostClock-Research/1.0"}
    t0 = time.time()
    try:
        r = requests.get(url, headers=headers, timeout=3.5)
        dt = time.time() - t0
        text_preview = r.text[:400]
        info = {
            "url": url,
            "http_status": r.status_code,
            "elapsed_s": round(dt, 3),
            "content_type": r.headers.get("Content-Type", ""),
            "length_bytes": len(r.content),
            "preview": text_preview,
        }
        if r.status_code == 200 and "json" in r.headers.get("Content-Type", "").lower():
            try:
                j = r.json()
                if isinstance(j, list) and len(j) > 0:
                    info["list_len"] = len(j)
                    info["first_item"] = j[0]
                    info["last_item"] = j[-1]
                elif isinstance(j, dict) and "data" in j and isinstance(j["data"], list) and len(j["data"]) > 0:
                    info["data_len"] = len(j["data"])
                    info["first_item"] = j["data"][0]
                    info["last_item"] = j["data"][-1]
                elif name == "NESO_ckan_system_frequency" and "result" in j:
                    res = j["result"].get("resources", [])
                    info["num_resources"] = len(res)
                    info["latest_resources"] = [
                        {"name": x.get("name"), "last_modified": x.get("last_modified"), "url": x.get("url")}
                        for x in res[-5:]
                    ]
                    del info["preview"]
                elif name == "EnergyCharts_openapi":
                    paths = list(j.get("paths", {}).keys())
                    info["paths"] = paths
                    del info["preview"]
            except Exception as je:
                info["json_parse_err"] = str(je)
        return name, info
    except Exception as e:
        return name, {"url": url, "error": str(e)}

def check_endpoints():
    endpoints = [
        ("Elexon_system_frequency", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency?format=json"),
        ("Elexon_system_frequency_stream", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"),
        ("Elexon_datasets_FREQ_stream", "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ/stream"),
        ("NESO_ckan_system_frequency", "https://api.neso.energy/api/3/action/package_show?id=system-frequency-data"),
        ("Netzfrequenz_info_act", "https://www.netzfrequenz.info/json/act.json"),
        ("Netzfrequenzmessung_xml", "https://www.netzfrequenzmessung.de/frequenz02.xml"),
        ("EnergyCharts_openapi", "https://api.energy-charts.info/openapi.json"),
        ("EnergyCharts_frequency", "https://api.energy-charts.info/frequency"),
        ("Volton_latest", "https://public-data.volton.energy/v1/grid-frequency/latest.json"),
        ("GridRadar_query", "https://api.gridradar.net/query"),
    ]
    with ThreadPoolExecutor(max_workers=10) as ex:
        pairs = list(ex.map(fetch_one, endpoints))
    return dict(pairs)

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_ntp = ex.submit(check_ntp)
        f_aud = ex.submit(check_audio_devices)
        f_end = ex.submit(check_endpoints)
        report = {
            "probed_at_utc": datetime.now(timezone.utc).isoformat(),
            "ntp": f_ntp.result(),
            "audio": f_aud.result(),
            "endpoints": f_end.result(),
        }
    with open("work/W12/probe_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("Saved work/W12/probe_report.json")
