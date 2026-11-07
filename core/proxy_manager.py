"""Dynamic proxy pool management for Selenium sessions."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, unquote, urlsplit

import config

logger = logging.getLogger(__name__)


@dataclass
class ProxyStatus:
    """Runtime health state for a normalized proxy URL."""

    url: str
    fail_count: int = 0
    success_count: int = 0
    cooldown_until: float = 0.0
    quarantined_until: float = 0.0
    last_error_code: str | None = None
    last_latency_ms: float = 0.0


def normalize_proxy_url(raw_value: str) -> str:
    """Normalize multiple proxy formats into a canonical URL string."""
    value = (raw_value or "").strip().lstrip("\ufeff")
    if not value or value.startswith("#"):
        return ""

    if "://" not in value and value.count(":") == 3 and "@" not in value:
        host, port, username, password = value.split(":", 3)
        username = quote(username, safe="")
        password = quote(password, safe="")
        value = f"http://{username}:{password}@{host}:{port}"
    elif "://" not in value and "@" in value:
        value = f"http://{value}"
    elif "://" not in value:
        value = f"http://{value}"

    parsed = urlsplit(value)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"Invalid proxy format: {raw_value}")

    scheme = (parsed.scheme or "http").lower()
    if scheme not in {"http", "https", "socks5", "socks5h"}:
        raise ValueError(f"Unsupported proxy scheme: {scheme}")

    auth = ""
    if parsed.username is not None:
        username = quote(unquote(parsed.username), safe="")
        password = quote(unquote(parsed.password or ""), safe="")
        auth = f"{username}:{password}@"

    return f"{scheme}://{auth}{parsed.hostname}:{parsed.port}"


def mask_proxy_url(proxy_url: str | None) -> str:
    """Mask proxy credentials for logs and Telegram messages."""
    if not proxy_url:
        return "direct"

    try:
        parsed = urlsplit(normalize_proxy_url(proxy_url))
    except Exception:
        return "invalid"

    if parsed.username is None:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"

    return f"{parsed.scheme}://{unquote(parsed.username)}:****@{parsed.hostname}:{parsed.port}"


def parse_proxy_parts(proxy_url: str) -> dict[str, str | int | None]:
    """Return parsed proxy connection parts."""
    parsed = urlsplit(normalize_proxy_url(proxy_url))
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": unquote(parsed.username) if parsed.username is not None else None,
        "password": unquote(parsed.password) if parsed.password is not None else None,
    }


def resolve_runtime_proxy_url(
    proxy_url: str | None,
    proxy_session_token: str | None = None,
) -> str | None:
    """Return the proxy URL that should actually be used at runtime.

    The ``proxy_session_token`` argument is accepted for backward compatibility
    with callers that want to thread a per-Telegram-chat sticky-session token
    through the automation stack. It is currently unused: AutoPixel is proxy
    provider agnostic, so the token is not injected into the proxy URL. Custom
    sticky-session schemes can be added back here per provider if needed.
    """
    del proxy_session_token  # currently unused; kept for API stability
    if not proxy_url:
        return proxy_url
    try:
        return normalize_proxy_url(proxy_url)
    except Exception:
        return proxy_url


class ProxyManager:
    """Lightweight proxy pool with dynamic file reload and health tracking."""

    def __init__(self, proxy_file_path: str | None = None) -> None:
        self.proxy_file_path = proxy_file_path or config.PROXY_FILE_PATH
        self._proxies: dict[str, ProxyStatus] = {}
        self._proxy_file_mtime_ms = 0.0
        self._current_index = -1
        self.reload_if_changed(force=True)

    def _now(self) -> float:
        return time.time()

    def _upsert(self, proxy_url: str) -> ProxyStatus:
        normalized = normalize_proxy_url(proxy_url)
        existing = self._proxies.get(normalized)
        if existing:
            return existing

        status = ProxyStatus(url=normalized)
        self._proxies[normalized] = status
        return status

    def _sync_urls(self, urls: Iterable[str]) -> None:
        normalized_urls: set[str] = set()
        for item in urls:
            if not item or item.strip().startswith("#"):
                continue
            try:
                normalized = normalize_proxy_url(item)
            except Exception as exc:
                logger.warning("Skipping invalid proxy entry %r: %s", item, exc)
                continue
            if normalized:
                normalized_urls.add(normalized)

        for existing_url in list(self._proxies.keys()):
            if existing_url not in normalized_urls:
                self._proxies.pop(existing_url, None)

        for url in normalized_urls:
            self._upsert(url)

    def reload_if_changed(self, force: bool = False) -> None:
        """Reload proxies from file when the file changes."""
        if not config.PROXY_ENABLED:
            self._proxies.clear()
            self._proxy_file_mtime_ms = 0.0
            return

        if not os.path.exists(self.proxy_file_path):
            self._proxies.clear()
            self._proxy_file_mtime_ms = 0.0
            return

        try:
            stat = os.stat(self.proxy_file_path)
            mtime_ms = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)) / 1_000_000
            if not force and mtime_ms == self._proxy_file_mtime_ms:
                return

            self._proxy_file_mtime_ms = mtime_ms
            with open(self.proxy_file_path, "r", encoding="utf-8") as handle:
                raw_urls = [line.strip() for line in handle if line.strip()]
            self._sync_urls(raw_urls)
            logger.info("Proxy pool synced: %d entries", len(self._proxies))
        except Exception as exc:
            logger.warning("Failed to reload proxy file %s: %s", self.proxy_file_path, exc)

    def _is_quarantined(self, status: ProxyStatus) -> bool:
        return status.quarantined_until > self._now()

    def _is_cooling_down(self, status: ProxyStatus) -> bool:
        return status.cooldown_until > self._now()

    def has_pool(self) -> bool:
        """Return True when at least one proxy is available in the file."""
        self.reload_if_changed()
        return bool(self._proxies)

    def stats(self) -> dict[str, int]:
        """Return current proxy pool counts."""
        self.reload_if_changed()
        available = 0
        cooling_down = 0
        quarantined = 0

        for status in self._proxies.values():
            if self._is_quarantined(status):
                quarantined += 1
            elif self._is_cooling_down(status):
                cooling_down += 1
            else:
                available += 1

        return {
            "total": len(self._proxies),
            "available": available,
            "cooling_down": cooling_down,
            "quarantined": quarantined,
        }

    def get_proxy(self, preferred: str | None = None, excluded: set[str] | None = None) -> str | None:
        """Return a preferred or next healthy proxy from the pool."""
        self.reload_if_changed()
        excluded = excluded or set()

        if preferred:
            try:
                normalized_preferred = normalize_proxy_url(preferred)
            except Exception:
                normalized_preferred = ""
            status = self._proxies.get(normalized_preferred)
            if (
                status
                and not self._is_quarantined(status)
                and not self._is_cooling_down(status)
                and normalized_preferred not in excluded
            ):
                return status.url

        candidates = [
            status.url
            for status in self._proxies.values()
            if not self._is_quarantined(status) and not self._is_cooling_down(status) and status.url not in excluded
        ]

        if not candidates:
            candidates = [
                status.url
                for status in self._proxies.values()
                if not self._is_quarantined(status) and status.url not in excluded
            ]

        if not candidates:
            return None

        candidates.sort()
        self._current_index = (self._current_index + 1) % len(candidates)
        return candidates[self._current_index]

    def mark_success(self, proxy_url: str | None, latency_ms: float = 0.0) -> None:
        """Mark a proxy as healthy after a successful browser session."""
        if not proxy_url:
            return

        try:
            status = self._upsert(proxy_url)
        except Exception:
            return

        status.success_count += 1
        status.fail_count = 0
        status.cooldown_until = 0.0
        status.quarantined_until = 0.0
        status.last_error_code = None
        if latency_ms > 0:
            status.last_latency_ms = latency_ms

    def mark_failed(self, proxy_url: str | None, code: str = "error") -> None:
        """Apply cooldown or quarantine to a failed proxy."""
        if not proxy_url:
            return

        try:
            status = self._upsert(proxy_url)
        except Exception:
            return

        status.fail_count += 1
        status.last_error_code = code
        status.cooldown_until = self._now() + config.PROXY_FAILURE_COOLDOWN_SECONDS
        if status.fail_count >= config.PROXY_QUARANTINE_THRESHOLD:
            status.quarantined_until = self._now() + config.PROXY_QUARANTINE_SECONDS


PROXY_MANAGER = ProxyManager()
