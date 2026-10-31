"""Find a freely licensed background track on Wikimedia Commons (no key needed).

Only CC0, public-domain and CC BY tracks are accepted. CC BY-SA and NC licences are skipped because putting music
under a video can count as an adaptation. CC BY requires credit, so the credit line is returned for the caption.
"""
import hashlib, html, json, re, sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "music"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "ReelPipeline/0.3 (https://github.com/Kedar7412/claude-video-pro)"}
AUDIO_EXT = (".mp3", ".ogg", ".oga", ".opus", ".flac", ".wav")


def log(msg): print(msg, file=sys.stderr, flush=True)


def license_ok(lic: str) -> bool:
    l = lic.lower().replace("-", " ")
    if "nc" in l.split() or "sa" in l.split() or "nd" in l.split():
        return False
    return l.startswith("cc0") or "public domain" in l or l.startswith("pd") or re.match(r"^cc by( \d(\.\d)?)?$", l) is not None


def _ext(url): return Path(urlparse(url).path).suffix.lower()


def _clean(v): return html.unescape(re.sub(r"<[^>]+>", "", v or "")).strip()


def _artist(v):
    v = re.split(r"\.\s|\s(?:Released|Licensed)\b", v)[0]
    v = re.sub(r"^(Created|Composed|Music) by\s+", "", v, flags=re.I).strip(" .")
    return v[:60]


def search(query, limit=25):
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"search_{hashlib.sha1(query.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = requests.get(API, headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:audio {query}", "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName|LicenseUrl"})
    r.raise_for_status()
    out = []
    for p in sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        m = ii.get("extmetadata", {})
        out.append({"title": p["title"][5:], "url": ii.get("url", ""), "page": ii.get("descriptionurl", ""),
                    "size": ii.get("size", 0), "license": _clean(m.get("LicenseShortName", {}).get("value")),
                    "artist": _artist(_clean(m.get("Artist", {}).get("value")))})
    f.write_text(json.dumps(out))
    return out


def find_track(query, pick=1, max_mb=25):
    """Download the pick-th acceptable track for the query. Returns (path, credit) or (None, reason)."""
    import requests
    q, _, n = query.partition("#")
    pick = int(n) if n.strip().isdigit() else pick
    ok = [c for c in search(q.strip()) if license_ok(c["license"]) and _ext(c["url"]) in AUDIO_EXT
          and 300_000 < c["size"] < max_mb * 1_000_000]
    if not ok:
        return None, f"no CC0 / CC BY track found for '{q.strip()}'"
    c = ok[min(pick, len(ok)) - 1]
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / (hashlib.sha1(urlparse(c["url"]).path.encode()).hexdigest()[:16] + _ext(c["url"]))
    if not dst.exists():
        log(f"    downloading music '{c['title']}' ({c['license']})")
        r = requests.get(c["url"], headers=UA, timeout=180)
        r.raise_for_status()
        dst.write_bytes(r.content)
    name = re.sub(r"\.(mp3|ogg|oga|opus|flac|wav)$", "", c["title"], flags=re.I)
    credit = f"Music: {name} by {c['artist'] or 'unknown'} ({c['license']}), via Wikimedia Commons {c['page']}"
    return dst, credit
