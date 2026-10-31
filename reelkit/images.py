"""Still images from Wikimedia Commons for documentary-style cutaways (no key needed).

Only CC0, public-domain and CC BY images are used (BY-SA and NC are skipped), and every image's credit is returned
so it can go into the video description."""
import hashlib, json, sys
from pathlib import Path
from urllib.parse import urlparse

from .musicsearch import UA, _artist, _clean, license_ok

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "images"
API = "https://commons.wikimedia.org/w/api.php"
OK_MIME = ("image/jpeg", "image/png")


def log(msg): print(msg, file=sys.stderr, flush=True)


def search(query, width=1920, limit=25):
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"search_{hashlib.sha1(f'{query}|{width}'.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = requests.get(API, headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": limit, "prop": "imageinfo", "iiurlwidth": width,
        "iiprop": "url|size|mime|extmetadata", "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName"})
    r.raise_for_status()
    out = []
    for p in sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        m = ii.get("extmetadata", {})
        out.append({"title": p["title"][5:], "url": ii.get("thumburl") or ii.get("url", ""), "page": ii.get("descriptionurl", ""),
                    "w": ii.get("width", 0), "h": ii.get("height", 0), "mime": ii.get("mime", ""),
                    "license": _clean(m.get("LicenseShortName", {}).get("value")),
                    "artist": _artist(_clean(m.get("Artist", {}).get("value")))})
    f.write_text(json.dumps(out))
    return out


def find_image(query, used=(), width=1920):
    """(path, credit) for the first acceptable unused image, or (None, reason)."""
    import requests
    q, _, n = query.partition("#")
    pick = int(n) if n.strip().isdigit() else 1
    ok = [c for c in search(q.strip(), width) if license_ok(c["license"]) and c["mime"] in OK_MIME
          and c["w"] >= 1000 and c["url"] and c["url"] not in used]
    if not ok:
        return None, f"no CC0 / CC BY image found for '{q.strip()}'", ""
    c = ok[min(pick, len(ok)) - 1]
    CACHE.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(c["url"]).path).suffix.lower() or ".jpg"
    dst = CACHE / (hashlib.sha1(urlparse(c["url"]).path.encode()).hexdigest()[:16] + ext)
    if not dst.exists():
        log(f"    downloading image '{c['title'][:50]}' ({c['license']})")
        r = requests.get(c["url"], headers=UA, timeout=60)
        r.raise_for_status()
        dst.write_bytes(r.content)
    name = c["title"].rsplit(".", 1)[0]
    return dst, f"Image: {name} by {c['artist'] or 'unknown'} ({c['license']}), via Wikimedia Commons {c['page']}", c["url"]
