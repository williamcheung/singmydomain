import asyncio
import logging
import os
import tempfile
import time

import httpx

import config
from time_it import time_it

logger = logging.getLogger(__name__)

_GMI_BASE_URL = config.GMI_QUEUE_BASE_URL
_POLL_INTERVAL = 1
_POLL_TIMEOUT = 60
# Limit announcement delay before browser TTS takes over.
_TTS_WAIT_TIMEOUT = int(os.environ.get("TTS_WAIT_TIMEOUT_SECONDS", "3"))


@time_it
async def speak(text: str) -> str | None:
    """Attempt MiniMax Speech 2.8 TTS via GMI Cloud. Returns a path to the mp3 on success,
    or None on any failure so the caller can fall back to browser TTS.
    No retries — GMI is under heavy load during the hackathon and 503s are common; a single
    attempt keeps the fallback fast rather than making the user wait through retry delays.
    """
    try:
        path = await asyncio.wait_for(_generate(text), timeout=_TTS_WAIT_TIMEOUT)
        return path
    except asyncio.TimeoutError:
        # GMI job continues server-side (no cancel API) but httpx cleans up connections on cancel.
        logger.warning("MiniMax TTS timed out after %ds — falling back to browser TTS", _TTS_WAIT_TIMEOUT)
        return None
    except Exception as e:
        logger.warning("MiniMax TTS failed (%s) — falling back to browser TTS", e)
        return None


async def _generate(text: str) -> str:
    headers = {"Authorization": f"Bearer {config.GMI_API_KEY}"}
    async with httpx.AsyncClient(base_url=_GMI_BASE_URL, headers=headers, timeout=30) as client:
        request_id = await _submit(client, text)
        detail = await _poll(client, request_id)

    if detail.get("status") != "success":
        raise RuntimeError(f"MiniMax TTS status={detail.get('status')}")

    audio_url = _extract_audio_url(detail)
    if not audio_url:
        raise RuntimeError("MiniMax TTS returned no audio URL")

    logger.info("Downloading TTS audio from %s", audio_url)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(audio_url)
        r.raise_for_status()

    path = os.path.join(tempfile.gettempdir(), f"tts_{int(time.time() * 1000)}.mp3")
    with open(path, "wb") as f:
        f.write(r.content)
    logger.info("TTS audio saved to %s (%d bytes)", path, len(r.content))
    return path


async def _submit(client: httpx.AsyncClient, text: str) -> str:
    logger.info("Submitting TTS request: voice=%s text_len=%d", config.GMI_TTS_VOICE, len(text))
    payload = {
        "model": config.GMI_TTS_MODEL,
        "payload": {
            "text": text,
            "voice_id": config.GMI_TTS_VOICE,
            "speed": "1",
            "vol": "1",
            "pitch": "0",
            "emotion": "auto",
            "language_boost": "auto",
            "format": "mp3",
            "audio_sample_rate": "24000",
            "bitrate": "128000",
            "channel": "1",
        },
    }
    resp = await client.post("/requests", json=payload)
    if not resp.is_success:
        logger.warning("MiniMax TTS submit HTTP %d: %s", resp.status_code, resp.text[:300])
    if resp.status_code == 429:  # "Too Many Requests
        wait = int(resp.headers.get("Retry-After", 1))
        if wait > 2:
            raise RuntimeError(f"MiniMax TTS 429 Retry-After {wait}s too long — skipping retry")
        logger.info("MiniMax TTS 429 — retrying in %ds", wait)
        await asyncio.sleep(wait)
        resp = await client.post("/requests", json=payload)
        if not resp.is_success:
            logger.warning("MiniMax TTS submit retry HTTP %d: %s", resp.status_code, resp.text[:300])
    resp.raise_for_status()
    data = resp.json()
    request_id = data.get("request_id") or data.get("id")
    logger.info("MiniMax TTS submitted request_id=%s", request_id)
    return request_id


async def _poll(client: httpx.AsyncClient, request_id: str) -> dict:
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(_POLL_INTERVAL)
        resp = await client.get(f"/requests/{request_id}")
        detail = resp.json()
        status = detail.get("status", "UNKNOWN")
        logger.info("MiniMax TTS poll request_id=%s status=%s", request_id, status)
        if status in ("success", "failed", "cancelled"):
            return detail
    raise TimeoutError(f"MiniMax TTS timed out after {_POLL_TIMEOUT}s")


def _extract_audio_url(detail: dict) -> str | None:
    outcome = detail.get("outcome") or {}
    for entry in outcome.get("media_urls", []):
        if isinstance(entry, dict) and entry.get("url"):
            return entry["url"]
        if isinstance(entry, str):
            return entry
    return outcome.get("audio_url") or outcome.get("url")
