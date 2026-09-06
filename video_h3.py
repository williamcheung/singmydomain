import asyncio
import logging
import os
import tempfile
import time
from html import escape
from pathlib import Path

import httpx

import config
from time_it import time_it

logger = logging.getLogger(__name__)

_BASE_URL = config.GMI_QUEUE_BASE_URL
_MODEL = "MiniMax-H3"
_RESOLUTION = "768P"
_POLL_INTERVAL = 5
_POLL_TIMEOUT = 300
_SUBMIT_TIMEOUT = 10


@time_it
async def generate_video(domain: str, lyrics: str, duration: int = config.GMI_VIDEO_DURATION) -> tuple[str, str]:
    """Generate a video mp4 to accompany a jingle for a domain via GMI Cloud (MiniMax-H3).

    Returns:
        Paths to the downloaded MP4 and its chorus captions (WebVTT).
    """
    chorus = _extract_chorus(lyrics)
    prompt = (
        f"Cinematic brand video for domain {domain}. "
        "Visual style: live action or high-quality animation, warm colors, bright, optimistic, and uplifting mood. "
        "The following jingle lyrics should be delivered as a voiceover, not spoken by characters on screen."
        f"\nLyrics:\n{chorus}"
    )
    headers = {"Authorization": f"Bearer {config.GMI_API_KEY}"}

    async with httpx.AsyncClient(base_url=_BASE_URL, headers=headers, timeout=30) as client:
        generation_id = await _submit(client, prompt, duration)
        result = await _poll(client, generation_id)

    video_url = (result.get("outcome") or {}).get("video_url")
    if not video_url:
        raise RuntimeError(f"Video generation returned no URL: {result}")

    logger.info("Downloading video from %s", video_url)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        r = await client.get(video_url)
        r.raise_for_status()

    filename = f"{domain.replace('.', '_')}_{int(time.time() * 1000)}.mp4"
    path = os.path.join(tempfile.gettempdir(), filename)
    with open(path, "wb") as f:
        f.write(r.content)
    logger.info("Video saved to %s (%d bytes)", path, len(r.content))
    subtitle_path = Path(path).with_suffix(".vtt")
    subtitle_path.write_text(_chorus_vtt(lyrics, duration), encoding="utf-8")
    return path, str(subtitle_path)


def _chorus_vtt(lyrics: str, duration: float) -> str:
    """Spread chorus lines across the clip; these are not speech-aligned timestamps."""
    lines = [
        line.strip() for line in _extract_chorus(lyrics).splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    if not lines or duration <= 0:
        raise ValueError("Captions require lyrics and a positive video duration")

    def timestamp(milliseconds: int) -> str:
        seconds, milliseconds = divmod(milliseconds, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

    # Known limitation: evenly spaced cues do not follow the generated speech.
    # Increasing the video duration stretches caption timings even if the speech
    # timing stays the same, so captions can become further out of sync.
    # Accurate synchronization would require timestamps from the video audio.
    total_ms = round(duration * 1000)
    cues = []
    for index, line in enumerate(lines):
        start = round(index * total_ms / len(lines))
        end = round((index + 1) * total_ms / len(lines))
        cues.append(f"{timestamp(start)} --> {timestamp(end)}\n{escape(line, quote=False)}")
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n"


def _extract_chorus(lyrics: str) -> str:
    """Extract the chorus lines from lyrics, stripping the [chorus] tag.
    Falls back to the full lyrics if no chorus section is found.
    """
    lines = lyrics.splitlines()
    in_chorus = False
    chorus_lines = []
    for line in lines:
        if line.strip().lower() == "[chorus]":
            in_chorus = True
            continue
        if in_chorus:
            if line.strip().startswith("["):
                break
            chorus_lines.append(line)
    return "\n".join(chorus_lines).strip() or lyrics.strip()


async def _submit(client: httpx.AsyncClient, prompt: str, duration: int) -> str:
    logger.info("Submitting video generation request: domain in prompt, duration=%ds", duration)
    resp = await client.post("/requests", timeout=_SUBMIT_TIMEOUT, json={
        "model": _MODEL,
        "payload": {
            "prompt": prompt,
            "resolution": _RESOLUTION,
            "duration": duration,
            "ratio": "16:9",
        },
    })
    if not resp.is_success:
        logger.warning("Video generation submit HTTP %d: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status in ("failed", "cancelled"):
        raise RuntimeError(f"Video generation submit failed: status={status} outcome={data.get('outcome')}")
    generation_id = data["request_id"]
    logger.info("Video generation submitted id=%s status=%s", generation_id, status)
    return generation_id


async def _poll(client: httpx.AsyncClient, generation_id: str) -> dict:
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(_POLL_INTERVAL)
        resp = await client.get(f"/requests/{generation_id}")
        if not resp.is_success:
            logger.warning("Video generation poll HTTP %d: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status", "unknown")
        logger.info("Video generation poll id=%s status=%s", generation_id, status)
        if status in ("success", "failed", "cancelled"):
            if status != "success":
                raise RuntimeError(f"Video generation failed: {result}")
            return result
    raise TimeoutError(f"Video generation timed out after {_POLL_TIMEOUT}s")


if __name__ == "__main__":
    import asyncio

    import logging_config  # noqa: F401

    async def main():
        domain = "coupleslastchances.io"
        lyrics = """[intro]
Couples Last Chances dot I O

[chorus]
Couples Last Chances dot I O
Love worth saving, start today
One more try, the better way
Couples Last Chances dot I O"""
        path, subtitle_path = await generate_video(domain, lyrics)
        print(f"Video saved to: {path}")
        print(f"Captions saved to: {subtitle_path}")

    asyncio.run(main())
