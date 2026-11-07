"""Android Pixel 10 Pro device simulation service."""

import json
import random
import string
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

import config

PIXEL_10_PRO_SPECS = {
    "width": 412,
    "height": 915,
    "device_width": 1080,
    "device_height": 2400,
    "pixel_ratio": 2.625,
    "color_depth": 24,
    "webgl_vendor": "Qualcomm",
    "webgl_renderer": "Adreno (TM) 750",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 120,
    "max_touch_points": 5,
    "device_memory": 12,
    "hardware_concurrency": 8,
}

PIXEL_10_PRO_XL_SPECS = {
    "width": 412,
    "height": 919,
    "device_width": 1344,
    "device_height": 2992,
    "pixel_ratio": 3.0,
    "color_depth": 24,
    "webgl_vendor": "Qualcomm",
    "webgl_renderer": "Adreno (TM) 750",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 115,
    "max_touch_points": 5,
    "device_memory": 16,
    "hardware_concurrency": 8,
}

PIXEL_10_PRO_FOLD_SPECS = {
    "width": 360,
    "height": 808,
    "device_width": 1080,
    "device_height": 2424,
    "pixel_ratio": 3.0,
    "color_depth": 24,
    "webgl_vendor": "Qualcomm",
    "webgl_renderer": "Adreno (TM) 750",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 115,
    "max_touch_points": 5,
    "device_memory": 16,
    "hardware_concurrency": 8,
}

PIXEL_9_PRO_SPECS = {
    "width": 412,
    "height": 919,
    "device_width": 1280,
    "device_height": 2856,
    "pixel_ratio": 3.0,
    "color_depth": 24,
    "webgl_vendor": "ARM",
    "webgl_renderer": "Mali-G715-Immortalis MP7",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 115,
    "max_touch_points": 5,
    "device_memory": 16,
    "hardware_concurrency": 8,
}

PIXEL_9_PRO_XL_SPECS = {
    "width": 412,
    "height": 919,
    "device_width": 1344,
    "device_height": 2992,
    "pixel_ratio": 3.0,
    "color_depth": 24,
    "webgl_vendor": "ARM",
    "webgl_renderer": "Mali-G715-Immortalis MP7",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 115,
    "max_touch_points": 5,
    "device_memory": 16,
    "hardware_concurrency": 8,
}

PIXEL_9_PRO_FOLD_SPECS = {
    "width": 360,
    "height": 808,
    "device_width": 1080,
    "device_height": 2424,
    "pixel_ratio": 3.0,
    "color_depth": 24,
    "webgl_vendor": "ARM",
    "webgl_renderer": "Mali-G715-Immortalis MP7",
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,
    "rtt": 115,
    "max_touch_points": 5,
    "device_memory": 16,
    "hardware_concurrency": 8,
}

DEVICE_SPECS_BY_PROFILE: dict[str, dict] = {
    "pixel_10_pro": PIXEL_10_PRO_SPECS,
    "pixel_10_pro_xl": PIXEL_10_PRO_XL_SPECS,
    "pixel_10_pro_fold": PIXEL_10_PRO_FOLD_SPECS,
    "pixel_9_pro": PIXEL_9_PRO_SPECS,
    "pixel_9_pro_xl": PIXEL_9_PRO_XL_SPECS,
    "pixel_9_pro_fold": PIXEL_9_PRO_FOLD_SPECS,
}

DEVICE_BUILDS_BY_PROFILE: dict[str, list[str]] = {
    "pixel_10_pro": [
        "AP4A.250405.002",
        "AP4A.250305.001",
        "AP4A.250205.004",
        "AP3A.250105.002",
        "AP3A.241205.015",
    ],
    "pixel_10_pro_xl": [
        "AP4A.250405.003",
        "AP4A.250305.002",
        "AP4A.250205.005",
        "AP3A.250105.003",
        "AP3A.241205.016",
    ],
    "pixel_10_pro_fold": [
        "AP4A.250405.004",
        "AP4A.250305.003",
        "AP4A.250205.006",
        "AP3A.250105.004",
        "AP3A.241205.017",
    ],
    "pixel_9_pro": [
        "AP4A.250405.005",
        "AP4A.250305.004",
        "AP4A.250205.007",
        "AP3A.250105.005",
        "AP3A.241205.018",
    ],
    "pixel_9_pro_xl": [
        "AP4A.250405.006",
        "AP4A.250305.005",
        "AP4A.250205.008",
        "AP3A.250105.006",
        "AP3A.241205.019",
    ],
    "pixel_9_pro_fold": [
        "AP4A.250405.007",
        "AP4A.250305.006",
        "AP4A.250205.009",
        "AP3A.250105.007",
        "AP3A.241205.020",
    ],
}

DEVICE_SPECS: dict = DEVICE_SPECS_BY_PROFILE.get(
    config.DEVICE_PROFILE_NAME, PIXEL_10_PRO_SPECS
)


def _resolve_profile_name(profile_name: str | None) -> str:
    """Return *profile_name* if it is a known preset, else the active default."""
    if profile_name and profile_name in config.DEVICE_PRESETS:
        return profile_name
    return config.DEVICE_PROFILE_NAME


def get_specs_for_profile(profile_name: str | None) -> dict:
    """Return the screen/GPU/etc spec dict for *profile_name*."""
    resolved = _resolve_profile_name(profile_name)
    return DEVICE_SPECS_BY_PROFILE.get(resolved, PIXEL_10_PRO_SPECS)


def luhn_checksum(number: str) -> int:
    """Return the Luhn check digit for a numeric string."""
    digits = [int(digit) for digit in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for digit in even_digits:
        total += sum(divmod(digit * 2, 10))
    return total % 10


def generate_imei() -> str:
    """Generate a syntactically valid IMEI (15 digits, Luhn-valid)."""
    tac = random.choice(["35847631", "35900012", "35250011", "86893003"])
    serial = "".join(random.choices(string.digits, k=15 - len(tac) - 1))
    partial = tac + serial
    check_digit = (10 - luhn_checksum(partial + "0")) % 10
    return partial + str(check_digit)


def generate_android_id() -> str:
    """Generate a 16-character hex Android ID."""
    return "".join(random.choices("0123456789abcdef", k=16))


def generate_device_fingerprint(model: str, build_id: str, android: str) -> str:
    """Return a realistic Android build fingerprint."""
    model_key = model.lower().replace(" ", "_")
    return (
        f"google/{model_key}/{model_key}:{android}/"
        f"{build_id}/eng.{random.randint(10000000, 99999999)}:user/release-keys"
    )


def random_chrome_patch() -> str:
    """Return installed Chrome version with small patch variation."""
    actual = config.CHROME_VERSION
    parts = actual.split(".")
    if len(parts) == 4:
        parts[3] = str(int(parts[3]) + random.randint(-5, 5))
        return ".".join(parts)
    return actual


def random_build_id(profile_name: str | None = None) -> str:
    """Pick a realistic BUILD_ID from the pool that matches the active device."""
    resolved = _resolve_profile_name(profile_name)
    builds = DEVICE_BUILDS_BY_PROFILE.get(
        resolved,
        DEVICE_BUILDS_BY_PROFILE["pixel_10_pro"],
    )
    return random.choice(builds)


def _safe_float(value, default: float) -> float:
    """Return a float value or the provided fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int) -> int:
    """Return an int value or the provided fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_emulation_settings(
    network_identity: Mapping[str, str] | None = None,
) -> dict[str, str | float | int]:
    """Return timezone/GPS settings, preferring the active proxy identity."""
    timezone_id = config.EMULATION_TIMEZONE_ID
    latitude = config.EMULATION_GEO_LATITUDE
    longitude = config.EMULATION_GEO_LONGITUDE
    accuracy = config.EMULATION_GEO_ACCURACY

    if network_identity:
        timezone_id = str(network_identity.get("timezone") or timezone_id)
        latitude = _safe_float(network_identity.get("latitude"), latitude)
        longitude = _safe_float(network_identity.get("longitude"), longitude)

    return {
        "timezone_id": timezone_id,
        "geolocation_latitude": latitude,
        "geolocation_longitude": longitude,
        "geolocation_accuracy": _safe_int(accuracy, config.EMULATION_GEO_ACCURACY),
    }


@dataclass
class DeviceProfile:
    imei: str
    android_id: str
    device_fingerprint: str
    user_agent: str
    chrome_version: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    profile_name: str = config.DEVICE_PROFILE_NAME
    model: str = config.DEVICE_MODEL
    brand: str = config.DEVICE_BRAND
    manufacturer: str = config.DEVICE_MANUFACTURER
    android_version: str = config.ANDROID_VERSION
    android_sdk: str = config.ANDROID_SDK
    build_id: str = config.BUILD_ID
    accept_language: str = config.DEVICE_ACCEPT_LANGUAGE
    locale: str = config.DEVICE_LOCALE
    timezone_id: str = config.EMULATION_TIMEZONE_ID
    geolocation_latitude: float = config.EMULATION_GEO_LATITUDE
    geolocation_longitude: float = config.EMULATION_GEO_LONGITUDE
    geolocation_accuracy: int = config.EMULATION_GEO_ACCURACY
    battery_level: float = field(default_factory=lambda: round(random.uniform(0.73, 0.96), 2))
    canvas_noise_blue: int = field(default_factory=lambda: random.randint(1, 3))

    def user_agent_brands(self) -> list[dict[str, str]]:
        """Return low-entropy UA brands for User-Agent Client Hints."""
        major = str(config.CHROME_MAJOR_VERSION)
        return [
            {"brand": "Chromium", "version": major},
            {"brand": "Google Chrome", "version": major},
            {"brand": "Not:A-Brand", "version": "24"},
        ]

    def user_agent_full_version_list(self) -> list[dict[str, str]]:
        """Return full version entries for User-Agent Client Hints."""
        return [
            {"brand": "Chromium", "version": self.chrome_version},
            {"brand": "Google Chrome", "version": self.chrome_version},
            {"brand": "Not:A-Brand", "version": "24.0.0.0"},
        ]

    def user_agent_metadata(self) -> dict[str, object]:
        """Return Chrome client-hints metadata for CDP override."""
        return {
            "brands": self.user_agent_brands(),
            "fullVersionList": self.user_agent_full_version_list(),
            "mobile": True,
            "platform": "Android",
            "platformVersion": f"{self.android_version}.0.0",
            "architecture": "",
            "bitness": "64",
            "model": self.model,
            "wow64": False,
        }

    def user_agent_high_entropy_values(self) -> dict[str, object]:
        """Return the JS payload exposed via navigator.userAgentData."""
        payload = dict(self.user_agent_metadata())
        payload["uaFullVersion"] = self.chrome_version
        return payload

    def client_hints_headers(self) -> dict:
        """Return User-Agent Client Hints headers for this device."""
        brands = ", ".join(
            f'"{item["brand"]}";v="{item["version"]}"'
            for item in self.user_agent_brands()
        )
        full_version_list = ", ".join(
            f'"{item["brand"]}";v="{item["version"]}"'
            for item in self.user_agent_full_version_list()
        )
        return {
            "Sec-CH-UA": brands,
            "Sec-CH-UA-Mobile": "?1",
            "Sec-CH-UA-Platform": '"Android"',
            "Sec-CH-UA-Platform-Version": f'"{self.android_version}.0.0"',
            "Sec-CH-UA-Model": f'"{self.model}"',
            "Sec-CH-UA-Full-Version": f'"{self.chrome_version}"',
            "Sec-CH-UA-Full-Version-List": full_version_list,
            "Sec-CH-UA-Arch": '""',
            "Sec-CH-UA-Bitness": '"64"',
        }

    def as_headers(self) -> dict:
        """Return extra HTTP headers that identify this device."""
        headers = {
            "Accept-Language": self.accept_language,
        }
        headers.update(self.client_hints_headers())
        return headers

    def navigator_overrides_js(self) -> str:
        """Return JavaScript to inject navigator/screen spoofs via CDP."""
        specs = get_specs_for_profile(self.profile_name)
        brands_json = json.dumps(self.user_agent_brands())
        metadata_json = json.dumps(self.user_agent_high_entropy_values())
        locale_languages_json = json.dumps([self.locale, "en"])
        media_devices_json = json.dumps([
            {"deviceId": "default", "groupId": "g1", "kind": "audioinput", "label": ""},
            {"deviceId": "cam0", "groupId": "g2", "kind": "videoinput", "label": ""},
            {"deviceId": "cam1", "groupId": "g3", "kind": "videoinput", "label": ""},
            {"deviceId": "default", "groupId": "g4", "kind": "audiooutput", "label": ""},
        ])
        media_constraints_json = json.dumps({
            "deviceId": True,
            "facingMode": True,
            "frameRate": True,
            "height": True,
            "width": True,
        })
        return f"""
        (() => {{
            const makeFnsNative = (fns) => {{
                const oldCall = Function.prototype.call;
                function call() {{
                    return oldCall.apply(this, arguments);
                }}
                Function.prototype.call = call;
                const nativeToStringFunctionString = Error.toString().replace(
                    /Error/g,
                    "toString"
                );
                const oldToString = Function.prototype.toString;
                function functionToString() {{
                    for (const fn of fns) {{
                        if (this === fn.ref) {{
                            return `function ${{fn.name}}() {{ [native code] }}`;
                        }}
                    }}
                    if (this === functionToString) {{
                        return nativeToStringFunctionString;
                    }}
                    return oldCall.call(oldToString, this);
                }}
                Object.defineProperty(Function.prototype, "toString", {{
                    value: functionToString,
                    configurable: true,
                    enumerable: false,
                    writable: true,
                }});
            }};

            const fnsToMask = [];

            const defineGetter = (target, key, value) => {{
                try {{
                    const getter = () => value;
                    fnsToMask.push({{ ref: getter, name: `get ${{key}}` }});
                    Object.defineProperty(target, key, {{
                        get: getter,
                        configurable: true,
                    }});
                }} catch (error) {{}}
            }};

            const defineValue = (target, key, value) => {{
                try {{
                    if (typeof value === 'function') {{
                        fnsToMask.push({{ ref: value, name: key }});
                    }}
                    Object.defineProperty(target, key, {{
                        value,
                        configurable: true,
                    }});
                }} catch (error) {{}}
            }};

            // Jadwalkan penyamaran fungsi agar tereksekusi segera
            setTimeout(() => makeFnsNative(fnsToMask), 0);

            const lowEntropyUaData = {{
                brands: {brands_json},
                mobile: true,
                platform: "Android",
            }};
            const highEntropyUaData = {metadata_json};

            defineGetter(navigator, "platform", {json.dumps(specs["platform"])});
            defineGetter(navigator, "vendor", {json.dumps(specs["vendor"])});
            defineGetter(navigator, "maxTouchPoints", {specs["max_touch_points"]});
            defineGetter(navigator, "hardwareConcurrency", {specs["hardware_concurrency"]});
            defineGetter(navigator, "deviceMemory", {specs["device_memory"]});
            defineGetter(navigator, "language", {json.dumps(self.locale)});
            defineGetter(navigator, "languages", {locale_languages_json});
            defineGetter(window, "devicePixelRatio", {specs["pixel_ratio"]});

            defineGetter(navigator, "userAgentData", {{
                ...lowEntropyUaData,
                getHighEntropyValues: async (hints) => {{
                    if (!Array.isArray(hints) || !hints.length) {{
                        return {{ ...highEntropyUaData }};
                    }}
                    return hints.reduce((acc, hint) => {{
                        if (hint in highEntropyUaData) {{
                            acc[hint] = highEntropyUaData[hint];
                        }}
                        return acc;
                    }}, {{}});
                }},
                toJSON: () => ({{ ...lowEntropyUaData }}),
            }});

            defineGetter(screen, "orientation", {{
                type: "portrait-primary",
                angle: 0,
                addEventListener: () => {{}},
                removeEventListener: () => {{}},
                dispatchEvent: () => true,
                onchange: null,
                lock: () => Promise.resolve(),
                unlock: () => {{}},
            }});

            defineValue(navigator, "vibrate", () => true);

            const mediaDevices = navigator.mediaDevices || {{}};
            mediaDevices.enumerateDevices = () => Promise.resolve({media_devices_json});
            mediaDevices.getSupportedConstraints = () => ({media_constraints_json});
            if (typeof mediaDevices.getUserMedia !== "function") {{
                mediaDevices.getUserMedia = () =>
                    Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
            }}
            defineGetter(navigator, "mediaDevices", mediaDevices);

            const connection = navigator.connection || {{}};
            defineGetter(connection, "effectiveType", {json.dumps(specs["effective_type"])});
            defineGetter(connection, "type", "cellular");
            defineGetter(connection, "downlink", {specs["downlink"]});
            defineGetter(connection, "rtt", {specs["rtt"]});
            defineGetter(connection, "saveData", false);
            defineGetter(navigator, "connection", connection);

            defineGetter(screen, "width", {specs["width"]});
            defineGetter(screen, "height", {specs["height"]});
            defineGetter(screen, "availWidth", {specs["width"]});
            defineGetter(screen, "availHeight", {specs["height"]});
            defineGetter(screen, "colorDepth", {specs["color_depth"]});
            defineGetter(screen, "pixelDepth", {specs["color_depth"]});

            const webglDebugInfo = {{
                UNMASKED_VENDOR_WEBGL: 0x9245,
                UNMASKED_RENDERER_WEBGL: 0x9246,
            }};
            const patchWebGLContext = (ContextClass) => {{
                if (typeof ContextClass === "undefined" || !ContextClass.prototype) {{
                    return;
                }}

                const getParameterOrig = ContextClass.prototype.getParameter;
                const getExtensionOrig = ContextClass.prototype.getExtension;

                ContextClass.prototype.getParameter = function(param) {{
                    if (param === 0x9245) return {json.dumps(specs["webgl_vendor"])};
                    if (param === 0x9246) return {json.dumps(specs["webgl_renderer"])};
                    return getParameterOrig.call(this, param);
                }};

                ContextClass.prototype.getExtension = function(name) {{
                    if (name === "WEBGL_debug_renderer_info") {{
                        return webglDebugInfo;
                    }}
                    return getExtensionOrig ? getExtensionOrig.call(this, name) : null;
                }};
            }};

            patchWebGLContext(
                typeof WebGLRenderingContext === "undefined" ? undefined : WebGLRenderingContext
            );
            patchWebGLContext(
                typeof WebGL2RenderingContext === "undefined" ? undefined : WebGL2RenderingContext
            );

            defineGetter(navigator, "webdriver", undefined);

            const batteryManager = {{
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: {self.battery_level:.2f},
                addEventListener: () => {{}},
                removeEventListener: () => {{}},
                dispatchEvent: () => true,
                onchargingchange: null,
                onchargingtimechange: null,
                ondischargingtimechange: null,
                onlevelchange: null,
            }};
            defineValue(navigator, "getBattery", () => Promise.resolve(batteryManager));

            const origDateTimeFormat = Intl.DateTimeFormat;
            Intl.DateTimeFormat = function(locale, options) {{
                const nextOptions = {{ ...(options || {{}}) }};
                nextOptions.timeZone = nextOptions.timeZone || {json.dumps(self.timezone_id)};
                return new origDateTimeFormat(locale, nextOptions);
            }};
            Intl.DateTimeFormat.prototype = origDateTimeFormat.prototype;
            defineValue(Intl.DateTimeFormat, "supportedLocalesOf", origDateTimeFormat.supportedLocalesOf);

            if (
                typeof CanvasRenderingContext2D !== "undefined" &&
                CanvasRenderingContext2D.prototype.getImageData
            ) {{
                const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
                defineValue(CanvasRenderingContext2D.prototype, "getImageData", function() {{
                    const imageData = origGetImageData.apply(this, arguments);
                    if (imageData && imageData.data && imageData.data.length >= 3) {{
                        imageData.data[2] = Math.min(
                            255,
                            imageData.data[2] + {self.canvas_noise_blue}
                        );
                    }}
                    return imageData;
                }});
            }}

            if (typeof HTMLCanvasElement !== "undefined" && HTMLCanvasElement.prototype.toDataURL) {{
                const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                defineValue(HTMLCanvasElement.prototype, "toDataURL", function() {{
                    const ctx = this.getContext("2d");
                    if (ctx) {{
                        try {{
                            const style = ctx.fillStyle;
                            ctx.fillStyle = "rgba(0,0,{self.canvas_noise_blue},0.01)";
                            ctx.fillRect(0, 0, 1, 1);
                            ctx.fillStyle = style;
                        }} catch (error) {{}}
                    }}
                    return origToDataURL.apply(this, arguments);
                }});
            }}
        }})();
        """

    def summary(self) -> str:
        """Human-readable summary for Telegram messages."""
        return (
            f"📱 <b>Device Profile</b>\n"
            f"Model: {self.model}\n"
            f"Android: {self.android_version}\n"
            f"Build: {self.build_id}\n"
            f"Chrome: {self.chrome_version}\n"
            f"Session: <code>{self.session_id[:8]}…</code>"
        )


def create_device_profile(
    network_identity: Mapping[str, str] | None = None,
    profile_name: str | None = None,
) -> DeviceProfile:
    """Create a fresh Pixel device profile with unique identifiers.

    When *profile_name* is provided and matches a key in
    :data:`config.DEVICE_PRESETS`, the resulting profile uses that preset's
    model / brand / Android version / build pool. Otherwise it falls back to
    the active default selected by the ``DEVICE_PROFILE`` environment variable.
    """
    resolved_profile = _resolve_profile_name(profile_name)
    preset = config.DEVICE_PRESETS.get(resolved_profile, config.DEVICE_PRESETS[config.DEFAULT_DEVICE_PROFILE])

    model = preset["model"]
    brand = preset["brand"]
    manufacturer = preset["manufacturer"]
    android_version = preset["android_version"]
    android_sdk = preset["android_sdk"]
    accept_language = preset.get("accept_language", config.DEVICE_ACCEPT_LANGUAGE)
    locale = preset.get("locale", config.DEVICE_LOCALE)

    build_id = random_build_id(resolved_profile)
    chrome_version = random_chrome_patch()
    template = random.choice(config.USER_AGENT_TEMPLATES)
    user_agent = template.format(
        android=android_version,
        model=model,
        build=build_id,
        chrome=chrome_version,
    )
    fingerprint = generate_device_fingerprint(model, build_id, android_version)
    emulation = resolve_emulation_settings(network_identity)
    return DeviceProfile(
        imei=generate_imei(),
        android_id=generate_android_id(),
        device_fingerprint=fingerprint,
        user_agent=user_agent,
        chrome_version=chrome_version,
        profile_name=resolved_profile,
        model=model,
        brand=brand,
        manufacturer=manufacturer,
        android_version=android_version,
        android_sdk=android_sdk,
        build_id=build_id,
        accept_language=accept_language,
        locale=locale,
        timezone_id=str(emulation["timezone_id"]),
        geolocation_latitude=float(emulation["geolocation_latitude"]),
        geolocation_longitude=float(emulation["geolocation_longitude"]),
        geolocation_accuracy=int(emulation["geolocation_accuracy"]),
    )


__all__ = [
    "DeviceProfile",
    "DEVICE_BUILDS_BY_PROFILE",
    "DEVICE_SPECS",
    "DEVICE_SPECS_BY_PROFILE",
    "PIXEL_9_PRO_FOLD_SPECS",
    "PIXEL_9_PRO_SPECS",
    "PIXEL_9_PRO_XL_SPECS",
    "PIXEL_10_PRO_FOLD_SPECS",
    "PIXEL_10_PRO_SPECS",
    "PIXEL_10_PRO_XL_SPECS",
    "create_device_profile",
    "resolve_emulation_settings",
]
