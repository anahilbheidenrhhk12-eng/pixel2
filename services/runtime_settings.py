"""Helpers for updating runtime configuration and the local .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path

import config


def _local_env_path() -> Path:
    """Return the project's local .env path."""
    return Path(config.__file__).resolve().with_name(".env")


def _format_env_value(value: str) -> str:
    """Return a .env-safe string representation."""
    raw = str(value or "")
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_./:@+-]+", raw):
        return raw
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def upsert_local_env_values(updates: dict[str, str]) -> Path:
    """Create or update one or more environment keys in the local .env file."""
    env_path = _local_env_path()
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    formatted = {key: _format_env_value(value) for key, value in updates.items()}

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in formatted:
            lines[index] = f"{key}={formatted.pop(key)}"

    for key, value in formatted.items():
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return env_path


def store_wit_ai_token(token: str) -> Path:
    """Persist a Wit.ai token to runtime and the local .env file."""
    normalized = str(token or "").strip()
    config.WIT_AI_TOKEN = normalized
    config.GOOGLE_CAPTCHA_AUTO_SOLVE = True
    os.environ["WIT_AI_TOKEN"] = normalized
    os.environ["GOOGLE_CAPTCHA_AUTO_SOLVE"] = "1"
    return upsert_local_env_values(
        {
            "WIT_AI_TOKEN": normalized,
            "GOOGLE_CAPTCHA_AUTO_SOLVE": "1",
        }
    )


def clear_wit_ai_token() -> Path:
    """Remove the active Wit.ai token from runtime and clear it from .env."""
    config.WIT_AI_TOKEN = ""
    os.environ["WIT_AI_TOKEN"] = ""
    return upsert_local_env_values({"WIT_AI_TOKEN": ""})


__all__ = [
    "clear_wit_ai_token",
    "store_wit_ai_token",
    "upsert_local_env_values",
]
