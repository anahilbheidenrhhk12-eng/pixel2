"""Setup diagnostics helpers for first-run and onboarding checks."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import config
from core.proxy_manager import normalize_proxy_url


def _is_probable_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _inspect_header_media() -> dict[str, str | bool]:
    raw_value = (config.BOT_HEADER_MEDIA_URL or "").strip()
    if not raw_value:
        return {
            "mode": "disabled",
            "exists": False,
            "value": "",
        }

    if os.path.exists(raw_value):
        return {
            "mode": "local",
            "exists": True,
            "value": raw_value,
        }

    if _is_probable_url(raw_value):
        return {
            "mode": "remote",
            "exists": True,
            "value": raw_value,
        }

    return {
        "mode": "missing",
        "exists": False,
        "value": raw_value,
    }


def _detect_chrome_binary() -> str:
    """Return a detected Chrome path, or an empty string when not found."""
    candidates: list[str] = []

    def _add(candidate: str | None) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    _add(os.environ.get("CHROME_BIN"))
    for binary in ("chromium", "chromium-browser", "google-chrome", "chrome", "chrome.exe"):
        _add(shutil.which(binary))

    if os.name == "nt":
        for candidate in (
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ):
            _add(candidate)

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def _inspect_proxy_pool() -> dict[str, object]:
    proxy_file = Path(config.PROXY_FILE_PATH)
    if not config.PROXY_ENABLED:
        return {
            "enabled": False,
            "path": str(proxy_file),
            "exists": proxy_file.exists(),
            "readable": proxy_file.is_file(),
            "valid_entries": 0,
            "invalid_entries": 0,
        }

    if not proxy_file.exists():
        return {
            "enabled": True,
            "path": str(proxy_file),
            "exists": False,
            "readable": False,
            "valid_entries": 0,
            "invalid_entries": 0,
        }

    if not proxy_file.is_file():
        return {
            "enabled": True,
            "path": str(proxy_file),
            "exists": True,
            "readable": False,
            "valid_entries": 0,
            "invalid_entries": 0,
        }

    valid_entries = 0
    invalid_entries = 0
    try:
        for raw_line in proxy_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                normalize_proxy_url(line)
                valid_entries += 1
            except Exception:
                invalid_entries += 1
    except OSError:
        return {
            "enabled": True,
            "path": str(proxy_file),
            "exists": True,
            "readable": False,
            "valid_entries": 0,
            "invalid_entries": 0,
        }

    return {
        "enabled": True,
        "path": str(proxy_file),
        "exists": True,
        "readable": True,
        "valid_entries": valid_entries,
        "invalid_entries": invalid_entries,
    }


def _inspect_env_file() -> dict[str, str | bool]:
    env_path = Path(config.__file__).resolve().with_name(".env")
    return {
        "path": str(env_path),
        "exists": env_path.exists(),
    }


def collect_setup_diagnostics() -> dict[str, object]:
    """Return a first-run diagnostics snapshot for the current runtime."""
    header_media = _inspect_header_media()
    proxy_pool = _inspect_proxy_pool()
    env_file = _inspect_env_file()
    chrome_binary = _detect_chrome_binary()
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") or ""

    checks: list[dict[str, str]] = []
    checks.append({
        "name": "telegram_token",
        "status": "ok" if config.TELEGRAM_BOT_TOKEN else "fail",
    })
    checks.append({
        "name": "chrome_binary",
        "status": "ok" if chrome_binary else "fail",
    })
    checks.append({
        "name": "env_file",
        "status": "ok" if env_file["exists"] else "warn",
    })
    checks.append({
        "name": "header_media",
        "status": "ok" if header_media["exists"] else "warn",
    })

    if proxy_pool["enabled"]:
        if not proxy_pool["exists"]:
            checks.append({"name": "proxy_pool", "status": "warn"})
        elif not bool(proxy_pool.get("readable", False)):
            checks.append({"name": "proxy_pool", "status": "warn"})
        elif int(proxy_pool["valid_entries"]) == 0:
            checks.append({"name": "proxy_pool", "status": "warn"})
        elif int(proxy_pool["invalid_entries"]) > 0:
            checks.append({"name": "proxy_pool", "status": "warn"})
        else:
            checks.append({"name": "proxy_pool", "status": "ok"})
    else:
        checks.append({"name": "proxy_pool", "status": "ok"})

    if chromedriver_path:
        checks.append({
            "name": "chromedriver_path",
            "status": "ok" if os.path.exists(chromedriver_path) else "warn",
        })
    else:
        checks.append({"name": "chromedriver_path", "status": "ok"})

    has_fail = any(item["status"] == "fail" for item in checks)
    has_warn = any(item["status"] == "warn" for item in checks)

    return {
        "summary": "fail" if has_fail else "warn" if has_warn else "ok",
        "checks": checks,
        "env_file": env_file,
        "header_media": header_media,
        "proxy_pool": proxy_pool,
        "chrome_binary": chrome_binary,
        "chrome_version": config.CHROME_VERSION,
        "chrome_major_version": config.CHROME_MAJOR_VERSION,
        "chromedriver_path": chromedriver_path,
    }
