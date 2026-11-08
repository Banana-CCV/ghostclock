"""List files of Zenodo record 3549379 (ENF Moving Video Database) via the API."""
import json, sys, requests
r = requests.get("https://zenodo.org/api/records/3549379", timeout=60)
r.raise_for_status()
rec = r.json()
files = rec["files"]
out = [{"key": f["key"], "size": f["size"], "checksum": f["checksum"],
        "url": f["links"]["self"]} for f in files]
out.sort(key=lambda e: e["size"])
for e in out:
    print(f'{e["key"]:40s} {e["size"]/1e6:10.1f} MB  {e["checksum"]}')
print("total GB", sum(e["size"] for e in out) / 1e9)
json.dump(out, open(sys.argv[1], "w"), indent=1)
