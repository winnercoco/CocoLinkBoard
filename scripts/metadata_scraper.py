import asyncio
import json
import re
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import yt_dlp


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LINKS_PATH = DATA_DIR / "links.json"
METADATA_PATH = DATA_DIR / "metadata.json"
STREAM_CACHE_PATH = DATA_DIR / "stream_cache.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

DIRECT_VIDEO_EXTS = (".mp4", ".m3u8", ".webm", ".mkv", ".mov", ".mpd", ".m4v")
HLS_MIME = "application/vnd.apple.mpegurl"
DASH_MIME = "application/dash+xml"

# Short TTL because many sites use signed URLs
DEFAULT_STREAM_TTL_MINUTES = 20


# -------------------------
# JSON helpers
# -------------------------
def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data: Any):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# -------------------------
# HTTP session
# -------------------------
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# -------------------------
# Data structures
# -------------------------
@dataclass
class Playback:
    kind: str = "page"          # direct | embed | page | none
    mime: Optional[str] = None
    embed_url: Optional[str] = None
    page_url: Optional[str] = None
    extractor: Optional[str] = None


@dataclass
class MetadataRecord:
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    playback: Optional[dict] = None
    playback_mode: str = "none"
    last_scraped: Optional[str] = None
    domain: Optional[str] = None
    status: str = "ok"
    note: Optional[str] = None


@dataclass
class StreamRecord:
    stream_url: Optional[str] = None
    mime: Optional[str] = None
    expires_at: Optional[str] = None
    last_refreshed: Optional[str] = None
    status: str = "ok"
    note: Optional[str] = None


# -------------------------
# URL / time helpers
# -------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(base_url: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if value.startswith("blob:"):
        value = value[5:]
    return urljoin(base_url, value)


def infer_mime_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    lower = url.lower()
    if ".m3u8" in lower:
        return HLS_MIME
    if ".mpd" in lower:
        return DASH_MIME
    if any(ext in lower for ext in (".mp4", ".m4v")):
        return "video/mp4"
    if ".webm" in lower:
        return "video/webm"
    if ".mov" in lower:
        return "video/quicktime"
    if ".mkv" in lower:
        return "video/x-matroska"
    return None


def looks_like_direct_media(url: Optional[str]) -> bool:
    if not url:
        return False
    lower = url.lower()
    return any(ext in lower for ext in DIRECT_VIDEO_EXTS)


def parse_expiry_from_url(url: Optional[str]) -> Optional[datetime]:
    """
    Best-effort parser for signed URLs.
    Handles common query params like expire, expires, exp, e.
    """
    if not url:
        return None

    try:
        qs = parse_qs(urlparse(url).query)
        for key in ("expire", "expires", "exp", "e", "token_expires"):
            if key in qs and qs[key]:
                raw = qs[key][0]
                if raw.isdigit():
                    value = int(raw)
                    # seconds since epoch
                    if value > 10_000_000_000:
                        # probably milliseconds
                        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                    return datetime.fromtimestamp(value, tz=timezone.utc)
    except Exception:
        pass

    return None


def default_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_STREAM_TTL_MINUTES)


def is_stream_cache_fresh(record: dict) -> bool:
    expires_at = record.get("expires_at")
    stream_url = record.get("stream_url")
    if not stream_url or not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
        # refresh a bit early
        return datetime.now(timezone.utc) < (expiry - timedelta(minutes=2))
    except Exception:
        return False


# -------------------------
# HTML parsing
# -------------------------
M3U8_REGEX = re.compile(r'https?://[^"\']+\.m3u8[^"\']*', re.IGNORECASE)
DIRECT_MEDIA_REGEX = re.compile(
    r'https?://[^"\']+\.(?:mp4|m3u8|webm|mkv|mov|mpd)[^"\']*',
    re.IGNORECASE
)


def first_text(*values: Optional[str]) -> Optional[str]:
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return None


def parse_json_ld(soup: BeautifulSoup) -> dict:
    out = {"title": None, "thumbnail": None, "video_url": None}
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            out["title"] = out["title"] or item.get("name")
            thumb = item.get("thumbnailUrl")
            if isinstance(thumb, list):
                thumb = thumb[0] if thumb else None
            out["thumbnail"] = out["thumbnail"] or thumb
            out["video_url"] = out["video_url"] or item.get("contentUrl")
    return out


def parse_html_metadata(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    ld = parse_json_ld(soup)

    title = first_text(
        ld.get("title"),
        (soup.find("meta", property="og:title") or {}).get("content"),
        (soup.find("meta", attrs={"name": "twitter:title"}) or {}).get("content"),
        soup.title.string.strip() if soup.title and soup.title.string else None,
    )

    thumbnail = first_text(
        ld.get("thumbnail"),
        (soup.find("meta", property="og:image") or {}).get("content"),
        (soup.find("meta", attrs={"name": "twitter:image"}) or {}).get("content"),
        soup.find("video").get("poster") if soup.find("video") and soup.find("video").get("poster") else None,
    )

    video_url = first_text(
        ld.get("video_url"),
        (soup.find("meta", property="og:video") or {}).get("content"),
        (soup.find("meta", property="og:video:url") or {}).get("content"),
        (soup.find("meta", attrs={"name": "twitter:player:stream"}) or {}).get("content"),
    )

    if not video_url:
        m = M3U8_REGEX.search(html) or DIRECT_MEDIA_REGEX.search(html)
        if m:
            video_url = m.group(0)

    if not video_url:
        video_tag = soup.find("video")
        if video_tag:
            if video_tag.get("src"):
                video_url = video_tag.get("src")
            else:
                for source in video_tag.find_all("source"):
                    src = source.get("src")
                    if src and looks_like_direct_media(src):
                        video_url = src
                        break

    embed_url = None
    for iframe in soup.find_all("iframe", src=True):
        src = iframe.get("src")
        if src and any(token in src.lower() for token in ("embed", "player", "video", "stream", "jwplayer", "iframe")):
            embed_url = src
            break

    video_url = normalize_url(base_url, video_url)
    thumbnail = normalize_url(base_url, thumbnail)
    embed_url = normalize_url(base_url, embed_url)

    return {
        "title": title,
        "thumbnail": thumbnail,
        "video_url": video_url,
        "embed_url": embed_url,
    }


# -------------------------
# yt-dlp extraction
# -------------------------
def extract_with_ytdlp(page_url: str, cookie_file: Optional[str] = None) -> dict:
    """
    Use yt-dlp first because it already knows many sites.
    We do NOT treat the returned stream URL as durable.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "impersonate": "chrome",
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "retries": 2,
        "http_headers": HEADERS,
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(page_url, download=False)

    formats = info.get("formats") or []
    best_direct = None

    # Prefer HLS/DASH/MP4 in this order for browser playback
    scored = []
    for fmt in formats:
        url = fmt.get("url")
        if not url:
            continue
        ext = (fmt.get("ext") or "").lower()
        protocol = (fmt.get("protocol") or "").lower()
        acodec = fmt.get("acodec")
        vcodec = fmt.get("vcodec")

        mime = infer_mime_from_url(url)
        if not mime:
            # fallback inference from extractor fields
            if protocol in ("m3u8_native", "m3u8"):
                mime = HLS_MIME
            elif protocol == "http_dash_segments" or ext == "mpd":
                mime = DASH_MIME
            elif ext == "mp4":
                mime = "video/mp4"

        if not mime:
            continue

        # De-prioritize audio-only
        is_video_like = vcodec not in (None, "none")
        score = 0
        if mime == HLS_MIME:
            score += 300
        elif mime == "video/mp4":
            score += 200
        elif mime == DASH_MIME:
            score += 150
        else:
            score += 100

        if is_video_like:
            score += 50
        if acodec not in (None, "none"):
            score += 10
        height = fmt.get("height") or 0
        score += min(height, 2160)

        scored.append((score, url, mime))

    if scored:
        scored.sort(reverse=True, key=lambda x: x[0])
        _, best_url, best_mime = scored[0]
        best_direct = {"stream_url": best_url, "mime": best_mime}

    thumb = None
    thumbs = info.get("thumbnails") or []
    if thumbs:
        thumb = thumbs[-1].get("url")
    thumb = thumb or info.get("thumbnail")

    embed_url = info.get("playable_in_embed") and page_url or None

    return {
        "title": info.get("title"),
        "thumbnail": thumb,
        "stream": best_direct,
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or page_url,
        "embed_url": embed_url,
    }


# -------------------------
# Playwright fallback
# -------------------------
async def playwright_capture(page_url: str) -> dict:
    """
    Render page and sniff direct media / embeds from the final DOM and network.
    """
    captured = {
        "html": None,
        "direct_media": [],
        "embed_urls": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            service_workers="block",
        )

        # Abort only heavy static assets; keep XHR/fetch/media visible
        await context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ["image", "font", "stylesheet"]
            else route.continue_()
        )

        page = await context.new_page()

        async def on_response(response):
            try:
                rurl = response.url
                headers = await response.all_headers()
                ctype = (headers.get("content-type") or "").lower()

                if "mpegurl" in ctype or "video/" in ctype or looks_like_direct_media(rurl):
                    captured["direct_media"].append({
                        "url": rurl,
                        "mime": ctype or infer_mime_from_url(rurl),
                    })
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            captured["html"] = await page.content()

            # DOM-level fallbacks
            embed_urls = await page.eval_on_selector_all(
                "iframe[src]",
                """els => els.map(e => e.src).filter(Boolean)"""
            )
            captured["embed_urls"].extend(embed_urls or [])

            video_urls = await page.eval_on_selector_all(
                "video, source",
                """
                els => els
                    .map(e => e.src || e.getAttribute('src'))
                    .filter(Boolean)
                """
            )
            for v in video_urls or []:
                captured["direct_media"].append({
                    "url": v,
                    "mime": infer_mime_from_url(v),
                })

        finally:
            await context.close()
            await browser.close()

    return captured


# -------------------------
# Merge / classify
# -------------------------
def classify_playback(page_url: str, html_meta: dict, ytdlp_meta: Optional[dict], pw_meta: Optional[dict]) -> tuple[MetadataRecord, Optional[StreamRecord]]:
    title = html_meta.get("title")
    thumbnail = html_meta.get("thumbnail")
    html_video = html_meta.get("video_url")
    html_embed = html_meta.get("embed_url")

    extractor = None
    stream_record = None
    playback = Playback(kind="page", page_url=page_url)

    if ytdlp_meta:
        title = ytdlp_meta.get("title") or title
        thumbnail = ytdlp_meta.get("thumbnail") or thumbnail
        extractor = ytdlp_meta.get("extractor")
        if ytdlp_meta.get("stream"):
            stream_url = ytdlp_meta["stream"]["stream_url"]
            stream_mime = ytdlp_meta["stream"]["mime"] or infer_mime_from_url(stream_url)
            playback = Playback(
                kind="direct",
                mime=stream_mime,
                page_url=page_url,
                extractor=extractor,
            )
            expiry = parse_expiry_from_url(stream_url) or default_expiry()
            stream_record = StreamRecord(
                stream_url=stream_url,
                mime=stream_mime,
                expires_at=expiry.isoformat(),
                last_refreshed=utc_now_iso(),
                status="ok",
            )

        elif ytdlp_meta.get("embed_url"):
            playback = Playback(
                kind="embed",
                mime="text/html",
                embed_url=ytdlp_meta["embed_url"],
                page_url=page_url,
                extractor=extractor,
            )

    # If yt-dlp did not give us a direct stream, try HTML-level direct media
    if playback.kind == "page" and html_video:
        mime = infer_mime_from_url(html_video)
        if mime:
            playback = Playback(
                kind="direct",
                mime=mime,
                page_url=page_url,
                extractor=extractor,
            )
            expiry = parse_expiry_from_url(html_video) or default_expiry()
            stream_record = StreamRecord(
                stream_url=html_video,
                mime=mime,
                expires_at=expiry.isoformat(),
                last_refreshed=utc_now_iso(),
                status="ok",
            )

    # Embed fallback from static HTML
    if playback.kind == "page" and html_embed:
        playback = Playback(
            kind="embed",
            mime="text/html",
            embed_url=html_embed,
            page_url=page_url,
            extractor=extractor,
        )

    # Playwright fallback
    if pw_meta and playback.kind == "page":
        for item in pw_meta.get("direct_media", []):
            u = item.get("url")
            mime = item.get("mime") or infer_mime_from_url(u)
            if u and mime:
                playback = Playback(
                    kind="direct",
                    mime=mime,
                    page_url=page_url,
                    extractor=extractor or "playwright",
                )
                expiry = parse_expiry_from_url(u) or default_expiry()
                stream_record = StreamRecord(
                    stream_url=u,
                    mime=mime,
                    expires_at=expiry.isoformat(),
                    last_refreshed=utc_now_iso(),
                    status="ok",
                )
                break

        if playback.kind == "page":
            embeds = pw_meta.get("embed_urls") or []
            if embeds:
                playback = Playback(
                    kind="embed",
                    mime="text/html",
                    embed_url=embeds[0],
                    page_url=page_url,
                    extractor=extractor or "playwright",
                )

    if playback.kind == "embed":
        playback_mode = "embed"
    elif playback.kind == "direct":
        playback_mode = "direct_proxy"
    elif playback.kind == "page":
        playback_mode = "source_page"
    else:
        playback_mode = "none"

    meta = MetadataRecord(
        title=title,
        thumbnail=thumbnail,
        playback=asdict(playback),
        playback_mode=playback_mode,
        last_scraped=utc_now_iso(),
        domain=urlparse(page_url).netloc,
        status="ok" if (title or thumbnail or playback.kind != "page") else "partial",
        note=None if (title or thumbnail or playback.kind != "page") else "No direct media or embed found",
    )

    return meta, stream_record


# -------------------------
# Static fetch
# -------------------------
def fetch_html(page_url: str) -> Optional[str]:
    try:
        resp = SESSION.get(page_url, timeout=20, allow_redirects=True)
        if resp.ok and resp.text and len(resp.text) > 500:
            return resp.text
    except Exception:
        return None
    return None


# -------------------------
# Main scrape for one URL
# -------------------------
async def scrape_one(page_url: str, cookie_file: Optional[str], use_playwright_fallback: bool = True) -> tuple[MetadataRecord, Optional[StreamRecord]]:
    html = fetch_html(page_url)
    html_meta = parse_html_metadata(html, page_url) if html else {
        "title": None,
        "thumbnail": None,
        "video_url": None,
        "embed_url": None,
    }

    ytdlp_meta = None
    try:
        ytdlp_meta = await asyncio.to_thread(extract_with_ytdlp, page_url, cookie_file)
    except Exception as e:
        ytdlp_meta = {
            "title": None,
            "thumbnail": None,
            "stream": None,
            "extractor": None,
            "webpage_url": page_url,
            "embed_url": None,
            "error": str(e),
        }

    pw_meta = None
    need_playwright = False

    # Escalate when we still have no playback path
    if (
        not ytdlp_meta
        or (
            not (ytdlp_meta.get("stream") or ytdlp_meta.get("embed_url"))
            and not (html_meta.get("video_url") or html_meta.get("embed_url"))
        )
    ):
        need_playwright = True

    if use_playwright_fallback and need_playwright:
        try:
            pw_meta = await playwright_capture(page_url)
            # Re-parse DOM after rendering
            if pw_meta.get("html"):
                rendered_meta = parse_html_metadata(pw_meta["html"], page_url)
                for key in ("title", "thumbnail", "video_url", "embed_url"):
                    html_meta[key] = html_meta.get(key) or rendered_meta.get(key)
        except Exception:
            pw_meta = None

    return classify_playback(page_url, html_meta, ytdlp_meta, pw_meta)


# -------------------------
# Refresh stale stream only
# -------------------------
async def refresh_stream_only(page_url: str, cookie_file: Optional[str]) -> Optional[StreamRecord]:
    try:
        ytdlp_meta = await asyncio.to_thread(extract_with_ytdlp, page_url, cookie_file)
        stream = ytdlp_meta.get("stream") if ytdlp_meta else None
        if stream:
            url = stream["stream_url"]
            mime = stream["mime"] or infer_mime_from_url(url)
            expiry = parse_expiry_from_url(url) or default_expiry()
            return StreamRecord(
                stream_url=url,
                mime=mime,
                expires_at=expiry.isoformat(),
                last_refreshed=utc_now_iso(),
                status="ok",
            )
    except Exception:
        pass
    return None


# -------------------------
# Batch run
# -------------------------
async def main():
    links = load_json(LINKS_PATH, [])
    metadata_cache = load_json(METADATA_PATH, {})
    stream_cache = load_json(STREAM_CACHE_PATH, {})

    # Optional cookie file for blocked sites
    # Export one with yt-dlp or your browser extension when needed
    COOKIE_FILE = None  # e.g. str(DATA_DIR / "cookies.txt")

    total = len(links)
    print(f"Links loaded: {total}")

    for idx, item in enumerate(links, start=1):
        duration = item.get("duration",0)
        if not duration or duration==0:
            print(f"[{idx}/{total}] skip non-video entry (duration=0): {item.get('main_link')}")
        page_url = item.get("main_link")
        if not page_url:
            continue

        existing = metadata_cache.get(page_url)
        if existing:
            print(f"[{idx}/{total}] skip metadata (already cached): {page_url}")
            continue

        print(f"[{idx}/{total}] scraping metadata: {page_url}")

        try:
            meta, stream = await scrape_one(page_url, COOKIE_FILE, use_playwright_fallback=True)
            metadata_cache[page_url] = asdict(meta)

            if stream:
                stream_cache[page_url] = asdict(stream)

        except Exception as e:
            metadata_cache[page_url] = asdict(MetadataRecord(
                title=None,
                thumbnail=None,
                playback=asdict(Playback(kind="none", page_url=page_url)),
                playback_mode="none",
                last_scraped=utc_now_iso(),
                domain=urlparse(page_url).netloc,
                status="failed",
                note=str(e),
            ))

        save_json(METADATA_PATH, metadata_cache)
        save_json(STREAM_CACHE_PATH, stream_cache)

        # polite pacing
        await asyncio.sleep(random.uniform(2,4))

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())