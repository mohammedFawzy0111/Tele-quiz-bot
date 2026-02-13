import os
import re
import logging

# ================== CONSTANTS ==================

DEFAULT_PORT = 8000

MAX_QUESTION_LENGTH = 300
MIN_OPTIONS = 2
MAX_OPTIONS = 12
POLL_DELAY = 0.2

FILE_SIZE_LIMIT_MB = 15
FILE_SIZE_LIMIT_BYTES = FILE_SIZE_LIMIT_MB * 1024 * 1024

TIMEOUT_SECONDS = 60

USER_COOLDOWN_SECONDS = 5
USER_TTL_SECONDS = 3600  # 1 hour

WEBHOOK_PATH = "/webhook"

NON_ASCII_RE = re.compile(r"[^\x00-\x7F]+")

# ================== LOGGING ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ================== ENV ==================

def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TOKEN = get_env("TOKEN")
WEBHOOK_URL = get_env("WEBHOOK_URL")
PORT = int(os.getenv("PORT", DEFAULT_PORT))
