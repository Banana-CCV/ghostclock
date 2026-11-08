"""Download selected files from Zenodo 3549379 with resume + md5 verification.
usage: python zenodo_fetch.py <files.json> <outdir> <key> [<key> ...]"""
import hashlib, json, os, sys, time, requests
files = {e["key"]: e for e in json.load(open(sys.argv[1]))}
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)
for key in sys.argv[3:]:
    e = files[key]
    path = os.path.join(outdir, key)
    for attempt in range(20):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= e["size"]:
            break
        try:
            hdr = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(e["url"], headers=hdr, stream=True, timeout=120) as r:
                r.raise_for_status()
                mode = "ab" if (have and r.status_code == 206) else "wb"
                with open(path, mode) as f:
                    last = time.time()
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        if time.time() - last > 30:
                            print(key, os.path.getsize(path) / 1e6, "MB", flush=True)
                            last = time.time()
        except Exception as ex:
            print("retry", attempt, ex, flush=True)
            time.sleep(5)
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            md5.update(chunk)
    ok = "md5:" + md5.hexdigest() == e["checksum"]
    print(key, os.path.getsize(path), md5.hexdigest(), "OK" if ok else "CHECKSUM MISMATCH", flush=True)
