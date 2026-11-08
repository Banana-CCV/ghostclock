"""
Probe Elexon BMRS OpenAPI spec and exact query parameters (`from`/`to` vs `measurementDateTimeFrom`/`measurementDateTimeTo`),
plus inspect the data sources inside ukgridwatch.co.uk, gridwatch.templar.co.uk, dynamicdemand.co.uk, and grid.iamkate.com.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests

OUT_DIR = Path(__file__).resolve().parent
HEADERS = {"User-Agent": "GhostClock-W02-Research/1.0 (UCL-AgentVerse-2026)"}


def check_elexon_openapi():
    res = {}
    # Try common openapi URLs on data.elexon.co.uk
    for path in [
        "https://data.elexon.co.uk/bmrs/api/v1/swagger/v1/swagger.json",
        "https://data.elexon.co.uk/bmrs/api/v1/openapi.json",
        "https://data.elexon.co.uk/bmrs/swagger/v1/swagger.json",
    ]:
        try:
            r = requests.get(path, headers=HEADERS, timeout=15)
            res[path] = {"status": r.status_code}
            if r.status_code == 200:
                spec = r.json()
                paths = spec.get("paths", {})
                freq_paths = {k: v for k, v in paths.items() if "freq" in k.lower()}
                res[path]["freq_paths"] = freq_paths
                break
        except Exception as e:
            res[path] = {"error": str(e)}

    # Also test `from` and `to` on /system/frequency and /datasets/FREQ
    now_dt = datetime.now(timezone.utc)
    t_to = (now_dt + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_from_2h = (now_dt - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    test_calls = [
        ("sys_freq_from_to_2h", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency", {"from": t_from_2h, "to": t_to}),
        ("datasets_FREQ_meas_2h", "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ", {"measurementDateTimeFrom": t_from_2h, "measurementDateTimeTo": t_to}),
        ("datasets_FREQ_stream_2h", "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ/stream", {"measurementDateTimeFrom": t_from_2h, "measurementDateTimeTo": t_to}),
        ("sys_freq_stream_from_to_2h", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream", {"from": t_from_2h, "to": t_to}),
    ]

    calls_out = {}
    for label, url, params in test_calls:
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            srv_date = r.headers.get("Date")
            info = {"status": r.status_code, "server_date": srv_date, "url": r.url}
            if r.status_code == 200:
                p = r.json()
                rows = p.get("data", p if isinstance(p, list) else [])
                info["row_count"] = len(rows)
                if rows:
                    s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
                    info["earliest"] = s_rows[0]
                    info["latest"] = s_rows[-1]
                    if srv_date:
                        srv_dt = parsedate_to_datetime(srv_date)
                        lat_dt = datetime.fromisoformat(s_rows[-1]["measurementTime"].replace("Z", "+00:00"))
                        info["latency_s"] = (srv_dt - lat_dt).total_seconds()
            else:
                info["body"] = r.text[:400]
            calls_out[label] = info
        except Exception as e:
            calls_out[label] = {"error": str(e)}

    # Test max span with `from` and `to` on /system/frequency and /system/frequency/stream
    for days in [1, 2, 7, 8, 14, 31]:
        t_f = (now_dt - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for ep_name, ep_url in [
            ("sys_freq", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency"),
            ("sys_freq_stream", "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"),
        ]:
            try:
                r = requests.get(ep_url, params={"from": t_f, "to": t_to}, headers=HEADERS, timeout=30)
                info = {"status": r.status_code}
                if r.status_code == 200:
                    p = r.json()
                    rows = p.get("data", p if isinstance(p, list) else [])
                    info["row_count"] = len(rows)
                    if rows:
                        s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
                        info["earliest"] = s_rows[0]["measurementTime"]
                        info["latest"] = s_rows[-1]["measurementTime"]
                else:
                    info["body"] = r.text[:300]
                calls_out[f"{ep_name}_{days}d"] = info
            except Exception as e:
                calls_out[f"{ep_name}_{days}d"] = {"error": str(e)}

    # Test earliest history on Elexon with `from` and `to`
    for year in [2015, 2018, 2020, 2022, 2023, 2024, 2025]:
        t_f = f"{year}-06-01T00:00:00Z"
        t_t = f"{year}-06-01T01:00:00Z"
        try:
            r = requests.get(
                "https://data.elexon.co.uk/bmrs/api/v1/system/frequency",
                params={"from": t_f, "to": t_t},
                headers=HEADERS,
                timeout=20,
            )
            info = {"status": r.status_code}
            if r.status_code == 200:
                p = r.json()
                rows = p.get("data", p if isinstance(p, list) else [])
                info["row_count"] = len(rows)
                if rows:
                    info["earliest"] = rows[0]["measurementTime"]
                    info["latest"] = rows[-1]["measurementTime"]
            else:
                info["body"] = r.text[:300]
            calls_out[f"history_{year}"] = info
        except Exception as e:
            calls_out[f"history_{year}"] = {"error": str(e)}

    res["calls"] = calls_out
    return res


def inspect_other_dashboards():
    out = {}
    for name, url in [
        ("ukgridwatch", "https://ukgridwatch.co.uk/"),
        ("gridwatch_templar", "https://www.gridwatch.templar.co.uk/"),
        ("dynamic_demand", "http://www.dynamicdemand.co.uk/grid.htm"),
        ("iamkate", "https://grid.iamkate.com/"),
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            text = r.text
            # Extract URLs, API references, fetch/XHR calls, frequency mentions
            urls = re.findall(r'https?://[^\s"\'<>]+', text)
            api_refs = re.findall(r'["\'](/[^"\']*(?:api|freq|json|csv|data|live|stream)[^"\']*)["\']', text, flags=re.I)
            out[name] = {
                "external_urls_sample": list(dict.fromkeys(urls))[:25],
                "relative_api_refs": list(dict.fromkeys(api_refs))[:25],
            }
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


def main():
    elexon_res = check_elexon_openapi()
    dash_res = inspect_other_dashboards()
    out_file = OUT_DIR / "probe_elexon_details.json"
    out_file.write_text(json.dumps({"elexon": elexon_res, "dashboards": dash_res}, indent=2), encoding="utf-8")
    print(f"Wrote {out_file}")


if __name__ == "__main__":
    main()
