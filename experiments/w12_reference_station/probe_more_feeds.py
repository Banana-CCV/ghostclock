"""
Probe additional GB and Continental Europe frequency endpoints to complete Step B research.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import time
import requests

headers = {"User-Agent": "GhostClock-Research/1.0"}

URLS = [
    ("netzfrequenz_15", "https://www.netzfrequenz.info/json/15.json"),
    ("netzfrequenz_act2", "https://www.netzfrequenz.info/json/act2.json"),
    ("energy_charts_v2_2024", "https://api.energy-charts.info/v2/frequency?region=DE-Freiburg&start=2024-11-01T00:00Z&end=2024-11-01T00:10Z"),
    ("energy_charts_v1_2024", "https://api.energy-charts.info/frequency?region=DE-Freiburg&start=2024-11-01T00:00Z&end=2024-11-01T00:10Z"),
    ("energy_charts_v2_today", "https://api.energy-charts.info/v2/frequency?region=DE-Freiburg"),
    ("iamkate_grid", "https://grid.iamkate.com/"),
    ("gridwatch_co_uk", "https://www.gridwatch.co.uk/"),
    ("gridwatch_templar", "https://www.gridwatch.templar.co.uk/"),
    ("mainsfrequency_com", "https://www.mainsfrequency.com/"),
    ("fnet_utk", "http://fnetpublic.utk.edu/"),
]

def check_one(item):
    name, url = item
    t0 = time.time()
    try:
        r = requests.get(url, headers=headers, timeout=4.0)
        return name, {
            "url": url,
            "http_status": r.status_code,
            "elapsed_s": round(time.time() - t0, 3),
            "content_type": r.headers.get("Content-Type", ""),
            "length_bytes": len(r.content),
            "preview": r.text[:400],
        }
    except Exception as e:
        return name, {"url": url, "error": str(e)}

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=10) as ex:
        res = dict(ex.map(check_one, URLS))
    with open("work/W12/probe_more_feeds.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print("Saved work/W12/probe_more_feeds.json")
