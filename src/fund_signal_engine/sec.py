"""Polite access to SEC public data: identified User-Agent, rate limiting, and
range-read extraction of single tables from multi-GB bulk zips."""

import io
import os
import re
import time
import urllib.request
import zipfile
from pathlib import Path

SEC = "https://www.sec.gov"
_MIN_INTERVAL = 0.15  # SEC fair-access limit is 10 req/s; stay well under it
_last_request = 0.0


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def user_agent() -> str:
    _load_dotenv()
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise SystemExit(
            "Set SEC_USER_AGENT in .env, e.g. SEC_USER_AGENT=\"Jane Doe jane@example.com\" "
            "(SEC requires automated clients to identify themselves)."
        )
    return ua


def request(url: str, method: str = "GET", headers: dict | None = None) -> bytes | dict:
    global _last_request
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, method=method, headers={"User-Agent": user_agent(), **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                _last_request = time.monotonic()
                return dict(resp.headers) if method == "HEAD" else resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def links(page_url: str, pattern: str) -> list[str]:
    """Absolute URLs of hrefs on an SEC page matching `pattern`, in page order."""
    html = request(page_url).decode("utf-8", "replace")
    out = []
    for href in re.findall(r'href="([^"]+)"', html):
        if re.search(pattern, href):
            out.append(href if href.startswith("http") else SEC + href)
    return list(dict.fromkeys(out))


class _RangeFile(io.RawIOBase):
    """Seekable file over HTTP Range requests, so zipfile can read one member
    of a remote archive without downloading the whole thing."""

    def __init__(self, url: str):
        self.url, self.pos = url, 0
        self.size = int(request(url, method="HEAD")["Content-Length"])

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buf):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(buf), self.size) - 1
        data = request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        buf[: len(data)] = data
        self.pos += len(data)
        return len(data)


def extract_remote(url: str, prefixes: list[str], dest: Path) -> list[Path]:
    """Extract zip members whose basename starts with any prefix, transcoding
    latin-1 CSVs to UTF-8. Skips members already on disk."""
    dest.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BufferedReader(_RangeFile(url), buffer_size=8 << 20))
    written = []
    for info in archive.infolist():
        name = Path(info.filename).name
        if not name or not any(name.startswith(p) for p in prefixes):
            continue
        target = dest / name
        if not target.exists():
            print(f"  extracting {name} ({info.compress_size / 1e6:.0f} MB compressed)", flush=True)
            tmp = target.with_suffix(".part")
            with archive.open(info) as src, open(tmp, "w", encoding="utf-8", newline="") as out:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    out.write(chunk.decode("latin-1"))
            tmp.rename(target)
        written.append(target)
    return written


def download(url: str, target: Path) -> Path:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {target.name}", flush=True)
        target.write_bytes(request(url))
    return target
