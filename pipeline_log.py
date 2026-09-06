"""Captures key pipeline log entries for display in the Gradio UI pipeline log accordion.

Attaches to the name_client, acme_client, llm, jingle, tts, video_h3, video_fallback, and
application loggers and filters/transforms their output into clean one-line entries
suitable for display without wrapping.
"""

import logging
import re
from collections import deque
from datetime import datetime

_MAX_ENTRIES = 200
_entries: deque[str] = deque(maxlen=_MAX_ENTRIES)


def get_log() -> str:
    return "\n".join(_entries)


def clear_log() -> None:
    _entries.clear()


class PipelineLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        line = self._format_record(record)
        if line and line.strip():
            _entries.append(line.strip())

    def _format_record(self, record: logging.LogRecord) -> str | None:
        msg = record.getMessage()
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        logger = record.name

        # time_it timing lines — already clean, just reformat
        if "[TIME]" in msg:
            # e.g. "29-Aug-26 17:44:22 [TIME] name_client.py:265 - [_attempt] took 0.88 sec"
            match = re.search(r"\[(\w+)\] took ([\d.]+) sec", msg)
            if match:
                fn, duration = match.group(1), match.group(2)
                return f"{ts} ⏱ [{logger}] {fn} took {duration}s"
            return None

        # name_client: API response lines — strip body
        if "name.com API response:" in msg:
            # keep everything up to body=
            line = re.sub(r"\s*body=.*$", "", msg, flags=re.DOTALL)
            return f"{ts} ✓ {line}"

        # name_client: API request lines — strip body
        if "name.com API request:" in msg:
            line = re.sub(r"\s*body=.*$", "", msg, flags=re.DOTALL)
            return f"{ts} → {line}"

        # name_client: API errors
        if "name.com API request failed:" in msg:
            return f"{ts} ✗ {msg}"

        # acme_client: hook log lines surfaced from acme_hooks.py subprocess
        if msg.startswith("acme_hook: "):
            return f"{ts} ✓ {msg[len('acme_hook: '):]}"

        # acme_client: key status lines
        if any(phrase in msg for phrase in (
            "Starting certbot",
            "certbot succeeded",
            "certbot failed",
            "Revoking certificate",
            "certbot revoke succeeded",
            "certbot revoke failed",
        )):
            line = " ".join(msg.split())  # collapse whitespace and newlines first
            line = re.sub(r"Saving debug log to \S+", "", line)
            line = re.sub(r"See the logfile \S+", "", line)
            line = re.sub(r"Ask for help or search for solutions at \S+", "", line)
            line = re.sub(r"or re-run Certbot with -v for more details\.?", "", line)
            line = " ".join(line.split())  # clean up any double spaces left behind
            return f"{ts} {'\u2713' if 'succeeded' in line or 'Starting' in line or 'Revoking' in line else '\u2717'} {line}"

        # llm: invoking line — strip full prompt text, keep model + char count
        if msg.startswith("Invoking "):
            match = re.match(r"Invoking (\S+) with (\d+) char prompt", msg)
            if match:
                return f"{ts} → LLM {match.group(1)} ({match.group(2)} chars)"
            return None

        # llm: response line
        if msg.startswith("LLM response:"):
            return f"{ts} ✓ {msg}"

        # jingle: key status lines
        if "Jingle lyrics for" in msg:
            domain = re.search(r"Jingle lyrics for (.+?):", msg)
            return f"{ts} ✓ Jingle lyrics generated for {domain.group(1)}" if domain else None
        if "Submitting lyrics to MiniMax Music" in msg:
            return f"{ts} ⏳ {msg}"
        if "GMI submit" in msg:
            return f"{ts} {'✗' if 'status=failed' in msg else '✓'} {msg}"
        if "MiniMax Music rate limit" in msg:
            match = re.search(r"retrying in (\d+)s \(attempt (\d+)/(\d+)\)", msg)
            return f"{ts} ⚠ MiniMax Music rate limit — retrying in {match.group(1)}s (attempt {match.group(2)}/{match.group(3)})" if match else f"{ts} ⚠ {msg}"
        if "Downloading jingle from" in msg:
            return f"{ts} ✓ {msg}"
        # tts: key status lines
        if "Submitting TTS request:" in msg:
            match = re.search(r"voice=(\S+) text_len=(\d+)", msg)
            if match:
                return f"{ts} → MiniMax TTS request: voice={match.group(1)} text_len={match.group(2)}"
            return None
        if "MiniMax TTS submitted" in msg:
            return f"{ts} ✓ {msg}"
        if "MiniMax TTS poll" in msg:
            return f"{ts} ⏳ {msg}"
        if "TTS audio saved" in msg:
            return f"{ts} ✓ {msg}"
        if "MiniMax TTS submit HTTP" in msg:
            return f"{ts} ✗ {msg}"
        if "MiniMax TTS 429" in msg:
            return f"{ts} ⏳ {msg}"
        if "MiniMax TTS submit retry HTTP" in msg:
            return f"{ts} ✗ {msg}"
        if "MiniMax TTS failed" in msg:
            return f"{ts} ✗ {msg}"
        if "MiniMax TTS timed out" in msg:
            return f"{ts} ⚠ {msg}"

        # video: key status lines
        if "Submitting video generation request:" in msg:
            match = re.search(r"duration=(\d+)s", msg)
            return f"{ts} ⏳ Submitting video generation request (duration={match.group(1)}s)" if match else f"{ts} ⏳ {msg}"
        if "Video generation submitted" in msg:
            return f"{ts} ✓ {msg}"
        if "Video generation submit HTTP" in msg:
            return f"{ts} ✗ {msg.splitlines()[0]}"
        if "GMI video generation failed" in msg or ("falling back" in msg and "video" in msg.lower()):
            return f"{ts} ⚠ {msg.splitlines()[0]}"
        if "Video generation poll HTTP" in msg:
            return f"{ts} ✗ {msg}"
        if "Video generation poll" in msg:
            return f"{ts} ⏳ {msg}"
        if "Generating video for" in msg:
            return f"{ts} ⏳ {msg}"
        if "Video ready:" in msg:
            return f"{ts} ✓ {msg}"
        if "Downloading video from" in msg:
            return f"{ts} ✓ {msg}"
        if "Video saved to" in msg:
            match = re.search(r"Video saved to .+?([^\\/]+\.mp4) \((\d+) bytes\)", msg)
            if match:
                return f"{ts} ✓ Video saved: {match.group(1)} ({int(match.group(2)):,} bytes)"
            return None

        return None


def attach() -> None:
    """Attach the pipeline log handler to all relevant loggers. Safe to call multiple times."""
    handler = PipelineLogHandler()
    handler.setLevel(logging.DEBUG)
    for name in ("name_client", "acme_client", "llm", "jingle", "tts", "__main__"):
        logger = logging.getLogger(name)
        if not any(isinstance(h, PipelineLogHandler) for h in logger.handlers):
            logger.addHandler(handler)
