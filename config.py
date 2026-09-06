import os

from dotenv import load_dotenv

import logging_config  # noqa: F401  (imported for its module-level logging.basicConfig side effect)

load_dotenv()


def _int_env(name, default) -> int:
    return int(os.environ.get(name, default))


def _bool_env(name, default) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

BASE_URLS = {
    "sandbox": "https://api.dev.name.com",
    "production": "https://api.name.com",
}

NAMECOM_SANDBOX_USERNAME = os.environ["NAMECOM_SANDBOX_USERNAME"]
NAMECOM_SANDBOX_TOKEN = os.environ["NAMECOM_SANDBOX_TOKEN"]
NAMECOM_PROD_USERNAME = os.environ["NAMECOM_PROD_USERNAME"]
NAMECOM_PROD_TOKEN = os.environ["NAMECOM_PROD_TOKEN"]

# Sandbox tokens are only valid against a "-test" suffixed username; mixing them up returns an
# opaque 401 with no other clue, so fail loudly here instead of at the first API call.
if not NAMECOM_SANDBOX_USERNAME.endswith("-test"):
    raise ValueError(
        f"NAMECOM_SANDBOX_USERNAME must end in '-test', got: {NAMECOM_SANDBOX_USERNAME!r}"
    )

CREDENTIALS = {
    "sandbox": (NAMECOM_SANDBOX_USERNAME, NAMECOM_SANDBOX_TOKEN),
    "production": (NAMECOM_PROD_USERNAME, NAMECOM_PROD_TOKEN),
}

# name_client.py: 429 retry behavior.
NAMECOM_RATE_LIMIT_MAX_RETRIES = _int_env("NAMECOM_RATE_LIMIT_MAX_RETRIES", 3)
NAMECOM_RATE_LIMIT_MAX_AUTO_WAIT_SECONDS = _int_env("NAMECOM_RATE_LIMIT_MAX_AUTO_WAIT_SECONDS", 15)

# pipeline.py: off by default so this deployment never risks a real purchase. A deployer running
# their own copy with their own production credentials can opt into real registration by setting
# this — never enabled for the copy this project's own owner deploys.
NAMECOM_ALLOW_PRODUCTION_REGISTRATION = _bool_env("NAMECOM_ALLOW_PRODUCTION_REGISTRATION", False)

# jingle.py: GMI Cloud jingle generation feature flag. Set to false to disable if credits run low.
GMI_CLOUD_ENABLED = _bool_env("GMI_CLOUD_ENABLED", True)
GMI_MUSIC_MODEL = os.environ.get("GMI_MUSIC_MODEL", "minimax-music-3.0")

# llm.py: tuning for the SLD suggestion prompt.
LLM_MAX_TOKENS_SLDS = _int_env("LLM_MAX_TOKENS_SLDS", 150)
LLM_TEMPERATURE_SLDS = float(os.environ.get("LLM_TEMPERATURE_SLDS", 1.0))

# jingle.py: tuning for the jingle lyrics prompt.
LLM_MAX_TOKENS_LYRICS = _int_env("LLM_MAX_TOKENS_LYRICS", 150)
LLM_TEMPERATURE_LYRICS = float(os.environ.get("LLM_TEMPERATURE_LYRICS", 0.9))

# GMI Cloud API key: single key for all GMI Cloud services.
GMI_API_KEY = os.environ["GMI_API_KEY"]

# llm.py: MiniMax M3 chat endpoint.
GMI_CHAT_BASE_URL = os.environ.get("GMI_CHAT_BASE_URL", "https://api.gmi-serving.com/v1")
GMI_CHAT_MODEL = os.environ.get("GMI_CHAT_MODEL", "MiniMaxAI/MiniMax-M3")

# jingle.py / tts.py: GMI Cloud request queue base URL.
GMI_QUEUE_BASE_URL = os.environ.get("GMI_QUEUE_BASE_URL", "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey")

# tts.py: MiniMax Speech 2.8 voice ID and model.
GMI_TTS_VOICE = os.environ.get("GMI_TTS_VOICE", "English_Graceful_Lady")
GMI_TTS_MODEL = os.environ.get("GMI_TTS_MODEL", "minimax-tts-speech-2.8-hd")

# video_h3.py: MiniMax H3 Max video generation model and duration in seconds.
GMI_VIDEO_MODEL = os.environ.get("GMI_VIDEO_MODEL", "minimax/h3-max")
GMI_VIDEO_DURATION = _int_env("GMI_VIDEO_DURATION", 5)
