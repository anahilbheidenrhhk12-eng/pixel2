"""Wit.ai-backed helpers for browser audio captcha challenges."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from selenium.common.exceptions import (
    JavascriptException,
    NoSuchFrameException,
    WebDriverException,
)
from selenium.webdriver.common.by import By

import config

logger = logging.getLogger(__name__)

WIT_AI_SPEECH_ENDPOINT = f"https://api.wit.ai/speech?v={config.WIT_AI_SPEECH_API_VERSION}"

_AUDIO_BUTTON_SELECTORS = (
    "#recaptcha-audio-button",
    'button[aria-label*="audio challenge" i]',
    '[role="button"][aria-label*="audio challenge" i]',
    'button[title*="audio challenge" i]',
    'button[aria-label*="audio" i]',
    '[role="button"][aria-label*="audio" i]',
    'button[title*="audio" i]',
    '[data-action*="audio" i]',
    ".button-audio",
)

_ANSWER_INPUT_SELECTORS = (
    "#audio-response",
    'input[aria-label*="text you hear" i]',
    'input[aria-label*="hear or see" i]',
    'input[aria-label*="hear" i]',
    'input[placeholder*="hear" i]',
    'input[placeholder*="answer" i]',
    'input[name="ca"]',
    'input[name*="captcha" i]',
    'input[id*="captcha" i]',
)

_VERIFY_BUTTON_SELECTORS = (
    "#recaptcha-verify-button",
    "#caNext",
    "#captchaNext",
    "#next",
    'button[type="submit"]',
    'button[aria-label*="verify" i]',
    'button[aria-label*="next" i]',
    '[role="button"][aria-label*="verify" i]',
    '[role="button"][aria-label*="next" i]',
    '[jsname="LgbsSe"]',
    ".button-submit",
)

_RELOAD_BUTTON_SELECTORS = (
    "#recaptcha-reload-button",
    'button[aria-label*="reload" i]',
    'button[aria-label*="refresh" i]',
    'button[aria-label*="new challenge" i]',
    'button[title*="reload" i]',
    'button[title*="refresh" i]',
    "[data-action*='reload' i]",
    ".button-refresh",
)

_ERROR_SELECTORS = (
    ".rc-audiochallenge-error-message",
    '[aria-live="assertive"]',
    '[role="alert"]',
    ".challenge-error",
    ".error-text",
)

_PASSWORD_FIELD_SELECTORS = (
    'input[type="password"]',
    'input[name="Passwd"]',
    'input[autocomplete="current-password"]',
)


class AudioCaptchaSolveError(Exception):
    """Raised when an audio captcha is found but could not be solved."""


@dataclass(slots=True)
class AudioCaptchaContext:
    """DOM snapshot for one audio captcha context."""

    frame_path: tuple[int, ...]
    audio_url: str
    mime_type: str
    audio_button_selector: str
    answer_input_selector: str
    verify_button_selector: str
    reload_button_selector: str
    error_text: str
    challenge_url: str
    page_excerpt: str
    score: int


_DETECT_CONTEXT_SCRIPT = r"""
const [
  audioButtonSelectors,
  answerInputSelectors,
  verifyButtonSelectors,
  reloadButtonSelectors,
  errorSelectors
] = arguments;

function isVisible(element) {
  if (!element) {
    return false;
  }
  const style = window.getComputedStyle(element);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    Number(style.opacity || "1") === 0
  ) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function pickSelector(selectors) {
  for (const selector of selectors) {
    try {
      const element = document.querySelector(selector);
      if (element && isVisible(element)) {
        return selector;
      }
    } catch (error) {
      // Ignore unsupported selectors.
    }
  }
  return "";
}

function firstText(selectors) {
  for (const selector of selectors) {
    try {
      const element = document.querySelector(selector);
      const value = String(
        element?.innerText ||
          element?.textContent ||
          element?.value ||
          ""
      )
        .replace(/\s+/g, " ")
        .trim();
      if (value) {
        return value;
      }
    } catch (error) {
      // Ignore unsupported selectors.
    }
  }
  return "";
}

function resolveUrl(candidate) {
  const raw = String(candidate || "").trim();
  if (!raw) {
    return "";
  }
  try {
    return new URL(raw, window.location.href).href;
  } catch (error) {
    return raw;
  }
}

function normalizeMimeType(rawMimeType) {
  const normalized = String(rawMimeType || "")
    .split(";")[0]
    .trim()
    .toLowerCase();
  return normalized || "audio/mpeg";
}

const audioSourceElement =
  document.querySelector("#audio-source") ||
  document.querySelector("audio[src]") ||
  document.querySelector("audio source[src]") ||
  document.querySelector("source[src]");
const downloadLink =
  document.querySelector("a.rc-audiochallenge-tdownload-link[href]") ||
  document.querySelector('a[href*=".mp3"]') ||
  document.querySelector('a[href*="/audio"]') ||
  document.querySelector('a[href*="audio"]');
const audioUrl = resolveUrl(
  audioSourceElement?.currentSrc ||
    audioSourceElement?.src ||
    audioSourceElement?.getAttribute?.("src") ||
    downloadLink?.href ||
    ""
);
const pageText = String(document.body?.innerText || "")
  .replace(/\s+/g, " ")
  .trim();
const normalizedPageText = pageText.toLowerCase();
const challengeMarkers = [
  "text you hear or see",
  "characters you see in the image above",
  "enter the characters",
  "audio challenge",
  "captcha",
  "recaptcha",
  "hcaptcha"
];
const hasChallengeMarkers = challengeMarkers.some(marker =>
  normalizedPageText.includes(marker)
);

return {
  audioUrl,
  mimeType: normalizeMimeType(
    audioSourceElement?.getAttribute?.("type") || downloadLink?.type || ""
  ),
  audioButtonSelector: pickSelector(audioButtonSelectors),
  answerInputSelector: pickSelector(answerInputSelectors),
  verifyButtonSelector: pickSelector(verifyButtonSelectors),
  reloadButtonSelector: pickSelector(reloadButtonSelectors),
  errorText: firstText(errorSelectors),
  challengeUrl: String(window.location.href || ""),
  pageExcerpt: pageText.slice(0, 240),
  hasChallengeMarkers
};
"""

_CLICK_SELECTOR_SCRIPT = r"""
const selector = arguments[0];

function isVisible(element) {
  if (!element) {
    return false;
  }
  const style = window.getComputedStyle(element);
  if (
    style.display === "none" ||
    style.visibility === "hidden" ||
    Number(style.opacity || "1") === 0
  ) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

const element = document.querySelector(selector);
if (!element || !isVisible(element)) {
  return false;
}

element.dispatchEvent(
  new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window })
);
element.dispatchEvent(
  new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window })
);
element.click();
return true;
"""

_SET_INPUT_VALUE_SCRIPT = r"""
const [selector, nextValue] = arguments;
const field = document.querySelector(selector);
if (!field) {
  return false;
}

try {
  const prototype =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor && descriptor.set) {
    descriptor.set.call(field, String(nextValue || ""));
  } else {
    field.value = String(nextValue || "");
  }
} catch (error) {
  field.value = String(nextValue || "");
}

field.dispatchEvent(new Event("input", { bubbles: true }));
field.dispatchEvent(new Event("change", { bubbles: true }));
return true;
"""

_FETCH_AUDIO_PAYLOAD_SCRIPT = r"""
const [audioUrl, mimeTypeHint] = arguments;
const done = arguments[arguments.length - 1];

function normalizeMimeType(rawMimeType) {
  const normalized = String(rawMimeType || "")
    .split(";")[0]
    .trim()
    .toLowerCase();
  return normalized || "audio/mpeg";
}

fetch(audioUrl, {
  method: "GET",
  credentials: "include",
  cache: "no-store"
})
  .then(async response => {
    if (!response.ok) {
      throw new Error(`Failed to fetch audio challenge (HTTP ${response.status})`);
    }
    const audioBuffer = await response.arrayBuffer();
    if (!audioBuffer.byteLength) {
      throw new Error("Audio challenge payload is empty");
    }
    const bytes = new Uint8Array(audioBuffer);
    let binary = "";
    const chunkSize = 32768;
    for (let index = 0; index < bytes.length; index += chunkSize) {
      const chunk = bytes.subarray(index, index + chunkSize);
      binary += String.fromCharCode(...chunk);
    }
    done({
      ok: true,
      audioBase64: btoa(binary),
      mimeType: normalizeMimeType(response.headers.get("content-type") || mimeTypeHint)
    });
  })
  .catch(error => {
    done({
      ok: false,
      error: error?.message || "Failed to fetch audio challenge"
    });
  });
"""


def wit_ai_is_available() -> bool:
    """Return True when automatic audio captcha solving is configured."""
    return bool(
        config.GOOGLE_CAPTCHA_AUTO_SOLVE
        and (config.WIT_AI_TOKEN or "").strip()
    )


def has_audio_captcha_challenge(driver) -> bool:
    """Return True when an audio captcha challenge is visible in the browser."""
    return _locate_best_audio_context(driver) is not None


def solve_audio_captcha_with_wit_ai(
    driver,
    max_attempts: int | None = None,
) -> bool:
    """Solve the current browser audio captcha with Wit.ai when possible."""
    if not wit_ai_is_available():
        return False

    attempts = max_attempts or config.GOOGLE_CAPTCHA_MAX_AUDIO_ATTEMPTS
    saw_challenge = False
    last_error = ""

    for attempt in range(1, attempts + 1):
        context = _locate_best_audio_context(driver)
        if not context:
            return saw_challenge

        saw_challenge = True
        logger.info(
            "Audio captcha detected via frame %s (attempt %s/%s).",
            context.frame_path or "(root)",
            attempt,
            attempts,
        )

        if not context.audio_url:
            if context.audio_button_selector:
                _switch_to_frame_path(driver, context.frame_path)
                clicked = _click_selector(driver, context.audio_button_selector)
                _restore_default_content(driver)
                if clicked:
                    time.sleep(1.8)
                    last_error = "Switched captcha into audio mode."
                    continue
            last_error = "Audio captcha was detected, but no audio source was available."
            break

        if not context.answer_input_selector or not context.verify_button_selector:
            time.sleep(1.0)
            last_error = "Audio captcha input is not ready yet."
            continue

        if context.error_text and context.reload_button_selector:
            _switch_to_frame_path(driver, context.frame_path)
            _click_selector(driver, context.reload_button_selector)
            _restore_default_content(driver)
            time.sleep(1.8)
            last_error = context.error_text
            continue

        transcript = _normalize_transcript(
            _transcribe_audio_with_wit_ai(
                *_fetch_audio_payload(driver, context.frame_path, context.audio_url, context.mime_type)
            )
        )
        if not transcript:
            last_error = "Wit.ai returned an empty transcript."
            if context.reload_button_selector:
                _switch_to_frame_path(driver, context.frame_path)
                _click_selector(driver, context.reload_button_selector)
                _restore_default_content(driver)
                time.sleep(1.8)
                continue
            break

        _switch_to_frame_path(driver, context.frame_path)
        set_ok = _set_input_value(driver, context.answer_input_selector, transcript)
        click_ok = _click_selector(driver, context.verify_button_selector)
        _restore_default_content(driver)

        if not set_ok or not click_ok:
            last_error = "Failed to submit the audio captcha transcript in the browser."
            break

        logger.info("Submitted audio captcha transcript via Wit.ai: %s", transcript)
        time.sleep(2.5)

        if _password_field_visible(driver):
            return True

        next_context = _locate_best_audio_context(driver)
        if not next_context:
            return True

        last_error = (
            next_context.error_text
            or "Audio captcha is still present after transcript submission."
        )
        if next_context.reload_button_selector:
            _switch_to_frame_path(driver, next_context.frame_path)
            _click_selector(driver, next_context.reload_button_selector)
            _restore_default_content(driver)
            time.sleep(1.8)

    if saw_challenge:
        raise AudioCaptchaSolveError(
            last_error or f"Failed to solve the audio captcha after {attempts} attempts."
        )
    return False


def _locate_best_audio_context(driver) -> AudioCaptchaContext | None:
    best_context: AudioCaptchaContext | None = None

    for frame_path in _iter_frame_paths(driver, max_depth=4):
        try:
            _switch_to_frame_path(driver, frame_path)
            raw_context = driver.execute_script(
                _DETECT_CONTEXT_SCRIPT,
                list(_AUDIO_BUTTON_SELECTORS),
                list(_ANSWER_INPUT_SELECTORS),
                list(_VERIFY_BUTTON_SELECTORS),
                list(_RELOAD_BUTTON_SELECTORS),
                list(_ERROR_SELECTORS),
            )
        except (JavascriptException, NoSuchFrameException, WebDriverException):
            continue
        finally:
            _restore_default_content(driver)

        context = _build_context(frame_path, raw_context)
        if not context:
            continue
        if not best_context or context.score > best_context.score:
            best_context = context

    return best_context


def _iter_frame_paths(driver, max_depth: int = 4) -> list[tuple[int, ...]]:
    queue: list[tuple[int, ...]] = [()]
    discovered: list[tuple[int, ...]] = []

    while queue:
        frame_path = queue.pop(0)
        discovered.append(frame_path)

        if len(frame_path) >= max_depth:
            continue

        try:
            _switch_to_frame_path(driver, frame_path)
            frame_count = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
        except (NoSuchFrameException, WebDriverException):
            frame_count = 0
        finally:
            _restore_default_content(driver)

        for index in range(frame_count):
            queue.append(frame_path + (index,))

    return discovered


def _switch_to_frame_path(driver, frame_path: tuple[int, ...]) -> None:
    _restore_default_content(driver)
    for index in frame_path:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        if index >= len(frames):
            raise NoSuchFrameException(frame_path)
        driver.switch_to.frame(frames[index])


def _restore_default_content(driver) -> None:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def _build_context(
    frame_path: tuple[int, ...],
    raw_context: dict[str, Any] | None,
) -> AudioCaptchaContext | None:
    if not isinstance(raw_context, dict):
        return None

    audio_url = str(raw_context.get("audioUrl") or "").strip()
    audio_button_selector = str(raw_context.get("audioButtonSelector") or "").strip()
    answer_input_selector = str(raw_context.get("answerInputSelector") or "").strip()
    verify_button_selector = str(raw_context.get("verifyButtonSelector") or "").strip()
    reload_button_selector = str(raw_context.get("reloadButtonSelector") or "").strip()
    challenge_url = str(raw_context.get("challengeUrl") or "").strip()
    page_excerpt = str(raw_context.get("pageExcerpt") or "").strip()
    error_text = str(raw_context.get("errorText") or "").strip()
    mime_type = _normalize_mime_type(raw_context.get("mimeType") or "")
    has_markers = bool(raw_context.get("hasChallengeMarkers"))

    score = 0
    if audio_url:
        score += 100
    if audio_button_selector:
        score += 30
    if answer_input_selector:
        score += 40
    if verify_button_selector:
        score += 20
    if reload_button_selector:
        score += 10
    if has_markers:
        score += 20
    if any(token in challenge_url.lower() for token in ("recaptcha", "hcaptcha", "google")):
        score += 10

    if score < 50:
        return None

    return AudioCaptchaContext(
        frame_path=frame_path,
        audio_url=audio_url,
        mime_type=mime_type,
        audio_button_selector=audio_button_selector,
        answer_input_selector=answer_input_selector,
        verify_button_selector=verify_button_selector,
        reload_button_selector=reload_button_selector,
        error_text=error_text,
        challenge_url=challenge_url,
        page_excerpt=page_excerpt,
        score=score,
    )


def _click_selector(driver, selector: str) -> bool:
    if not selector:
        return False
    return bool(driver.execute_script(_CLICK_SELECTOR_SCRIPT, selector))


def _set_input_value(driver, selector: str, value: str) -> bool:
    if not selector:
        return False
    return bool(driver.execute_script(_SET_INPUT_VALUE_SCRIPT, selector, value))


def _fetch_audio_payload(
    driver,
    frame_path: tuple[int, ...],
    audio_url: str,
    mime_type: str,
) -> tuple[str, str]:
    _switch_to_frame_path(driver, frame_path)
    try:
        payload = driver.execute_async_script(
            _FETCH_AUDIO_PAYLOAD_SCRIPT,
            audio_url,
            mime_type,
        )
    finally:
        _restore_default_content(driver)

    if not isinstance(payload, dict) or not payload.get("ok"):
        raise AudioCaptchaSolveError(
            str((payload or {}).get("error") or "Failed to fetch the audio captcha payload.")
        )

    audio_base64 = str(payload.get("audioBase64") or "").strip()
    resolved_mime_type = _normalize_mime_type(payload.get("mimeType") or mime_type)
    if not audio_base64:
        raise AudioCaptchaSolveError("Audio captcha payload was empty.")
    return audio_base64, resolved_mime_type


def _transcribe_audio_with_wit_ai(audio_base64: str, mime_type: str) -> str:
    if not (config.WIT_AI_TOKEN or "").strip():
        raise AudioCaptchaSolveError("WIT_AI_TOKEN is not configured.")

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception as exc:
        raise AudioCaptchaSolveError("Audio captcha payload is not valid base64.") from exc

    request = Request(
        WIT_AI_SPEECH_ENDPOINT,
        data=audio_bytes,
        headers={
            "Authorization": f"Bearer {config.WIT_AI_TOKEN.strip()}",
            "Accept": "application/json",
            "Content-Type": _normalize_mime_type(mime_type),
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=config.WIT_AI_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        payload = _parse_wit_ai_response_payload(raw_body)
        message = _extract_wit_ai_error(payload) or raw_body.strip()
        raise AudioCaptchaSolveError(
            message or f"Wit.ai request failed with HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise AudioCaptchaSolveError(
            f"Wit.ai network error: {exc.reason}"
        ) from exc

    payload = _parse_wit_ai_response_payload(raw_body)
    transcript = _extract_wit_ai_transcript(payload)
    if not transcript:
        raise AudioCaptchaSolveError("Wit.ai returned no transcript.")
    return transcript


def _parse_wit_ai_response_payload(raw_body: str = "") -> Any:
    normalized_body = str(raw_body or "").strip()
    if not normalized_body:
        return None

    try:
        return json.loads(normalized_body)
    except json.JSONDecodeError:
        parsed_items: list[Any] = []
        start_index = -1
        depth = 0
        in_string = False
        escape_next = False

        for index, character in enumerate(raw_body):
            if start_index == -1:
                if character in "{[":
                    start_index = index
                    depth = 1
                    in_string = False
                    escape_next = False
                continue

            if escape_next:
                escape_next = False
                continue

            if character == "\\" and in_string:
                escape_next = True
                continue

            if character == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if character in "{[":
                depth += 1
                continue

            if character in "}]":
                depth -= 1
                if depth == 0:
                    fragment = raw_body[start_index : index + 1]
                    try:
                        parsed_items.append(json.loads(fragment))
                    except json.JSONDecodeError:
                        pass
                    start_index = -1

        return parsed_items or None


def _extract_wit_ai_transcript(payload: Any) -> str:
    if not payload:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        for item in reversed(payload):
            transcript = _extract_wit_ai_transcript(item)
            if transcript:
                return transcript
        return ""
    if isinstance(payload, dict):
        for key in ("text", "_text", "transcript"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        outcomes = payload.get("outcomes")
        if isinstance(outcomes, list):
            for item in reversed(outcomes):
                transcript = _extract_wit_ai_transcript(item)
                if transcript:
                    return transcript
    return ""


def _extract_wit_ai_error(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, list):
        for item in reversed(payload):
            message = _extract_wit_ai_error(item)
            if message:
                return message
    return ""


def _normalize_transcript(raw_transcript: str) -> str:
    normalized = " ".join(str(raw_transcript or "").split())
    if not normalized:
        return ""

    tokens = [
        token
        for token in re.sub(r"[^a-zA-Z0-9\s-]", " ", normalized.lower()).split()
        if token
    ]
    if not tokens:
        return normalized

    digit_words = {
        "zero": "0",
        "oh": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
    }
    if all(token in digit_words or token.isdigit() for token in tokens):
        return "".join(digit_words.get(token, token) for token in tokens)
    if all(len(token) == 1 and token.isalnum() for token in tokens):
        return "".join(tokens)
    return normalized


def _normalize_mime_type(raw_mime_type: str) -> str:
    normalized = str(raw_mime_type or "").split(";", 1)[0].strip().lower()
    return normalized or "audio/mpeg"


def _password_field_visible(driver) -> bool:
    for selector in _PASSWORD_FIELD_SELECTORS:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        try:
            if element.is_displayed():
                return True
        except Exception:
            continue
    return False


__all__ = [
    "AudioCaptchaSolveError",
    "has_audio_captcha_challenge",
    "solve_audio_captcha_with_wit_ai",
    "wit_ai_is_available",
]
