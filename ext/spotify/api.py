from __future__ import annotations

import base64
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlencode

import aiohttp

from config import api as api_values

if TYPE_CHECKING:
    from core.managers.database.client import Database

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTH_URL = "https://accounts.spotify.com/authorize"
API_URL = "https://api.spotify.com/v1"

SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-modify",
    "user-top-read",
    "user-read-playback-position",
)

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


def redirect_uri() -> str:
    return api_values.spotify_redirect_uri or DEFAULT_REDIRECT_URI


def extract_auth_code(raw: str) -> str:
    text = raw.strip()
    if "code=" in text:
        return text.split("code=", 1)[1].split("&", 1)[0]
    return text


class SpotifyUserAPI:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._client_token: str | None = None
        self._client_token_expires = 0.0

    def _client_configured(self) -> bool:
        return bool(api_values.spotify_client_id and api_values.spotify_client_secret)

    async def _client_credentials_token(self) -> str | None:
        if not self._client_configured():
            return None
        now = time.monotonic()
        if self._client_token and now < self._client_token_expires - 30:
            return self._client_token

        auth = base64.b64encode(
            f"{api_values.spotify_client_id}:{api_values.spotify_client_secret}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {"grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, headers=headers, data=data, timeout=15) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
        self._client_token = payload.get("access_token")
        self._client_token_expires = now + int(payload.get("expires_in", 0))
        return self._client_token

    def build_login_url(self, *, state: str) -> str:
        params = {
            "client_id": api_values.spotify_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": " ".join(SCOPES),
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def new_state(self) -> str:
        return secrets.token_urlsafe(16)

    async def exchange_code(self, code: str) -> dict[str, Any]:
        auth = base64.b64encode(
            f"{api_values.spotify_client_id}:{api_values.spotify_client_secret}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {
            "grant_type": "authorization_code",
            "code": extract_auth_code(code),
            "redirect_uri": redirect_uri(),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, headers=headers, data=data, timeout=15) as resp:
                payload = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(payload.get("error_description") or "Spotify login failed")
                return payload

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        auth = base64.b64encode(
            f"{api_values.spotify_client_id}:{api_values.spotify_client_secret}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, headers=headers, data=data, timeout=15) as resp:
                payload = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(payload.get("error_description") or "Spotify token refresh failed")
                return payload

    async def save_tokens(self, user_id: int, payload: dict[str, Any]) -> None:
        expires_in = int(payload.get("expires_in", 3600))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        refresh_token = payload.get("refresh_token")
        row = await self.db.fetchrow(
            "SELECT refresh_token FROM spotify_tokens WHERE user_id = $1",
            user_id,
        )
        if not refresh_token and row:
            refresh_token = row["refresh_token"]
        if not refresh_token:
            raise RuntimeError("Spotify did not return a refresh token")

        await self.db.execute(
            """INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (user_id) DO UPDATE SET
                   access_token = excluded.access_token,
                   refresh_token = excluded.refresh_token,
                   expires_at = excluded.expires_at""",
            user_id,
            payload["access_token"],
            refresh_token,
            expires_at,
        )

    async def delete_tokens(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM spotify_tokens WHERE user_id = $1", user_id)

    async def is_linked(self, user_id: int) -> bool:
        row = await self.db.fetchrow(
            "SELECT 1 FROM spotify_tokens WHERE user_id = $1",
            user_id,
        )
        return row is not None

    async def _ensure_user_token(self, user_id: int) -> str:
        row = await self.db.fetchrow(
            "SELECT access_token, refresh_token, expires_at FROM spotify_tokens WHERE user_id = $1",
            user_id,
        )
        if not row:
            raise RuntimeError("Connect Spotify with `spotify login` first")

        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at > datetime.now(timezone.utc) + timedelta(seconds=30):
            return row["access_token"]

        payload = await self.refresh_access_token(row["refresh_token"])
        if "refresh_token" not in payload:
            payload["refresh_token"] = row["refresh_token"]
        await self.save_tokens(user_id, payload)
        return payload["access_token"]

    async def user_request(
        self,
        user_id: int,
        method: str,
        endpoint: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        token = await self._ensure_user_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}
        url = endpoint if endpoint.startswith("http") else f"{API_URL}/{endpoint.lstrip('/')}"
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=15,
            ) as resp:
                if resp.status == 204:
                    return None
                payload = await resp.json(content_type=None)
                if resp.status >= 400:
                    error = payload.get("error", {}) if isinstance(payload, dict) else {}
                    message = error.get("message") if isinstance(error, dict) else str(payload)
                    raise RuntimeError(message or f"Spotify API error ({resp.status})")
                return payload

    async def client_search(self, query: str, *, search_type: str = "track", limit: int = 5) -> dict | None:
        token = await self._client_credentials_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": query, "type": search_type, "limit": limit}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/search", headers=headers, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def get_track(self, track_id: str) -> dict | None:
        token = await self._client_credentials_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/tracks/{track_id}", headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def get_album(self, album_id: str) -> dict | None:
        token = await self._client_credentials_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/albums/{album_id}", headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def search_open_url(self, query: str) -> str:
        return f"https://open.spotify.com/search/{quote_plus(query)}"
