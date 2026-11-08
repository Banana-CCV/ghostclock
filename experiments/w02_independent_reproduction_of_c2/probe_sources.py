"""
Discovery and empirical probing script for GB grid frequency sources (W02).
Probes:
1. NESO CKAN API (package_show for system-frequency-data & package_search for frequency)
2. Elexon BMRS Insights API (/system/frequency and /system/frequency/stream)
3. Candidate alternative public GB frequency monitors (Gridwatch, DynamicDemand, etc.)
"""
import json
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests

OUT_DIR = Path(__file__).resolve().parent
PROBE_JSON = OUT_DIR / "probe_results.json"

HEADERS = {
    "User-Agent": "GhostClock-W02-Research/1.0 (UCL-AgentVerse-2026)"
}


def probe_neso():
    result = {}
    url = "https://api.neso.energy/api/3/action/package_show"
    try:
        r = requests.get(url, params={"id": "system-frequency-data"}, headers=HEADERS, timeout=30)
        result["status_code"] = r.status_code
        result["server_date"] = r.headers.get("Date")
        data = r.json()
        pkg = data.get("result", {})
        result["package_title"] = pkg.get("title")
        result["package_name"] = pkg.get("name")
        result["license_title"] = pkg.get("license_title")
        result["license_id"] = pkg.get("license_id")
        resources = pkg.get("resources", [])
        res_list = []
        for res in resources:
            res_list.append({
                "id": res.get("id"),
                "name": res.get("name"),
                "description": res.get("description"),
                "format": res.get("format"),
                "url": res.get("url"),
                "created": res.get("created"),
                "last_modified": res.get("last_modified"),
                "datastore_active": res.get("datastore_active"),
                "size": res.get("size"),
            })
        result["resource_count"] = len(res_list)
        result["resources"] = res_list
    except Exception as e:
        result["error"] = str(e)

    # Also search NESO CKAN for any other frequency packages (e.g. rolling/real-time)
    try:
        r2 = requests.get(
            "https://api.neso.energy/api/3/action/package_search",
            params={"q": "frequency", "rows": 50},
            headers=HEADERS,
            timeout=30,
        )
        pkgs = r2.json().get("result", {}).get("results", [])
        result["other_frequency_packages"] = [
            {
                "name": p.get("name"),
                "title": p.get("title"),
                "num_resources": len(p.get("resources", [])),
                "resources_sample": [
                    {"name": x.get("name"), "format": x.get("format"), "url": x.get("url")}
                    for x in p.get("resources", [])[:3]
                ],
            }
            for p in pkgs
        ]
    except Exception as e:
        result["search_error"] = str(e)

    return result


def probe_elexon():
    result = {}
    base_url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency"
    try:
        t0 = time.time()
        r = requests.get(base_url, params={"format": "json"}, headers=HEADERS, timeout=30)
        t1 = time.time()
        result["default_status"] = r.status_code
        result["response_time_s"] = round(t1 - t0, 3)
        result["server_date"] = r.headers.get("Date")
        result["rate_limit_headers"] = {
            k: v for k, v in r.headers.items()
            if "rate" in k.lower() or "limit" in k.lower() or "retry" in k.lower() or "remaining" in k.lower()
        }
        if r.status_code == 200:
            payload = r.json()
            rows = payload.get("data", payload if isinstance(payload, list) else [])
            result["default_row_count"] = len(rows)
            if rows:
                # Sort by measurementTime
                sorted_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
                result["default_earliest"] = sorted_rows[0]
                result["default_latest"] = sorted_rows[-1]
                result["sample_rows_last_5"] = sorted_rows[-5:]
                if result["server_date"]:
                    srv_dt = parsedate_to_datetime(result["server_date"])
                    latest_dt = datetime.fromisoformat(
                        sorted_rows[-1]["measurementTime"].replace("Z", "+00:00")
                    )
                    result["latency_seconds_vs_server_date"] = (srv_dt - latest_dt).total_seconds()
                    result["server_utc_iso"] = srv_dt.isoformat()
    except Exception as e:
        result["default_error"] = str(e)

    # Probe max query span on /system/frequency (try 1 day, 2 days, 7 days)
    span_tests = {}
    if result.get("server_utc_iso"):
        now_dt = datetime.fromisoformat(result["server_utc_iso"])
    else:
        now_dt = datetime.now(timezone.utc)

    for days in [1, 2, 7]:
        start_dt = now_dt - timedelta(days=days)
        try:
            r_span = requests.get(
                base_url,
                params={
                    "measurementDateTimeFrom": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "measurementDateTimeTo": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "format": "json",
                },
                headers=HEADERS,
                timeout=30,
            )
            info = {"status_code": r_span.status_code}
            if r_span.status_code == 200:
                p = r_span.json()
                rows = p.get("data", p if isinstance(p, list) else [])
                info["row_count"] = len(rows)
            else:
                info["body"] = r_span.text[:500]
            span_tests[f"standard_{days}d"] = info
        except Exception as e:
            span_tests[f"standard_{days}d"] = {"error": str(e)}

    # Probe /system/frequency/stream for 7 days
    stream_url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
    for days in [2, 7]:
        start_dt = now_dt - timedelta(days=days)
        try:
            r_st = requests.get(
                stream_url,
                params={
                    "measurementDateTimeFrom": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "measurementDateTimeTo": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                headers=HEADERS,
                timeout=45,
            )
            info = {"status_code": r_st.status_code}
            if r_st.status_code == 200:
                rows = r_st.json()
                info["row_count"] = len(rows)
                if rows:
                    s_rows = sorted(rows, key=lambda x: x.get("measurementTime", ""))
                    info["earliest"] = s_rows[0]
                    info["latest"] = s_rows[-1]
            else:
                info["body"] = r_st.text[:500]
            span_tests[f"stream_{days}d"] = info
        except Exception as e:
            span_tests[f"stream_{days}d"] = {"error": str(e)}

    result["span_tests"] = span_tests

    # Probe historical depth on Elexon (e.g., 2020, 2022, 2024, 2025)
    history_tests = {}
    for year in [2018, 2020, 2022, 2024, 2025]:
        t_from = f"{year}-06-01T00:00:00Z"
        t_to = f"{year}-06-01T01:00:00Z"
        try:
            rh = requests.get(
                base_url,
                params={
                    "measurementDateTimeFrom": t_from,
                    "measurementDateTimeTo": t_to,
                    "format": "json",
                },
                headers=HEADERS,
                timeout=20,
            )
            h_info = {"status_code": rh.status_code}
            if rh.status_code == 200:
                p = rh.json()
                rows = p.get("data", p if isinstance(p, list) else [])
                h_info["row_count"] = len(rows)
                if rows:
                    h_info["first"] = rows[0]
            else:
                h_info["body"] = rh.text[:300]
            history_tests[str(year)] = h_info
        except Exception as e:
            history_tests[str(year)] = {"error": str(e)}
    result["history_tests"] = history_tests
    return result


def probe_other_sources():
    candidates = {
        "gridwatch_templar": "https://www.gridwatch.templar.co.uk/",
        "ukgridwatch": "https://ukgridwatch.co.uk/",
        "dynamic_demand": "http://www.dynamicdemand.co.uk/grid.htm",
        "dynamic_demand_xml": "http://www.dynamicdemand.co.uk/grid.xml",
        "mainsfrequency_uk": "https://mainsfrequency.uk/",
        "netzfrequenzmessung_uk": "https://www.netzfrequenzmessung.de/en/",
        "powergridfrequency_org": "https://powergridfrequency.org/",
        "openpmu": "https://www.openpmu.org/",
        "energy_dashboard": "https://www.energydashboard.co.uk/live",
        "national_grid_live_iamkate": "https://grid.iamkate.com/",
    }
    out = {}
    for name, url in candidates.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            out[name] = {
                "url": url,
                "status_code": r.status_code,
                "content_type": r.headers.get("Content-Type"),
                "length": len(r.text),
                "snippet": r.text[:400].replace("\n", " "),
            }
        except Exception as e:
            out[name] = {"url": url, "error": str(e)}
    return out


def main():
    print("Probing NESO CKAN API...")
    neso = probe_neso()
    print(f"NESO resources found: {neso.get('resource_count')}")

    print("Probing Elexon BMRS API...")
    elexon = probe_elexon()
    print(f"Elexon default rows: {elexon.get('default_row_count')}, latency(s): {elexon.get('latency_seconds_vs_server_date')}")

    print("Probing candidate alternative GB frequency sources...")
    others = probe_other_sources()

    full = {
        "probed_at_system_utc": datetime.now(timezone.utc).isoformat(),
        "neso": neso,
        "elexon": elexon,
        "other_candidates": others,
    }
    PROBE_JSON.write_text(json.dumps(full, indent=2), encoding="utf-8")
    print(f"Saved probe results to {PROBE_JSON}")


if __name__ == "__main__":
    main()
