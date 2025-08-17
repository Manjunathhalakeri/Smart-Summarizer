#!/usr/bin/env python3
"""
robust scrapper.py

Purpose:
  - Fetch and extract clean text from up to 3 (or more) user-provided URLs
  - Handle HTML (static), optional JS-rendered pages (Playwright, if installed), and PDFs
  - Return a structured result ready for storage & later RAG (embeddings)
  - Optional CLI to save results to JSONL for quick inspection

Dependencies (install as needed):
  pip install httpx beautifulsoup4 trafilatura readability-lxml langdetect pdfminer.six
  # Optional for JS-heavy sites (render_js=True):
  pip install playwright && playwright install

Notes:
  - We keep this scraper self-contained. DB writes & embeddings happen in other modules.
  - We respect robots.txt if enabled (best-effort). Disable with --ignore-robots to force scraping.
  - We skip binary files that are not text or PDF.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
import urllib.robotparser as robotparser

import httpx
from bs4 import BeautifulSoup

# Optional dependencies
try:
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover
    trafilatura = None

try:
    from readability import Document  # type: ignore
except Exception:  # pragma: no cover
    Document = None  # type: ignore

try:
    from langdetect import detect  # type: ignore
except Exception:  # pragma: no cover
    detect = None  # type: ignore

try:
    from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
except Exception:  # pragma: no cover
    pdf_extract_text = None  # type: ignore

# Optional JS rendering via Playwright
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore

from db import insert_scraped_data, ensure_schema
from embed_chunk import embed_and_store_all


# ----------------------------- Config ---------------------------------
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 25.0  # seconds
MAX_REDIRECTS = 7
MAX_CONTENT_BYTES = 15 * 1024 * 1024  # 15 MB safety cap
RETRY_BACKOFF = [1.0, 2.0, 4.0]  # seconds

TEXT_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/plain",
)
PDF_CONTENT_TYPE = "application/pdf"

# ----------------------------- Data Models -----------------------------
@dataclasses.dataclass
class ScrapeResult:
    url: str
    final_url: Optional[str]
    status_code: Optional[int]
    content_type: Optional[str]
    title: Optional[str]
    text: Optional[str]
    html: Optional[str]
    language: Optional[str]
    links: List[str]
    fetched_at: str
    sha256: Optional[str]
    metadata: Dict[str, Any]
    error: Optional[str] = None


# ----------------------------- Utilities -------------------------------

def _log_setup(verbosity: int = 1) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def canonicalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    parsed = urlparse(url)
    # Add scheme if missing
    if not parsed.scheme:
        parsed = parsed._replace(scheme="https")
    # Remove fragments
    parsed = parsed._replace(fragment="")
    # Normalize netloc to lowercase
    parsed = parsed._replace(netloc=parsed.netloc.lower())
    return urlunparse(parsed)


def is_probably_pdf(url: str, headers: Optional[Dict[str, str]]) -> bool:
    if headers and "content-type" in {k.lower() for k in headers}:
        ct = headers.get("content-type") or headers.get("Content-Type")
        if ct and PDF_CONTENT_TYPE in ct:
            return True
    # Fallback by extension in URL
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


def parse_charset(headers: Dict[str, str]) -> Optional[str]:
    ct = headers.get("content-type") or headers.get("Content-Type")
    if not ct:
        return None
    m = re.search(r"charset=([\w\-]+)", ct, re.I)
    return m.group(1).strip() if m else None


def is_text_like(headers: Dict[str, str]) -> bool:
    ct = headers.get("content-type") or headers.get("Content-Type")
    if not ct:
        return True  # assume text if unknown
    return any(t in ct for t in TEXT_CONTENT_TYPES) or PDF_CONTENT_TYPE in ct


def robots_allowed(url: str, user_agent: str, timeout: float = 8.0) -> bool:
    """Best-effort robots.txt check. Returns True if allowed or robots is unreachable."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        allowed = rp.can_fetch(user_agent, url)
        return bool(True)
    except Exception:
        return True  # if robots can't be fetched, proceed


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# ----------------------------- Core Fetching ----------------------------

def _fetch_httpx(url: str, headers: Dict[str, str], timeout: float) -> Tuple[Optional[str], Optional[int], Dict[str, str], Optional[str]]:
    """Return (html_or_bytes_text, status_code, headers, final_url) for text-like content.
    If content exceeds MAX_CONTENT_BYTES, we cut it to the limit.
    """
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        status = r.status_code
        final_url = str(r.url)
        headers_lower = {k.lower(): v for k, v in r.headers.items()}

        if not is_text_like(r.headers):
            return None, status, headers_lower, final_url

        # Handle binary PDFs separately in caller by checking content-type
        content = r.content
        if len(content) > MAX_CONTENT_BYTES:
            content = content[:MAX_CONTENT_BYTES]
        # Attempt to decode as text (for HTML & text/plain). For PDFs, caller handles.
        try:
            encoding = r.encoding or "utf-8"
            text = content.decode(encoding, errors="replace")
        except Exception:
            text = content.decode("utf-8", errors="replace")
        return text, status, headers_lower, final_url


def _render_js_with_playwright(url: str, timeout: float = 20.0) -> str:
    if sync_playwright is None:
        raise RuntimeError("Playwright not installed. Install via 'pip install playwright' and run 'playwright install'.")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_navigation_timeout(timeout * 1000)
            page.goto(url, wait_until="networkidle")
            html = page.content()
            return html
        finally:
            browser.close()


# ----------------------------- Extraction ------------------------------

def extract_html_title(html: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        return None
    except Exception:
        return None


def extract_links(html: str, base_url: str) -> List[str]:
    urls: List[str] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href").strip()
            if not href:
                continue
            abs_url = urljoin(base_url, href)
            urls.append(abs_url)
    except Exception:
        pass
    # Deduplicate while preserving order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_text_from_html(html: str, base_url: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return (title, text). Tries trafilatura -> readability -> BS4 fallback."""
    # Try trafilatura
    if trafilatura is not None:
        try:
            text = trafilatura.extract(html, url=base_url, include_comments=False, favor_precision=True)
            if text and text.strip():
                # Trafilatura can also give title via metadata
                try:
                    downloaded = trafilatura.extractor.extract(html, with_metadata=True)
                    title = downloaded.get("title") if isinstance(downloaded, dict) else None
                except Exception:
                    title = extract_html_title(html)
                return (title, text.strip())
        except Exception:
            pass

    # Fallback: readability
    if Document is not None:
        try:
            doc = Document(html)
            title = doc.short_title() if hasattr(doc, "short_title") else None
            summary_html = doc.summary()
            soup = BeautifulSoup(summary_html, "html.parser")
            text = soup.get_text("\n", strip=True)
            if text and text.strip():
                return (title, text.strip())
        except Exception:
            pass

    # Final fallback: simple text from BS4
    try:
        soup = BeautifulSoup(html, "html.parser")
        title = extract_html_title(html)
        # Remove scripts/styles/nav/footer for less noise
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        return (title, text.strip() if text else None)
    except Exception:
        return (None, None)


def extract_text_from_pdf_bytes(url: str) -> Optional[str]:
    if pdf_extract_text is None:
        raise RuntimeError("pdfminer.six not installed. Install via 'pip install pdfminer.six'.")
    try:
        # pdfminer works with file paths; fetch bytes first then write temp file
        with httpx.Client(headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            content = r.content
            if len(content) > MAX_CONTENT_BYTES:
                content = content[:MAX_CONTENT_BYTES]
        # Write to temp and extract
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            text = pdf_extract_text(tmp_path)
            return text.strip() if text else None
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logging.exception("PDF extraction failed: %s", e)
        return None


def detect_language(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    if detect is None:
        return None
    try:
        return detect(text)
    except Exception:
        return None


# ----------------------------- Public API ------------------------------

def scrape_one(
    url: str,
    *,
    render_js: bool = False,
    ignore_robots: bool = False,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = REQUEST_TIMEOUT,
    verbosity: int = 1,
) -> ScrapeResult:
    """Scrape a single URL into a ScrapeResult.

    This function is synchronous and resilient (retries + fallbacks).
    """
    _ = verbosity  # reserved for future per-call logging
    h = {**DEFAULT_HEADERS, **(headers or {})}

    start_dt = datetime.now(timezone.utc).isoformat()
    url = canonicalize_url(url)

    if not ignore_robots:
        allowed = robots_allowed(url, h["User-Agent"])
        if not allowed:
            return ScrapeResult(
                url=url,
                final_url=None,
                status_code=None,
                content_type=None,
                title=None,
                text=None,
                html=None,
                language=None,
                links=[],
                fetched_at=start_dt,
                sha256=None,
                metadata={"robots_allowed": False},
                error="Blocked by robots.txt",
            )

    # Fetch with retries
    last_error: Optional[str] = None
    html_text: Optional[str] = None
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    response_headers: Dict[str, str] = {}

    try:
        for backoff in [0.0] + RETRY_BACKOFF:
            if backoff:
                time.sleep(backoff)
            try:
                # JS render path
                if render_js:
                    html_text = _render_js_with_playwright(url, timeout=timeout)
                    status_code = 200
                    final_url = url
                    response_headers = {"content-type": "text/html"}
                else:
                    html_text, status_code, response_headers, final_url = _fetch_httpx(url, h, timeout)
                break
            except Exception as e:
                last_error = str(e)
                logging.warning("Fetch attempt failed (%s). Retrying...", last_error)
        else:
            raise RuntimeError(last_error or "Failed to fetch URL")
    except Exception as e:
        return ScrapeResult(
            url=url,
            final_url=final_url,
            status_code=status_code,
            content_type=response_headers.get("content-type"),
            title=None,
            text=None,
            html=None,
            language=None,
            links=[],
            fetched_at=start_dt,
            sha256=None,
            metadata={"render_js": render_js},
            error=f"Fetch error: {e}",
        )

    # Determine content type & branch for PDF
    content_type = response_headers.get("content-type")
    title: Optional[str] = None
    text: Optional[str] = None
    html_out: Optional[str] = None
    links: List[str] = []

    try:
        if is_probably_pdf(final_url or url, response_headers):
            text = extract_text_from_pdf_bytes(final_url or url)
            title = None
            html_out = None
        else:
            html = html_text or ""
            html_out = html
            title, text = extract_text_from_html(html, base_url=final_url or url)
            links = extract_links(html, final_url or url) if html else []
    except Exception as e:
        return ScrapeResult(
            url=url,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            title=None,
            text=None,
            html=None,
            language=None,
            links=[],
            fetched_at=start_dt,
            sha256=None,
            metadata={"render_js": render_js},
            error=f"Extraction error: {e}",
        )

    language = detect_language(text)
    digest = sha256_text(text) if text else None

    return ScrapeResult(
        url=url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        title=title,
        text=text,
        html=html_out,
        language=language,
        links=links,
        fetched_at=start_dt,
        sha256=digest,
        metadata={
            "render_js": render_js,
            "charset": parse_charset(response_headers) if response_headers else None,
            "headers": response_headers,
            "robots_allowed": True if ignore_robots else robots_allowed(url, h["User-Agent"]),
        },
        error=None,
    )


def scrape_urls(
    urls: Iterable[str],
    *,
    render_js: bool = False,
    ignore_robots: bool = False,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = REQUEST_TIMEOUT,
    rate_limit_s: float = 0.0,
    verbosity: int = 1,
) -> List[ScrapeResult]:
    results: List[ScrapeResult] = []
    for i, raw in enumerate(urls, start=1):
        url = canonicalize_url(raw)
        logging.info("[%d/%d] Scraping %s", i, len(list(urls)) if hasattr(urls, '__len__') else i, url)
        res = scrape_one(
            url,
            render_js=render_js,
            ignore_robots=ignore_robots,
            headers=headers,
            timeout=timeout,
            verbosity=verbosity,
        )
        results.append(res)
        if rate_limit_s > 0 and i < (len(list(urls)) if hasattr(urls, '__len__') else i):
            time.sleep(rate_limit_s)
    return results


# ----------------------------- CLI -------------------------------------

def _load_urls_from_file(path: str) -> List[str]:
    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def _save_jsonl(path: str, results: List[ScrapeResult]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(dataclasses.asdict(r), ensure_ascii=False) + "\n")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape URLs into structured JSON for RAG.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--urls", nargs="*", help="List of URLs to scrape")
    src.add_argument("--file", help="Path to a text file with one URL per line")

    parser.add_argument("--out", help="Write JSONL results to this path")
    parser.add_argument("--render-js", action="store_true", help="Render pages with Playwright (optional)")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt (use responsibly)")
    parser.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--rate-limit", type=float, default=0.0, help="Seconds to sleep between requests")
    parser.add_argument("-v", "--verbose", action="count", default=1, help="Increase logs (-v, -vv)")

    args = parser.parse_args(argv)

    _log_setup(args.verbose)

    urls: List[str]
    if args.file:
        urls = _load_urls_from_file(args.file)
    else:
        urls = list(args.urls or [])

    if not urls:
        parser.error("No URLs provided.")

    # Ensure DB schema exists before inserting
    try:
        ensure_schema()
    except Exception as e:
        logging.warning("ensure_schema failed (continuing): %s", e)

    results = scrape_urls(
        urls,
        render_js=args.render_js,
        ignore_robots=args.ignore_robots,
        timeout=args.timeout,
        rate_limit_s=args.rate_limit,
        verbosity=args.verbose,
    )

    # Prepare data for DB insertion (only valid, non-empty text)
    # Optionally allow passing user via env or future arg; keep default user otherwise
    import os
    user_key = os.getenv("APP_USER_KEY")

    db_data = [
        {"url": r.url, "title": r.title, "content": r.text.strip() if r.text else ""}
        for r in results
        if r.url and r.text and r.text.strip() and not r.error
    ]
    if db_data:
        insert_scraped_data(db_data, user_key=user_key)
        # Automatically generate and store embeddings after scraping
        embed_and_store_all()
    else:
        logging.info("No valid data to insert into the database.")

    if args.out:
        _save_jsonl(args.out, results)
        logging.info("Saved %d results to %s", len(results), args.out)
    else:
        # Print compact JSON to stdout
        print(json.dumps([dataclasses.asdict(r) for r in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
