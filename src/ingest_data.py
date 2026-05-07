from __future__ import annotations
"""
ingest_data.py — Data Ingestion Layer

Collects raw data from:
  - Web pages (Wikipedia, recipe sites, food blogs)
  - PDFs (academic papers, recipe books)
  - Images

All output is saved as raw text + metadata in data/raw/<country>/<bread>/
Images are downloaded to data/images/<country>/<bread>/
"""

import re
import json
import time
import hashlib
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, urljoin, quote_plus

import httpx
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

from config import (
    RAW_DIR, IMAGES_DIR, USER_AGENT, REQUEST_TIMEOUT,
    MAX_SOURCES_PER_BREAD, SCRAPE_SOURCES,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class RawSource:
    url: str
    title: str
    body_text: str
    images: list[str] = field(default_factory=list)   # local paths
    source_type: str = "web"  # web | pdf | api
    fetched_at: str = ""

    def to_markdown(self) -> str:
        imgs = "\n".join(f"![image]({p})" for p in self.images)
        return (
            f"# {self.title}\n\n"
            f"**Source:** {self.url}  \n"
            f"**Fetched:** {self.fetched_at}\n\n"
            f"{self.body_text}\n\n"
            f"{imgs}\n"
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]


def _save_raw(country: str, bread: str, source: RawSource) -> Path:
    out_dir = RAW_DIR / _slug(country) / _slug(bread)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_url_hash(source.url)}_{_slug(source.title)[:40]}.json"
    path = out_dir / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(source), f, ensure_ascii=False, indent=2)
    log.info(f"  saved raw → {path.relative_to(RAW_DIR.parent)}")
    return path


def _download_image(url: str, country: str, bread: str) -> str | None:
    """Download an image and return its local path (relative to project root)."""
    img_dir = IMAGES_DIR / _slug(country) / _slug(bread)
    img_dir.mkdir(parents=True, exist_ok=True)
    fname = _url_hash(url) + Path(urlparse(url).path).suffix or ".jpg"
    local = img_dir / fname
    if local.exists():
        return str(local)
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        img.save(local)
        return str(local)
    except Exception as e:
        log.warning(f"  image download failed {url}: {e}")
        return None


# ── Wikipedia ingestion ────────────────────────────────────────────────────────

def ingest_wikipedia(bread: str, country: str) -> RawSource | None:
    query = quote_plus(f"{bread} bread")
    url = f"https://en.wikipedia.org/wiki/{quote_plus(bread.replace(' ', '_'))}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            # fallback to search
            search_url = (
                f"https://en.wikipedia.org/w/api.php?action=query"
                f"&list=search&srsearch={query}+bread&format=json&srlimit=1"
            )
            sr = requests.get(search_url, headers=HEADERS, timeout=REQUEST_TIMEOUT).json()
            hits = sr.get("query", {}).get("search", [])
            if not hits:
                return None
            title = hits[0]["title"]
            url = f"https://en.wikipedia.org/wiki/{quote_plus(title)}"
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

        soup = BeautifulSoup(r.text, "lxml")

        # Extract main content paragraphs
        content_div = soup.find("div", id="mw-content-text")
        paragraphs = []
        if content_div:
            for p in content_div.find_all("p", limit=20):
                txt = p.get_text(" ", strip=True)
                if len(txt) > 60:
                    paragraphs.append(txt)

        body = "\n\n".join(paragraphs)

        # Extract images
        img_urls = []
        for img in (content_div or soup).find_all("img", limit=5):
            src = img.get("src", "")
            if src.startswith("//"):
                src = "https:" + src
            if any(ext in src for ext in (".jpg", ".jpeg", ".png", ".webp")):
                local = _download_image(src, country, bread)
                if local:
                    img_urls.append(local)

        page_title = soup.find("h1", id="firstHeading")
        title = page_title.get_text() if page_title else bread

        return RawSource(
            url=url,
            title=title,
            body_text=body,
            images=img_urls,
            source_type="web",
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    except Exception as e:
        log.warning(f"  Wikipedia fetch failed for '{bread}': {e}")
        return None


# ── Generic web page ingestion ─────────────────────────────────────────────────

def ingest_web_page(url: str, country: str, bread: str) -> RawSource | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Remove nav / footer / ads
        for tag in soup(["nav", "footer", "script", "style", "aside", "header"]):
            tag.decompose()

        # Prefer article / main content
        main = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile(r"content|post|article|recipe", re.I))
            or soup.body
        )

        paragraphs = []
        if main:
            for p in main.find_all(["p", "li"], limit=40):
                txt = p.get_text(" ", strip=True)
                if len(txt) > 50:
                    paragraphs.append(txt)

        body = "\n\n".join(paragraphs)
        title_tag = soup.find("title") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else url

        return RawSource(
            url=url,
            title=title[:120],
            body_text=body[:8000],
            source_type="web",
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    except Exception as e:
        log.warning(f"  web fetch failed {url}: {e}")
        return None


# ── PDF ingestion ──────────────────────────────────────────────────────────────

def ingest_pdf(pdf_path: str | Path, country: str, bread: str) -> RawSource | None:
    if not HAS_PYMUPDF:
        log.warning("PyMuPDF not installed; skipping PDF ingestion")
        return None
    path = Path(pdf_path)
    try:
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        body = "\n\n".join(pages)[:12000]
        return RawSource(
            url=f"file://{path.resolve()}",
            title=path.stem.replace("_", " ").title(),
            body_text=body,
            source_type="pdf",
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    except Exception as e:
        log.warning(f"  PDF parse failed {path}: {e}")
        return None


# ── Master ingestion function ──────────────────────────────────────────────────

def ingest_bread(bread: str, country: str) -> list[Path]:
    """
    Collect all available data for a given bread from a given country.
    Returns list of saved raw JSON file paths.
    """
    log.info(f"Ingesting: {country} / {bread}")
    saved: list[Path] = []

    # 1. Wikipedia
    wiki = ingest_wikipedia(bread, country)
    if wiki:
        saved.append(_save_raw(country, bread, wiki))
        time.sleep(0.5)  # polite delay

    # 2. Additional web sources (up to MAX_SOURCES_PER_BREAD - 1)
    extra_queries = [
        f"https://www.thespruceeats.com/search?q={quote_plus(bread+' bread')}",
        f"https://www.allrecipes.com/search?q={quote_plus(bread)}",
    ]
    for src_url in extra_queries[: MAX_SOURCES_PER_BREAD - 1]:
        page = ingest_web_page(src_url, country, bread)
        if page and len(page.body_text) > 200:
            saved.append(_save_raw(country, bread, page))
        time.sleep(0.8)

    log.info(f"  → {len(saved)} raw sources saved for {bread}")
    return saved


def ingest_catalog(catalog: dict[str, list[str]]) -> None:
    """Run ingestion for every bread in the seed catalog."""
    for country, breads in catalog.items():
        for bread in breads:
            ingest_bread(bread, country)
            time.sleep(1)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from config import SEED_CATALOG

    if len(sys.argv) == 3:
        # python ingest_data.py "Italy" "ciabatta"
        ingest_bread(sys.argv[2], sys.argv[1])
    else:
        print("Running full catalog ingestion …")
        ingest_catalog(SEED_CATALOG)
        print("Done.")
