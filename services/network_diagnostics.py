"""Small network diagnostics helpers for active proxy inspection."""

from __future__ import annotations

import json
import logging
import ssl
import time
from collections.abc import Mapping
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

import httpx

import config
from core.proxy_manager import (
    mask_proxy_url,
    normalize_proxy_url,
    parse_proxy_parts,
    resolve_runtime_proxy_url,
)

IP_API_URL = "https://ipwho.is/"
GOOGLE_SIGNIN_PROBE_URL = "https://accounts.google.com/signin/v2/identifier"

logger = logging.getLogger(__name__)


def _build_proxy_handler(proxy_url: str | None) -> ProxyHandler:
    if not proxy_url:
        return ProxyHandler({})

    normalized = normalize_proxy_url(proxy_url)
    parsed = urlsplit(normalized)
    if parsed.scheme.startswith("socks"):
        raise RuntimeError("SOCKS proxy probing is not supported by the current /ip command.")

    return ProxyHandler({
        "http": normalized,
        "https": normalized,
    })


def _normalize_http_proxy(proxy_url: str | None) -> str | None:
    if not proxy_url:
        return None

    normalized = normalize_proxy_url(proxy_url)
    parsed = urlsplit(normalized)
    if parsed.scheme.startswith("socks"):
        raise RuntimeError("SOCKS proxy probing is not supported by the current /ip command.")
    return normalized


def _format_probe_error(prefix: str, exc: Exception) -> RuntimeError:
    message = str(exc)
    lowered = message.lower()
    if "407" in lowered or "proxy authentication required" in lowered:
        return RuntimeError(
            f"{prefix}: Proxy authentication failed (407). "
            "Please rotate the proxy or verify the proxy username/password."
        )
    if (
        "bad_endpoint" in lowered
        or "robots.txt" in lowered
        or "policy_20130" in lowered
        or "policy_20140" in lowered
    ):
        return RuntimeError(
            f"{prefix}: The proxy provider blocked this destination by policy. "
            "Try a different proxy from the pool or switch to direct mode."
        )
    return RuntimeError(f"{prefix}: {exc}")


def _should_verify_ssl(proxy_url: str | None) -> bool:
    """Keep strict TLS checks for direct traffic but allow proxy probes to relax them."""
    return not proxy_url or config.PROXY_DIAGNOSTICS_VERIFY_SSL


def _build_ssl_context(proxy_url: str | None) -> ssl.SSLContext:
    """Return an SSL context that matches the configured probe verification mode."""
    if _should_verify_ssl(proxy_url):
        return ssl.create_default_context()
    logger.warning(
        "Skipping TLS certificate verification for proxy diagnostics via %s",
        mask_proxy_url(proxy_url),
    )
    return ssl._create_unverified_context()


def _resolve_probe_target(proxy_url: str | None) -> tuple[str, tuple[str, ...], str]:
    """Pick a provider-safe probe URL for the current proxy route."""
    del proxy_url  # AutoPixel is proxy provider agnostic; always probe Google.
    return (
        GOOGLE_SIGNIN_PROBE_URL,
        ("accounts.google.com", ".google.com"),
        "Google sign-in",
    )


def _open_json_with_httpx(url: str, proxy_url: str | None, timeout: int = 15) -> dict:
    normalized_proxy = _normalize_http_proxy(proxy_url)
    with httpx.Client(
        proxy=normalized_proxy,
        timeout=timeout,
        follow_redirects=True,
        verify=_should_verify_ssl(proxy_url),
    ) as client:
        response = client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        if response.status_code == 407:
            raise RuntimeError("407 Proxy Authentication Required")
        response.raise_for_status()
        return response.json()


def _open_json_with_urllib(url: str, proxy_url: str | None, timeout: int = 15) -> dict:
    handler = _build_proxy_handler(proxy_url)
    context = _build_ssl_context(proxy_url)
    opener = build_opener(handler, HTTPSHandler(context=context))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _probe_url_with_httpx(
    url: str,
    proxy_url: str | None,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, float]:
    normalized_proxy = _normalize_http_proxy(proxy_url)
    started = time.perf_counter()
    with httpx.Client(
        proxy=normalized_proxy,
        timeout=timeout,
        follow_redirects=True,
        verify=_should_verify_ssl(proxy_url),
    ) as client:
        response = client.get(url, headers=headers)
        if response.status_code == 407:
            raise RuntimeError("407 Proxy Authentication Required")
        response.raise_for_status()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return response.status_code, str(response.url), latency_ms


def _probe_url_with_urllib(
    url: str,
    proxy_url: str | None,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, float]:
    handler = _build_proxy_handler(proxy_url)
    context = _build_ssl_context(proxy_url)
    opener = build_opener(handler, HTTPSHandler(context=context))
    request = Request(url, headers=headers or {})
    started = time.perf_counter()
    with opener.open(request, timeout=timeout) as response:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        final_url = response.geturl()
        status_code = getattr(response, "status", None) or response.getcode()
        return int(status_code), final_url, latency_ms


def inspect_connection(
    proxy_url: str | None,
    proxy_session_token: str | None = None,
) -> dict[str, str]:
    """Return masked proxy info plus public IP and geo summary."""
    runtime_proxy_url = resolve_runtime_proxy_url(proxy_url, proxy_session_token)
    try:
        payload = _open_json_with_httpx(IP_API_URL, runtime_proxy_url, timeout=15)
    except Exception as exc:
        try:
            payload = _open_json_with_urllib(IP_API_URL, runtime_proxy_url, timeout=15)
        except URLError as fallback_exc:
            raise _format_probe_error(
                "Failed to probe public IP",
                fallback_exc.reason if getattr(fallback_exc, "reason", None) else fallback_exc,
            ) from fallback_exc
        except Exception as fallback_exc:
            raise _format_probe_error("Failed to probe public IP", fallback_exc) from fallback_exc

    if payload.get("success") is False:
        raise RuntimeError("The IP geo service returned an unsuccessful response.")

    ip_address = str(payload.get("ip") or payload.get("query") or "-")
    country = str(payload.get("country") or "-")
    country_code = str(payload.get("country_code") or payload.get("countryCode") or "-")
    continent = str(payload.get("continent") or "-")
    region = str(payload.get("region") or payload.get("regionName") or "-")
    city = str(payload.get("city") or "-")
    postal = str(payload.get("postal") or "-")
    latitude = str(payload.get("latitude") or "-")
    longitude = str(payload.get("longitude") or "-")
    connection = payload.get("connection", {}) or {}
    timezone = payload.get("timezone", {}) or {}
    isp = str(connection.get("isp") or payload.get("isp") or "-")
    org = str(connection.get("org") or "-")
    asn = str(connection.get("asn") or "-")
    domain = str(connection.get("domain") or "-")
    timezone_id = str(timezone.get("id") or "-")
    timezone_utc = str(timezone.get("utc") or "-")
    timezone_abbr = str(timezone.get("abbr") or "-")

    result = {
        "proxy": mask_proxy_url(proxy_url),
        "ip": ip_address,
        "continent": continent,
        "country": country,
        "country_code": country_code,
        "region": region,
        "city": city,
        "postal": postal,
        "latitude": latitude,
        "longitude": longitude,
        "org": org,
        "isp": isp,
        "asn": asn,
        "domain": domain,
        "timezone": timezone_id,
        "timezone_utc": timezone_utc,
        "timezone_abbr": timezone_abbr,
    }

    proxy_parts = parse_proxy_parts(runtime_proxy_url) if runtime_proxy_url else None
    if proxy_parts:
        result["proxy_host"] = f"{proxy_parts['host']}:{proxy_parts['port']}"

    return result


def format_connection_identity(
    result: Mapping[str, str],
    title: str = "🌍 Connection Identity",
) -> str:
    """Return a readable multi-line connection/proxy summary."""
    lines = [
        title,
        f"🌐 Proxy: {result.get('proxy', '-')}",
    ]

    proxy_host = result.get("proxy_host")
    if proxy_host:
        lines.append(f"🔌 Proxy host: {proxy_host}")

    lines.extend(
        [
            f"🧷 Public IP: {result.get('ip', '-')}",
            f"🏳️ Country: {result.get('country', '-')} ({result.get('country_code', '-')})",
            f"🗺️ Continent: {result.get('continent', '-')}",
            f"📍 Region: {result.get('region', '-')}",
            f"🏙️ City: {result.get('city', '-')}",
        ]
    )

    postal = result.get("postal")
    if postal and postal != "-":
        lines.append(f"📮 ZIP: {postal}")

    timezone_id = result.get("timezone", "-")
    timezone_utc = result.get("timezone_utc", "-")
    timezone_abbr = result.get("timezone_abbr", "-")
    timezone_bits = [part for part in (timezone_id, timezone_abbr, timezone_utc) if part and part != "-"]
    if timezone_bits:
        lines.append(f"🕒 Timezone: {' | '.join(timezone_bits)}")

    latitude = result.get("latitude", "-")
    longitude = result.get("longitude", "-")
    if latitude != "-" and longitude != "-":
        lines.append(f"🧭 Coordinates: {latitude}, {longitude}")

    org = result.get("org")
    if org and org != "-":
        lines.append(f"🏢 Brand/Org: {org}")

    isp = result.get("isp")
    if isp and isp != "-" and isp != org:
        lines.append(f"🛰️ ISP: {isp}")

    asn = result.get("asn")
    if asn and asn != "-":
        lines.append(f"🔢 ASN: {asn}")

    domain = result.get("domain")
    if domain and domain != "-":
        lines.append(f"🌐 Domain: {domain}")

    return "\n".join(lines)


def probe_google_signin(
    proxy_url: str | None,
    timeout: int = 12,
    proxy_session_token: str | None = None,
) -> dict[str, str | float | int]:
    """Return a quick reachability check for the current proxy route."""
    runtime_proxy_url = resolve_runtime_proxy_url(proxy_url, proxy_session_token)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    probe_url, expected_hosts, target_label = _resolve_probe_target(runtime_proxy_url)
    try:
        status_code, final_url, latency_ms = _probe_url_with_httpx(
            probe_url,
            runtime_proxy_url,
            timeout,
            headers=headers,
        )
    except Exception as exc:
        try:
            status_code, final_url, latency_ms = _probe_url_with_urllib(
                probe_url,
                runtime_proxy_url,
                timeout,
                headers=headers,
            )
        except URLError as fallback_exc:
            raise _format_probe_error(
                f"Failed to reach {target_label}",
                fallback_exc.reason if getattr(fallback_exc, "reason", None) else fallback_exc,
            ) from fallback_exc
        except Exception as fallback_exc:
            raise _format_probe_error(f"Failed to reach {target_label}", fallback_exc) from fallback_exc

    hostname = (urlsplit(final_url).hostname or "").lower()
    if not any(
        hostname == expected_host or hostname.endswith(expected_host)
        for expected_host in expected_hosts
    ):
        raise RuntimeError(
            f"Unexpected response while probing {target_label}: {hostname or final_url}"
        )

    return {
        "proxy": mask_proxy_url(proxy_url),
        "status_code": int(status_code),
        "final_url": final_url,
        "latency_ms": latency_ms,
    }
