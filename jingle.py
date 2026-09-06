import asyncio
import logging
import os
import tempfile
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

import config
from llm import invoke
from time_it import time_it
from utils import load_prompt

logger = logging.getLogger(__name__)

_LYRICS_PROMPT = load_prompt("generate_jingle_lyrics.txt")
_GMI_BASE_URL = config.GMI_QUEUE_BASE_URL
_MUSIC_PROMPT = (
    "Upbeat pop jingle, catchy hook, bright and optimistic, male and female vocals, "
    "light percussion, suitable for any brand or product category, "
    "short instrumental intro of no more than 3 seconds before vocals start"
)


@time_it
async def generate_jingle(domain: str, description: str) -> tuple[str, str]:
    """Generate a jingle mp3 for a domain and app description.

    Returns:
        Tuple of (path to the generated mp3 temp file, lyrics string).
    """
    lyrics = await _generate_lyrics(domain, description)
    path = await _generate_mp3(lyrics, domain)
    return path, lyrics


async def _generate_lyrics(domain: str, description: str) -> str:
    text = f"Domain: {domain}\nApp description: {description}"
    lyrics = await invoke(
        _LYRICS_PROMPT,
        text,
        max_tokens=config.LLM_MAX_TOKENS_LYRICS,
        temperature=config.LLM_TEMPERATURE_LYRICS,
    )
    lyrics = lyrics.strip() + "\n"  # ensure trailing newline for music model
    logger.info("Jingle lyrics for %s:\n%s", domain, lyrics)
    return lyrics


_RATE_LIMIT_MARKER = "rate limit exceeded"
_RATE_LIMIT_WAITS = [10, 20, 30, 40, 50, 60, 60, 60, 60, 60]  # seconds between retries; worst-case total wait ~450s (~7.5 min) before giving up


async def _generate_mp3(lyrics: str, domain: str) -> str:
    for attempt in range(len(_RATE_LIMIT_WAITS) + 1):
        headers = {"Authorization": f"Bearer {config.GMI_API_KEY}"}
        async with httpx.AsyncClient(base_url=_GMI_BASE_URL, headers=headers, timeout=120) as client:
            logger.info("Submitting lyrics to MiniMax Music for audio generation...")
            data = await _submit(client, lyrics)
            request_id = data.get("request_id") or data.get("id")
            status = data.get("status")
            logger.info("GMI submit request_id=%s status=%s", request_id, status)

            if status not in ("success", "failed", "cancelled"):
                data = await _poll(client, request_id)
                status = data.get("status")

        if status == "success":
            break
        outcome = data.get("outcome") or {}
        if _RATE_LIMIT_MARKER in str(outcome) and attempt < len(_RATE_LIMIT_WAITS):
            wait = _RATE_LIMIT_WAITS[attempt]
            logger.warning("MiniMax Music rate limit — retrying in %ds (attempt %d/%d)", wait, attempt + 1, len(_RATE_LIMIT_WAITS))
            await asyncio.sleep(wait)
        else:
            raise RuntimeError(f"GMI jingle generation failed: status={status} outcome={outcome}")

    audio_url = _extract_audio_url(data)
    if not audio_url:
        raise RuntimeError(f"GMI jingle generation returned no audio URL: outcome={data.get('outcome')}")

    logger.info("Downloading jingle from %s", audio_url)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(audio_url)
        r.raise_for_status()

    filename = f"{domain.replace('.', '_')}_{int(time.time() * 1000)}.mp3"
    path = os.path.join(tempfile.gettempdir(), filename)
    with open(path, "wb") as f:
        f.write(r.content)

    logger.info("Jingle saved to %s (%d bytes)", path, len(r.content))
    return path


def _is_503(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 503


@retry(
    retry=retry_if_exception(_is_503),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    stop=stop_after_attempt(8),
    before_sleep=lambda rs: logger.info("GMI 503 — retrying in %.0fs (attempt %d/8)", rs.next_action.sleep, rs.attempt_number),
)
async def _submit(client: httpx.AsyncClient, lyrics: str) -> dict:
    resp = await client.post("/requests", json={
        "model": config.GMI_MUSIC_MODEL,
        "payload": {
            "lyrics": lyrics,
            "prompt": _MUSIC_PROMPT,
            "sample_rate": 44100,
            "bitrate": 128000,
            "format": "mp3",
        },
    })
    resp.raise_for_status()
    return resp.json()


async def _poll(client: httpx.AsyncClient, request_id: str) -> dict:
    deadline = time.time() + 180
    while time.time() < deadline:
        await asyncio.sleep(5)
        resp = await client.get(f"/requests/{request_id}")
        detail = resp.json()
        status = detail.get("status", "UNKNOWN")
        logger.info("GMI poll request_id=%s status=%s", request_id, status)
        if status in ("success", "failed", "cancelled"):
            return detail
    raise TimeoutError("GMI jingle generation timed out after 180s")


def _extract_audio_url(detail: dict) -> str | None:
    outcome = detail.get("outcome") or {}
    for entry in outcome.get("media_urls", []):
        if isinstance(entry, dict) and entry.get("url"):
            return entry["url"]
    return outcome.get("audio_url")
