from __future__ import annotations

from core.networks.web import get_bytes, get_json

_GIF_ENDPOINT = "https://api.otakugifs.xyz/gif"


async def fetch_action_gif(action: str) -> bytes:
    """
    Return the raw bytes of a reaction GIF for action.

        Two hops are required: the API hands back a JSON document pointing at the
        real asset, which we then download.
    
    """
    payload = await get_json(_GIF_ENDPOINT, params={"reaction": action})
    asset_url = payload["url"]
    return await get_bytes(asset_url)
