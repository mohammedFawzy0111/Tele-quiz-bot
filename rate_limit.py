import time
from typing import Tuple, Dict
from config import USER_COOLDOWN_SECONDS, USER_TTL_SECONDS

user_last_request: Dict[int, float] = {}


def cleanup_users() -> None:
    now = time.time()
    to_delete = [
        uid for uid, ts in user_last_request.items()
        if now - ts > USER_TTL_SECONDS
    ]
    for uid in to_delete:
        del user_last_request[uid]


def check_rate_limit(user_id: int) -> Tuple[bool, float]:
    now = time.time()
    last = user_last_request.get(user_id)

    if last and now - last < USER_COOLDOWN_SECONDS:
        remaining = USER_COOLDOWN_SECONDS - (now - last)
        return False, remaining

    user_last_request[user_id] = now
    cleanup_users()
    return True, 0.0
