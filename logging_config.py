import logging
import os
import sys

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# force=True guarantees this takes effect even if some other library (gradio, certbot, httpx)
# already called logging.basicConfig first — otherwise basicConfig silently no-ops if the root
# logger already has handlers, and Cloud Run would end up missing logs with no obvious cause.
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
