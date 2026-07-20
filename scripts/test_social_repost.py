"""End-to-end tests: Instagram + TikTok resolve + download (no session cookies)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

PASS = 0
FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {msg}")


IG_URL = "https://www.instagram.com/reel/DXbTOzTjWjW/"


async def test_vainapi_instagram():
    print("\n=== vain.rest Instagram ===")
    from core.api.vain_rest import VainRest

    ig = VainRest()

    try:
        resolved = await ig.instagram_resolve_media(IG_URL)
    except Exception as e:
        fail(f"resolve_media: {type(e).__name__}: {e}")
        return

    videos = resolved.get("video_urls") or []
    images = resolved.get("image_urls") or []
    if videos:
        ok(f"resolve_media video urls={len(videos)} source={resolved.get('source')}")
    else:
        fail(f"no video urls: {resolved}")
        return

    media_url = videos[0]
    try:
        data = await ig.instagram_download_media(media_url)
        raw = data.getvalue() if hasattr(data, "getvalue") else bytes(data)
        if len(raw) > 100_000 and raw[4:8] in (b"ftyp",) or raw[:8].find(b"ftyp") >= 0 or raw[4:8] == b"ftyp":
            ok(f"download_media {len(raw)} bytes ftyp ok")
        elif len(raw) > 100_000:
            ok(f"download_media {len(raw)} bytes (large)")
        else:
            fail(f"download too small: {len(raw)} head={raw[:16]!r}")
    except Exception as e:
        fail(f"download_media: {type(e).__name__}: {e}")

    try:
        posts = await ig.instagram_get_post(IG_URL)
        if posts and posts[0].get("video_url"):
            ok(f"get_post video_url set code={posts[0].get('code')}")
        else:
            fail(f"get_post missing video: {posts}")
    except Exception as e:
        fail(f"get_post: {type(e).__name__}: {e}")

    try:
        vurl = await ig.instagram_get_video_url(IG_URL)
        if vurl and vurl.startswith("http"):
            ok("get_video_url ok")
        else:
            fail(f"get_video_url bad: {vurl!r}")
    except Exception as e:
        fail(f"get_video_url: {e}")


async def test_networks_ig():
    print("\n=== networks.social.Instagram ===")
    from core.networks.social.ig import Instagram, is_instagram_url

    if not is_instagram_url(IG_URL):
        fail("is_instagram_url false")
    else:
        ok("is_instagram_url")

    client = Instagram()
    try:
        post = await client.post(IG_URL)
    finally:
        await client.close()

    if not post:
        fail("post() returned None")
        return
    if not post.media_urls:
        fail("post has no media_urls")
        return
    ok(f"post media_urls={len(post.media_urls)} is_video={post.is_video} user={post.username}")

    # download first media
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.instagram.com/"}
    ) as s:
        async with s.get(post.media_urls[0], timeout=aiohttp.ClientTimeout(total=45)) as r:
            data = await r.read()
            if r.status == 200 and len(data) > 50_000:
                ok(f"cdn download status=200 bytes={len(data)} ctype={r.content_type}")
            else:
                fail(f"cdn download status={r.status} bytes={len(data)}")


async def test_ig_repost_manager():
    print("\n=== IGRepost manager ===")
    from core.managers.repost.ig import IGRepost
    from unittest.mock import MagicMock

    bot = MagicMock()
    handler = IGRepost(bot)
    data = await handler.fetch(IG_URL)
    if data and data.get("url") and data.get("is_video"):
        ok(f"IGRepost.fetch url ok is_video={data.get('is_video')}")
    else:
        fail(f"IGRepost.fetch failed: {data}")


async def test_tiktok():
    print("\n=== TikTok ===")
    from core.networks.social.tiktok import TikTok, is_tiktok_url
    from core.managers.repost.tt import TikTokRepost
    from unittest.mock import MagicMock

    # Known-good public video used by downloader demos
    url = "https://www.tiktok.com/@philandmore/video/6805867805452324102"
    if not is_tiktok_url(url):
        fail("is_tiktok_url false")
        return
    ok("is_tiktok_url")

    client = TikTok()
    try:
        post = await client.post(url)
    finally:
        await client.close()

    if not post or not post.media_urls:
        fail(f"tiktok post failed: {post}")
        return
    ok(f"tiktok post user={post.username} media={len(post.media_urls)}")

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
        async with s.get(post.media_urls[0], timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.read()
            if r.status == 200 and len(data) > 10_000:
                ok(f"tiktok download bytes={len(data)}")
            else:
                fail(f"tiktok download status={r.status} bytes={len(data)}")

    handler = TikTokRepost(MagicMock())
    fetched = await handler.fetch(url)
    if fetched and fetched.get("url"):
        ok("TikTokRepost.fetch ok")
    else:
        fail(f"TikTokRepost.fetch: {fetched}")


async def test_socials_repost_path():
    print("\n=== socials._repost path (file only) ===")
    import inspect
    from ext.socials import socials as socials_mod

    src = inspect.getsource(socials_mod.Socials._repost)
    if "build_social_repost_container" in src or "components=" in src:
        fail("socials still builds embed/container")
    else:
        ok("socials._repost has no embed/container")
    if "ctx.send(file=" in src or "await ctx.send(file=upload)" in src:
        ok("socials._repost sends file only")
    else:
        fail("socials._repost does not send file")

    # simulate resolve+download like _repost would
    from core.networks.social import Instagram

    client = Instagram()
    try:
        post = await client.post(IG_URL)
    finally:
        await client.close()
    if not post or not post.media_urls:
        fail("socials path: no media")
        return
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.instagram.com/"}
    ) as s:
        async with s.get(post.media_urls[0], timeout=aiohttp.ClientTimeout(total=45)) as r:
            data = await r.read()
            if r.status == 200 and len(data) > 50_000 and (b"ftyp" in data[:32] or data[:1] == b"\x00"):
                ok(f"socials-equivalent download ok bytes={len(data)}")
            elif r.status == 200 and len(data) > 50_000:
                ok(f"socials-equivalent download ok bytes={len(data)} ctype={r.content_type}")
            else:
                fail(f"socials-equivalent download bad status={r.status} bytes={len(data)}")


async def main():
    print("social repost e2e tests (no IG session cookies)")
    await test_vainapi_instagram()
    await test_networks_ig()
    await test_ig_repost_manager()
    await test_tiktok()
    await test_socials_repost_path()
    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL == 0


if __name__ == "__main__":
    ok_all = asyncio.run(main())
    sys.exit(0 if ok_all else 1)
