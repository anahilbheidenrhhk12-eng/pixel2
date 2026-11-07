"""In-memory session storage with secure credential wiping."""

import logging
import time
import uuid

import config

logger = logging.getLogger(__name__)

# In-memory dict keyed by Telegram chat_id.
# Values: {"email": bytearray, "password": bytearray, "device": DeviceProfile,
#          "offer_link": str|None, "created_at": float}
SESSION_STORE: dict[int, dict] = {}


def is_session_expired(session: dict) -> bool:
    """Return True if *session* has exceeded the configured TTL."""
    created = session.get("created_at")
    if created is None:
        return False
    return (time.time() - created) > config.SESSION_TTL_SECONDS


def secure_wipe(data: bytearray) -> None:
    """Zero-fill a bytearray in-place so the original bytes are unrecoverable."""
    for i in range(len(data)):
        data[i] = 0


def ensure_proxy_session_token(session: dict, seed: str | None = None) -> str:
    """Return a stable per-session token for sticky proxy usernames."""
    existing = str(session.get("_proxy_session_token") or "").strip()
    if existing:
        return existing

    raw = str(seed or uuid.uuid4().hex).strip()
    token = "".join(ch for ch in raw.lower() if ch.isalnum())[:24]
    if not token:
        token = uuid.uuid4().hex[:12]

    session["_proxy_session_token"] = token
    return token


def clear_session(chat_id: int) -> None:
    """Securely wipe credentials and remove the session for *chat_id*."""
    session = SESSION_STORE.pop(chat_id, None)
    if session is None:
        return

    driver = session.get("_driver")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    for key in ("password", "email"):
        val = session.get(key)
        if isinstance(val, bytearray):
            secure_wipe(val)

    session.clear()
    logger.debug("Session cleared for chat %s", chat_id)


def get_session(chat_id: int) -> dict:
    """Return (creating if absent) the session dict for *chat_id*."""
    session = SESSION_STORE.get(chat_id)
    if session and is_session_expired(session):
        logger.info("Session expired for chat %s - purging", chat_id)
        clear_session(chat_id)
        session = None

    if session is None:
        SESSION_STORE[chat_id] = {}

    return SESSION_STORE[chat_id]


def purge_expired_sessions() -> int:
    """Remove all expired sessions. Returns the number purged."""
    expired = [cid for cid, sess in SESSION_STORE.items() if is_session_expired(sess)]
    for cid in expired:
        clear_session(cid)

    if expired:
        logger.info("Purged %d expired session(s)", len(expired))

    return len(expired)
