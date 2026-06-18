from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - local tooling fallback
    load_dotenv = None


API_BASE = "https://discord.com/api/v10"
REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
PACK_PREFIXES = {
    "ctx": "BLEED_EMOJI_",
    "paginator": "BLEED_EMOJI_PAGINATOR_",
    "interface": "BLEED_EMOJI_INTERFACE_",
}


def _request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    body = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "bleed-emoji-sync",
    }
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw)


def _application_id(token: str) -> str:
    data = _request_json(f"{API_BASE}/applications/@me", token=token)
    app_id = str(data.get("id", "")).strip()
    if not app_id:
        raise RuntimeError("could not resolve application id")
    return app_id


def _emoji_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return sanitized[:32]


def _upload_path(path: Path) -> Path:
    if path.suffix.lower() != ".svg":
        return path

    temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                str(temp_path),
            ],
            check=True,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{encoded}"


def _emoji_token(name: str, emoji_id: str, *, animated: bool = False) -> str:
    prefix = "a" if animated else ""
    return f"<{prefix}:{name}:{emoji_id}>"


def _env_key(emoji_dir: Path, name: str) -> str:
    prefix = PACK_PREFIXES.get(emoji_dir.name)
    if not prefix:
        raise RuntimeError(f"unsupported emoji pack: {emoji_dir.name}")
    return f"{prefix}{name.upper()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("emoji_dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env")

    token = (
        os.getenv("BLEED_TOKEN")
        or os.getenv("DISCORD_TOKEN")
        or os.getenv("TOKEN")
    )
    if not token:
        raise SystemExit("BLEED_TOKEN, DISCORD_TOKEN, or TOKEN is required")

    emoji_dir = args.emoji_dir.resolve()
    if not emoji_dir.is_dir():
        raise SystemExit(f"{emoji_dir} is not a directory")

    manifest_path = args.manifest or (emoji_dir / "app_emojis.json")
    app_id = _application_id(token)
    existing = _request_json(f"{API_BASE}/applications/{app_id}/emojis", token=token)
    existing_items = {
        str(item["name"]): item
        for item in existing.get("items", [])
        if isinstance(item, dict) and item.get("name")
    }

    source_files: dict[str, Path] = {}
    for path in sorted(emoji_dir.iterdir()):
        if not path.is_file() or path.name == manifest_path.name:
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        source_files[path.stem] = path

    uploaded: dict[str, str] = {}
    for name in sorted(source_files):
        image_path = source_files[name]
        upload_path = _upload_path(image_path)
        upload_name = _emoji_name(f"{emoji_dir.name}_{name}")
        try:
            current = existing_items.get(upload_name)
            if current:
                _request_json(
                    f"{API_BASE}/applications/{app_id}/emojis/{current['id']}",
                    token=token,
                    method="DELETE",
                )
            created = _request_json(
                f"{API_BASE}/applications/{app_id}/emojis",
                token=token,
                method="POST",
                payload={
                    "name": upload_name,
                    "image": _data_uri(upload_path),
                },
            )
            uploaded[_env_key(emoji_dir, name)] = _emoji_token(
                str(created["name"]),
                str(created["id"]),
                animated=bool(created.get("animated")),
            )
        finally:
            if upload_path != image_path:
                upload_path.unlink(missing_ok=True)

    manifest_path.write_text(json.dumps(uploaded, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
