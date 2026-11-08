"""
Part 2 of empirical API probing:
1. Binary search exact earliest date in Elexon BMRS /system/frequency.
2. Check /system/frequency/stream max query span (1d, 7d, 14d, 30d).
3. Poll Elexon /system/frequency 5 times over 40 seconds to measure update batching and latency range.
4. Inspect ukgridwatch.co.uk/ukgw-live.js to verify its underlying data source.
"""
import json
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUT_DIR = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "GhostClock-W02-Research/1.0 (UCL-AgentVerse-2026)"}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def find_earliest_elexon(sess: requests.Session):
    # We already found 2021-08-30T00:00:00Z via binary search; verify 2021-08-29 to 2021-08-31 directly
    url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency"
    r = sess.get(url, params={"from": "2021-08-29T00:00:00Z", "to": "2021-08-30T02:00:00Z"}, timeout=20)
    rows = r.json().get("data", []) if r.status_code == 200 else []
    s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
    return {
        "earliest_record": s_rows[0] if s_rows else None,
        "second_record": s_rows[1] if len(s_rows) > 1 else None,
        "rows_in_first_2h": len(s_rows),
    }


def check_stream_spans(sess: requests.Session):
    stream_url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
    freq_ds_url = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ"
    now_dt = datetime.now(timezone.utc)
    t_to = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for days in [1, 7, 14, 30]:
        t_from = (now_dt - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = sess.get(stream_url, params={"from": t_from, "to": t_to}, timeout=30)
            info = {"status": r.status_code}
            if r.status_code == 200:
                rows = r.json()
                info["row_count"] = len(rows)
                if rows:
                    s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
                    info["earliest"] = s_rows[0]["measurementTime"]
                    info["latest"] = s_rows[-1]["measurementTime"]
            else:
                info["body"] = r.text[:300]
            out[f"stream_{days}d"] = info
        except Exception as e:
            out[f"stream_{days}d"] = {"error": str(e)}

    for days in [1, 2]:
        t_from = (now_dt - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = sess.get(
                freq_ds_url,
                params={"measurementDateTimeFrom": t_from, "measurementDateTimeTo": t_to},
                timeout=20,
            )
            out[f"datasets_FREQ_{days}d"] = {
                "status": r.status_code,
                "body_or_count": len(r.json().get("data", [])) if r.status_code == 200 else r.text[:300],
            }
        except Exception as e:
            out[f"datasets_FREQ_{days}d"] = {"error": str(e)}
    return out


def measure_live_latency_series(sess: requests.Session):
    url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency"
    samples = []
    for i in range(6):
        now_dt = datetime.now(timezone.utc)
        t_from = (now_dt - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t_to = (now_dt + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = sess.get(url, params={"from": t_from, "to": t_to}, timeout=15)
            srv_date = r.headers.get("Date")
            rows = r.json().get("data", []) if r.status_code == 200 else []
            s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
            if s_rows and srv_date:
                srv_dt = parsedate_to_datetime(srv_date)
                lat_dt = datetime.fromisoformat(s_rows[-1]["measurementTime"].replace("Z", "+00:00"))
                samples.append({
                    "poll_idx": i,
                    "server_utc": srv_dt.isoformat(),
                    "latest_measurementTime": s_rows[-1]["measurementTime"],
                    "latest_frequency": s_rows[-1]["frequency"],
                    "latency_s": (srv_dt - lat_dt).total_seconds(),
                    "row_count_last_15m": len(s_rows),
                })
        except Exception as e:
            samples.append({"poll_idx": i, "error": str(e)})
        if i < 5:
            time.sleep(8)
    return samples


def inspect_ukgridwatch_js(sess: requests.Session):
    out = {}
    try:
        r = sess.get("https://ukgridwatch.co.uk/ukgw-live.js", timeout=15)
        out["status"] = r.status_code
        out["length"] = len(r.text)
        out["snippet"] = r.text[:3000]
    except Exception as e:
        out["error"] = str(e)
    return out


def main():
    sess = make_session()
    print("Finding earliest Elexon record...")
    earliest = find_earliest_elexon(sess)
    print("Earliest Elexon:", earliest)

    print("Checking stream spans...")
    spans = check_stream_spans(sess)

    print("Inspecting ukgridwatch JS...")
    ukgw = inspect_ukgridwatch_js(sess)

    print("Measuring live latency across 6 polls (40s total)...")
    lat = measure_live_latency_series(sess)

    out_path = OUT_DIR / "probe_elexon_part2.json"
    out_path.write_text(
        json.dumps(
            {
                "earliest_elexon": earliest,
                "stream_spans": spans,
                "live_latency_polls": lat,
                "ukgridwatch_js": ukgw,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
