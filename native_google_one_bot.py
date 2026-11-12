"""Telegram command to start/inspect the separate GitHub Android 17 Google One test.

This module does not authenticate to Google, move Chrome cookies to Android,
change Pixel device identity, or access the customer's password/TOTP.

GITHUB_ACTIONS_TOKEN (optional) is a fine-grained GitHub PAT with Actions write
access to the single pixel2 repository. Never include it in Telegram messages.
"""
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from admin_store import is_admin

LOG = logging.getLogger(__name__)
REPO = "anahilbheidenrhhk12-eng/pixel2"
WORKFLOW = "native-google-one.yml"
BRANCH = "android-test"
WORKFLOW_URL = f"https://github.com/{REPO}/actions/workflows/{WORKFLOW}"
API_BASE = f"https://api.github.com/repos/{REPO}"
_last_start = 0.0


def api_json(path, *, method="GET", token=None, data=None):
    url = API_BASE + path
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "DigiPro-GoogleOne-Test",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=14) as response:
        return (response.status, json.load(response) if response.status != 204 else {})


def latest_native_run():
    path = f"/actions/workflows/{WORKFLOW}/runs?branch={BRANCH}&per_page=1"
    _, result = api_json(path)
    items = result.get("workflow_runs", [])
    if not items:
        return None
    run = items[0]
    return {
        "id": run["id"],
        "status": run.get("status", "unknown"),
        "conclusion": run.get("conclusion"),
        "url": run.get("html_url"),
    }


def dispatch_native_test(token):
    status, _ = api_json(
        f"/actions/workflows/{WORKFLOW}/dispatches",
        method="POST",
        token=token,
        data={"ref": BRANCH},
    )
    return status == 204


def format_result(run):
    if not run:
        return "ما فمّاش اختبار Google One مسجّل في GitHub."
    label = {
        "queued": "في قائمة الانتظار",
        "in_progress": "قيد التنفيذ",
        "completed": "مكتمل",
        "waiting": "في الانتظار",
    }.get(run["status"], run["status"])
    conclusion = run["conclusion"]
    if conclusion == "success":
        label += " — نجحت خطوات CI (موش إثبات عرض Google One)"
    elif conclusion:
        label += f" — {conclusion}"
    return f"🧪 آخر اختبار Android / Google One\nالحالة: {label}\n{run['url'] or WORKFLOW_URL}"


async def native_google_one_command(update, context):
    """Read existing CI status, or dispatch new test for configured admins."""
    if not update.effective_chat or update.effective_chat.type != "private":
        await update.effective_message.reply_text("استعمل هذا الأمر في الخاص.")
        return
    mode = (context.args or ["status"])[0].lower()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("فتح اختبارات GitHub", url=WORKFLOW_URL)]
    ])
    if mode in ("status", "حالة"):
        try:
            run = await asyncio.to_thread(latest_native_run)
            await update.effective_message.reply_text(format_result(run), reply_markup=keyboard)
        except Exception as exc:
            LOG.warning("Google One native status unavailable: %s", type(exc).__name__)
            await update.effective_message.reply_text("تعذّر قراءة نتيجة GitHub حاليًا.", reply_markup=keyboard)
        return

    token = (os.environ.get("GITHUB_ACTIONS_TOKEN") or "").strip()
    # Never enable spending GitHub Actions minutes for arbitrary customers.
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "🧪 عرض آخر اختبار: /test_google_one status\n"
            "بدء اختبار جديد متاح فقط للأدمن المعرّف في ADMIN_TELEGRAM_IDS.",
            reply_markup=keyboard,
        )
        return
    if not token:
        await update.effective_message.reply_text(
            "⚙️ الأمر موجود، لكن بدء تجربة جديدة يحتاج GITHUB_ACTIONS_TOKEN "
            "في Railway → PIXEL → Variables (صلاحية GitHub Actions: Write).\n"
            "تقدر تشوف آخر اختبار بالأمر: /test_google_one status\n\n"
            "الاختبار الحالي يفحص Android 17 ووجود Google One، "
            "ولا ينقل جلسة Chrome إلى تطبيق Android.",
            reply_markup=keyboard,
        )
        return
    global _last_start
    now = time.monotonic()
    if now - _last_start < 90:
        await update.effective_message.reply_text(
            "اختبار جديد أُرسل منذ قليل. اكتب /test_google_one status للتحقق.",
            reply_markup=keyboard,
        )
        return
    try:
        if not await asyncio.to_thread(dispatch_native_test, token):
            raise RuntimeError("Unexpected GitHub response")
        _last_start = now
        await update.effective_message.reply_text(
            "✅ أرسلت تجربة Android 17 + Google One إلى GitHub Actions.\n"
            "تابعها بالأمر /test_google_one status\n"
            "هذه تجربة فحص للتطبيق، لا تسجيل دخول لحساب Google.",
            reply_markup=keyboard,
        )
    except urllib.error.HTTPError as exc:
        LOG.warning("GitHub workflow dispatch returned HTTP %s", exc.code)
        if exc.code in (401, 403):
            detail = "تأكد من صلاحية Actions: Write للمفتاح ومن وصوله إلى المستودع."
        elif exc.code == 404:
            detail = "لم يعثر GitHub على الـWorkflow؛ تحقق من فرع main وandroid-test."
        else:
            detail = "تعذّر تشغيل الاختبار حاليًا."
        await update.effective_message.reply_text(
            f"❌ GitHub رفض البدء (HTTP {exc.code}). {detail}", reply_markup=keyboard,
        )
    except Exception as exc:
        LOG.warning("GitHub dispatch failed: %s", type(exc).__name__)
        await update.effective_message.reply_text(
            "❌ تعذّر الاتصال بـGitHub لتشغيل الاختبار.", reply_markup=keyboard,
        )
