"""Reusable UI helpers for Telegram bot messages, keyboards, and i18n."""

from __future__ import annotations

import html
import logging
import os
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update

import config

logger = logging.getLogger(__name__)

DEFAULT_LANG = "en"
SUPPORTED_LANGS = {"en", "id"}

MENU_ROWS: list[tuple[str, ...]] = [
    ("menu_login", "menu_check_offer"),
    ("menu_status", "menu_get_link"),
    ("menu_proxy", "menu_ip"),
    ("menu_rotate_proxy", "menu_disable_proxy"),
    ("menu_device",),
    ("menu_lang_en", "menu_lang_id"),
    ("menu_home", "menu_logout"),
]

INLINE_PANEL_HEADER_KEY = "menu_panel_header"
INLINE_PANEL_FOOTER_KEY = "menu_panel_refresh"

I18N = {
    "en": {
        "start_title": "🚀 Pixel Google One Assistant",
        "start_header_caption": "🚀 Pixel Control Panel • Created by Dziel",
        "start_subtitle": "⌬ Pixel Control Panel • Google One • Modern Offer Deck",
        "start_body": (
            "A modern Telegram control deck for secure Google sign-in, Pixel "
            "device simulation, proxy-aware networking, and live Gemini offer checks."
        ),
        "start_deck_intro": "Use the control deck below to launch login, diagnostics, proxy tools, and offer checks in one tap.",
        "start_tip": "💡 Gmail and Google Workspace accounts are supported.",
        "start_privacy": "🔒 Credentials stay in memory only for the active session.",
        "creator_line": "Created by Dziel",
        "quick_actions_title": (
            "<b>⌬ Pixel Control Panel</b>\n"
            "<code>Pixel • Google One • Modern Offer Deck</code>\n"
            "<i>Created by Dziel</i>\n\n"
            "Tap a module below to continue."
        ),
        "section_quick_start": "Quick Start",
        "section_commands": "Core Commands",
        "section_language": "Language",
        "section_tools": "Modules",
        "section_session": "Session",
        "section_device": "Device Profile",
        "section_proxy": "Proxy Mode",
        "section_flow": "Recommended Flow",
        "section_power": "Power Tools",
        "start_flow_1": "Launch a secure login session with /login",
        "start_flow_2": "Review proxy identity or switch to direct mode",
        "start_flow_3": "Run /check_offer and inspect the live result",
        "command_login_desc": "Open a secure login session",
        "command_witai_desc": "Save the Wit.ai token for audio captcha solving",
        "command_check_offer_desc": "Run the Gemini offer scanner",
        "command_doctor_desc": "Run the first-time setup self-check",
        "command_get_link_desc": "Show the latest captured offer link",
        "command_status_desc": "View account, proxy, and device status",
        "command_proxy_desc": "Inspect the active proxy and pool",
        "command_ip_desc": "Check the current public IP and geo",
        "command_rotate_proxy_desc": "Switch to another proxy from the pool",
        "command_disable_proxy_desc": "Use your local/direct IP for this session",
        "command_device_desc": "Pick which Pixel device the bot simulates",
        "command_lang_en_desc": "Switch the interface to English",
        "command_lang_id_desc": "Switch the interface to Indonesian",
        "command_logout_desc": "Clear the active session and browser state",
        "offer_no_credentials": "⚠️ No credentials found. Run /login first.",
        "offer_cooldown_wait": "⏳ Please wait {mins}m {secs}s before checking again.",
        "offer_capacity_busy": "🔄 The system is currently at maximum capacity. Please try again in a minute.",
        "offer_starting_secure_check": (
            "⏳ Starting secure check...\n"
            "Launching Pixel device simulation and signing in.\n"
            "Chrome should appear within 10-20 seconds.\n"
            "The full check can still take 1-3 minutes if Google asks for extra verification."
        ),
        "offer_opening_visible_browser": (
            "🔓 Authenticated proxy detected.\n"
            "Opening Chrome in visible mode immediately so this session does not waste time on a hidden retry."
        ),
        "offer_retry_note_fresh": "minting a fresh Pixel device profile and trying again.",
        "offer_retry_note_same": "reusing the same session device and trying again.",
        "offer_retry_attempt": "🔄 Retry {attempt}/{max_attempts}: {note}",
        "offer_proxy_precheck_failed_rotate": (
            "⚠️ Proxy precheck failed before opening Chrome. Rotating proxy..."
        ),
        "offer_proxy_precheck_failed_error": (
            "Proxy precheck failed before opening Chrome: {error}"
        ),
        "offer_manual_verification_reopen": (
            "🔐 Google requested manual verification.\n"
            "Reopening Chrome in visible mode with the same session device..."
        ),
        "offer_auto_totp_rejected": (
            "❌ Auto-generated TOTP code was rejected. Please check your TOTP secret key."
        ),
        "offer_login_success_checking": (
            "✅ Login successful ({attempt}/{max_attempts}).\n"
            "Checking Gemini Pro offer now..."
        ),
        "offer_auto_totp_error": (
            "❌ Auto-TOTP error: {error}\n"
            "Please check your TOTP secret key."
        ),
        "offer_2fa_required": (
            "🔐 *Two-Factor Authentication Required*\n\n"
            "Please send your 6-digit authenticator code *here in Telegram only*.\n"
            "Do not type that code in the Chrome window."
        ),
        "offer_manual_required": (
            "🔐 Manual verification required.\n\n"
            "Google requested: {challenge_type}\n"
            "Complete that step in the Chrome window that just opened.\n"
            "After the browser leaves the Google sign-in page, send `done` here.\n"
            "Send /cancel to stop this check."
        ),
        "offer_proxy_transport_rotating": "⚠️ Proxy transport issue detected. Rotating proxy...",
        "offer_runtime_network_rotating": "⚠️ Runtime network issue detected. Rotating proxy...",
        "offer_not_found_retrying": "⏳ Offer not found yet. Retrying in {delay} seconds...",
        "offer_retry_device_fresh": "a fresh Pixel device profile",
        "offer_retry_device_same": "the same session device",
        "offer_starting_retry": (
            "🔄 Starting retry {next_attempt}/{max_attempts}: "
            "preparing {device_note} and signing in again."
        ),
        "offer_automation_error": "❌ <b>Automation Error:</b> {error}",
        "offer_unexpected_error": "❌ An unexpected error occurred: {error}",
        "offer_session_expired": "⚠️ Session expired. Please run /check_offer again.",
        "offer_verification_session_closed": (
            "⚠️ The Chrome verification session has already closed or crashed.\n"
            "Please run /check_offer again."
        ),
        "offer_invalid_code": "⚠️ Invalid code. Please enter a 6-digit number.",
        "offer_verifying_code": "🔄 Verifying code…",
        "offer_code_rejected": (
            "❌ Code rejected or expired.\n"
            "Please send a fresh 6-digit authenticator code.\n"
            "Send /cancel to stop this check."
        ),
        "offer_generic_error": "❌ Error: {error}",
        "offer_verification_window_closed": (
            "⚠️ The Chrome verification window has already closed or crashed.\n"
            "Please run /check_offer again."
        ),
        "offer_checking_chrome_window": "🔄 Checking the Chrome window…",
        "offer_2fa_required_after_manual": (
            "🔐 *Two-Factor Authentication Required*\n\n"
            "Google has moved to the authenticator-code step.\n"
            "Please send your 6-digit code *here in Telegram only*.\n"
            "Do not type that code in the Chrome window."
        ),
        "offer_google_waiting_verification": (
            "⏳ Google is still waiting for verification in Chrome.\n"
            "Pending step: {challenge_type}\n"
            "Finish it there first, then send `done` again.\n"
            "Send /cancel to stop this check."
        ),
        "offer_verification_completed_checking": (
            "✅ Verification completed. Checking Gemini Pro offer now..."
        ),
        "offer_verification_cancelled": "❌ Verification cancelled.",
        "offer_verification_timed_out": (
            "⏰ Verification timed out. Please run /check_offer again."
        ),
        "offer_found_html": (
            "🎉 <b>Gemini Pro Offer Found!</b>\n\n"
            "Use the link below to activate your 12-month free Gemini Pro:\n\n"
            "🔗 {offer_link}\n\n"
            "You can run /get_link anytime to retrieve this link again."
        ),
        "offer_found_plain": (
            "🎉 Gemini Pro Offer Found!\n\n"
            "🔗 {offer_link}\n\n"
            "You can run /get_link anytime to retrieve this link again."
        ),
        "offer_not_found_now": (
            "😔 No active Gemini Pro offer was detected on your Google One account at this time.\n\n"
            "The offer may not be available for your account region or may have already been activated. "
            "You can try again later.{diagnostic_note}{artifact_note}"
        ),
        "offer_embedded_trial_detected": (
            "🧪 A Google One trial offer was detected for this account, but AutoPixel did not capture the "
            "checkout link automatically.\n\n"
            "This usually means the offer is embedded behind a Google button flow instead of a direct claim URL."
            "{diagnostic_note}{artifact_note}"
        ),
        "offer_not_found_after_attempts": (
            "❌ No Gemini Pro offer found after {attempts} attempts.\n\n"
            "Possible reasons:\n"
            "• Your account region is not eligible\n"
            "• An active Gemini subscription already exists\n"
            "• Family group eligibility has already been used\n"
            "• New-account risk controls are in effect"
            "{diagnostic_note}{artifact_note}"
        ),
        "offer_diagnosis_label": "Diagnosis",
        "offer_debug_saved": "Debug artifacts saved:",
        "offer_debug_screenshot": "Screenshot: {path}",
        "offer_debug_html": "HTML: {path}",
        "offer_diag_ai_mixed": (
            "Google One shows AI-related products, but the promo state is mixed "
            "and needs manual review."
        ),
        "offer_diag_paid_no_free": (
            "Google One shows regular paid Google AI Pro plans for this account, "
            "but no free promo claim link was present."
        ),
        "offer_diag_normal_plan_no_promo": (
            "Google One loaded your normal account plan page, but no promo card was present."
        ),
        "offer_diag_embedded_ai_trial": (
            "Google One shows an embedded Google AI trial offer on the plans page, "
            "but AutoPixel did not capture the checkout link automatically."
        ),
        "offer_diag_embedded_trial": (
            "Google One shows an embedded free-trial offer on the plans page, "
            "but AutoPixel did not capture the checkout link automatically."
        ),
        "lang_set": "🌐 Language set to English.",
        "login_prompt_email": (
            "📧 [·] Login\n"
            "Send your Google email address.\n"
            "Supported: Gmail and Google Workspace."
        ),
        "login_invalid_email": (
            "⚠️ [·] Invalid Email\n"
            "Please enter a valid email address.\n"
            "Example: user@gmail.com or user@company.com."
        ),
        "login_password_prompt": (
            "✅ [·] Email Accepted\n"
            "<code>{email}</code>\n\n"
            "🔒 Send your password now.\n"
            "Optional format: <code>password|totp_secret</code>"
        ),
        "login_saved_title": "✅ [·] Session Ready",
        "login_saved_body": "Credentials saved successfully. A fresh Pixel device profile is ready for this session.",
        "login_saved_totp": "🔑 TOTP secret detected. Auto-2FA is available for this session.",
        "login_saved_next": "Next step: run <code>/check_offer</code>",
        "login_cancelled": "❌ Login flow cancelled.",
        "wit_ai_prompt": (
            "🧠 Send your Wit.ai server token now.\n\n"
            "Tip: you can also send `/witai YOUR_TOKEN` directly.\n"
            "Send `clear` to remove the saved token.\n"
            "Send /cancel to stop."
        ),
        "wit_ai_invalid": "⚠️ The Wit.ai token looks empty or too short. Please try again.",
        "wit_ai_saved": (
            "✅ Wit.ai token saved.\n\n"
            "Masked token: <code>{token}</code>\n"
            "Audio captcha auto-solve is now enabled.\n"
            "Saved to: <code>{path}</code>"
        ),
        "wit_ai_cleared": (
            "🗑️ Wit.ai token cleared.\n\n"
            "Audio captcha solving will fall back to manual verification.\n"
            "Updated file: <code>{path}</code>"
        ),
        "wit_ai_cancelled": "❌ Wit.ai token input cancelled.",
        "logout_success": "🗑️ Session, credentials, and temporary browser state were cleared.",
        "logout_none": "ℹ️ No active session to clear.",
        "doctor_running": "🩺 Running the setup self-check...",
        "doctor_title": "<b>🩺 Setup Doctor</b>",
        "doctor_summary_ok": "✅ Your baseline setup looks ready for a new user.",
        "doctor_summary_warn": "⚠️ The bot can run, but there are a few setup items worth fixing first.",
        "doctor_summary_fail": "❌ The bot is not ready for a clean first-time user setup yet.",
        "doctor_token_ok": "✅ Telegram bot token is loaded.",
        "doctor_token_fail": "❌ Telegram bot token is missing. Set <code>TELEGRAM_BOT_TOKEN</code> in .env first.",
        "doctor_chrome_ok": "✅ Chrome version detected: <code>{version}</code> (major <code>{major}</code>).",
        "doctor_chrome_fail": "❌ Chrome could not be detected correctly. Install Chrome or set <code>CHROME_BIN</code> / <code>CHROME_VERSION</code>.",
        "doctor_env_ok": "✅ .env file detected at <code>{path}</code>.",
        "doctor_env_warn": "⚠️ No local .env file was found at <code>{path}</code>. System environment variables may still work.",
        "doctor_header_local_ok": "✅ Header media file found: <code>{value}</code>.",
        "doctor_header_remote_ok": "✅ Header media is configured as a remote URL: <code>{value}</code>.",
        "doctor_header_disabled": "⚠️ Header media is disabled or empty.",
        "doctor_header_warn": "⚠️ Header media path/URL looks invalid: <code>{value}</code>.",
        "doctor_proxy_disabled": "✅ Proxy mode is disabled by default. New users will start in direct mode.",
        "doctor_proxy_missing": "⚠️ Proxy mode is enabled, but the proxy file is missing: <code>{path}</code>.",
        "doctor_proxy_unreadable": "⚠️ Proxy path exists but is not a readable file: <code>{path}</code>.",
        "doctor_proxy_empty": "⚠️ Proxy file exists but no valid proxy entries were found: <code>{path}</code>.",
        "doctor_proxy_warn_invalid": "⚠️ Proxy pool loaded with <code>{valid}</code> valid entries and <code>{invalid}</code> invalid entries.",
        "doctor_proxy_ok": "✅ Proxy pool looks good: <code>{count}</code> valid entries in <code>{path}</code>.",
        "doctor_driver_auto": "✅ CHROMEDRIVER_PATH is not pinned. Automatic driver resolution is enabled.",
        "doctor_driver_ok": "✅ CHROMEDRIVER_PATH exists: <code>{path}</code>.",
        "doctor_driver_warn": "⚠️ CHROMEDRIVER_PATH is set but the file does not exist: <code>{path}</code>.",
        "doctor_next_steps": "Next step: run <code>/login</code> for a real session, or fix any warning above before sharing the repo with new users.",
        "status_no_session": "ℹ️ No active session found. Run /login to get started.",
        "status_title": "📊 Session Overview",
        "status_account": "👤 Account",
        "status_creds": "🔐 Credentials loaded",
        "status_offer": "🎁 Offer link captured",
        "status_yes": "✅ Yes",
        "status_no": "❌ No",
        "proxy_summary_direct": "direct / local IP",
        "proxy_summary_direct_locked": "direct / local IP (manual override)",
        "proxy_summary_pool": "🧩 Proxy pool: {available}/{total} available",
        "proxy_disabled_set": "⛔ [·] Direct Mode Enabled\nThis session will now use your local/direct IP.",
        "proxy_disabled_already": "⛔ [·] Direct Mode Already Active\nThis session is already using your local/direct IP.",
        "proxy_rotated": "🔄 [·] Proxy Rotated\nNew proxy: <code>{proxy}</code>",
        "proxy_no_pool": "ℹ️ No proxies were loaded from the pool.\nThe bot will continue using a direct connection.",
        "proxy_no_healthy": "⚠️ No healthy alternative proxy is available right now.\nThe bot will continue using a direct connection.",
        "ip_checking": "🔎 Checking current network identity...",
        "ip_check_failed": "⚠️ IP check failed.\n\nReason: {reason}",
        "network_title": "🌍 Connection Identity",
        "ip_emulation_title": "🧪 Active Browser Emulation",
        "ip_emulation_source_route": "Source: current /ip route data",
        "ip_emulation_source_fallback": "Source: fallback .env values",
        "ip_emulation_copy_note": "Copy these lines into .env if you want to pin the current emulation values:",
        "proxy_panel_title": "🌍 Active Proxy Panel",
        "proxy_rotated_title": "🔄 Rotated Proxy Panel",
        "direct_panel_title": "🧷 Direct Network Panel",
        "menu_login": "🚀 Login",
        "menu_check_offer": "🎯 Check Offer",
        "menu_status": "📊 Status",
        "menu_get_link": "🔗 Get Link",
        "menu_proxy": "🌐 Proxy",
        "menu_ip": "🧭 Check IP",
        "menu_rotate_proxy": "🔄 Rotate Proxy",
        "menu_disable_proxy": "⛔ Direct Mode",
        "menu_device": "📱 Pick Device",
        "menu_lang_en": "🇺🇸 English",
        "menu_lang_id": "🇮🇩 Indonesian",
        "menu_home": "🏠 Home",
        "menu_logout": "🗑️ Logout",
        "menu_panel_header": "⌬ PIXEL CONTROL PANEL",
        "menu_panel_refresh": "🪄 Open Dashboard",
        "device_prompt": (
            "📱 <b>Pick a Pixel Device</b>\n\n"
            "Pick which Pixel the bot should simulate for your session. "
            "Only devices eligible for the Google One AI Premium (2 TB) "
            "12-month trial are listed.\n\n"
            "Active: <code>{active}</code>"
        ),
        "device_set_title": "✅ <b>Device Updated</b>",
        "device_set_body": (
            "Bot will now simulate <b>{model}</b> (Android {android}) for your session."
        ),
        "device_set_next": "Next step: run <code>/login</code> or <code>/check_offer</code>.",
        "device_set_toast": "Device set to {model}",
        "device_unknown": "Unknown device preset.",
    },
    "id": {
        "start_title": "🚀 Pixel Google One Assistant",
        "start_header_caption": "🚀 Panel Kontrol Pixel • Created by Dziel",
        "start_subtitle": "⌬ Panel Kontrol Pixel • Google One • Deck Offer Modern",
        "start_body": (
            "Panel kontrol Telegram modern untuk login Google yang aman, simulasi "
            "device Pixel, jaringan berbasis proxy, dan pengecekan offer Gemini secara live."
        ),
        "start_deck_intro": "Gunakan control deck di bawah untuk membuka login, diagnostik, alat proxy, dan pengecekan offer hanya dengan satu tap.",
        "start_tip": "💡 Mendukung akun Gmail dan Google Workspace.",
        "start_privacy": "🔒 Kredensial hanya disimpan di memori selama sesi aktif.",
        "creator_line": "Dibuat oleh Dziel",
        "quick_actions_title": (
            "<b>⌬ Pixel Control Panel</b>\n"
            "<code>Pixel • Google One • Deck Offer Modern</code>\n"
            "<i>Created by Dziel</i>\n\n"
            "Pilih modul di bawah untuk melanjutkan."
        ),
        "section_quick_start": "Mulai Cepat",
        "section_commands": "Perintah Inti",
        "section_language": "Bahasa",
        "section_tools": "Modul",
        "section_session": "Sesi",
        "section_device": "Profil Device",
        "section_proxy": "Mode Proxy",
        "section_flow": "Alur Rekomendasi",
        "section_power": "Power Tools",
        "start_flow_1": "Mulai sesi login aman dengan /login",
        "start_flow_2": "Periksa identitas proxy atau pindah ke mode direct",
        "start_flow_3": "Jalankan /check_offer dan lihat hasil live-nya",
        "command_login_desc": "Buka sesi login yang aman",
        "command_witai_desc": "Simpan token Wit.ai untuk solver audio captcha",
        "command_check_offer_desc": "Jalankan scanner offer Gemini",
        "command_doctor_desc": "Jalankan self-check setup untuk pengguna baru",
        "command_get_link_desc": "Tampilkan link offer terakhir yang tertangkap",
        "command_status_desc": "Lihat status akun, proxy, dan device",
        "command_proxy_desc": "Periksa proxy aktif dan pool",
        "command_ip_desc": "Cek IP publik dan geo saat ini",
        "command_rotate_proxy_desc": "Ganti ke proxy lain dari pool",
        "command_disable_proxy_desc": "Gunakan IP lokal/direct untuk sesi ini",
        "command_device_desc": "Pilih device Pixel yang disimulasikan bot",
        "command_lang_en_desc": "Ubah antarmuka ke Bahasa Inggris",
        "command_lang_id_desc": "Ubah antarmuka ke Bahasa Indonesia",
        "command_logout_desc": "Hapus sesi aktif dan state browser sementara",
        "offer_no_credentials": "⚠️ Kredensial tidak ditemukan. Jalankan /login terlebih dahulu.",
        "offer_cooldown_wait": "⏳ Mohon tunggu {mins}m {secs}d sebelum cek lagi.",
        "offer_capacity_busy": (
            "🔄 Sistem sedang mencapai kapasitas maksimum. Silakan coba lagi dalam satu menit."
        ),
        "offer_starting_secure_check": (
            "⏳ Memulai pengecekan aman...\n"
            "Menjalankan simulasi device Pixel dan login.\n"
            "Chrome biasanya akan muncul dalam 10-20 detik.\n"
            "Pengecekan penuh masih bisa memakan 1-3 menit jika Google meminta verifikasi tambahan."
        ),
        "offer_opening_visible_browser": (
            "🔓 Proxy dengan autentikasi terdeteksi.\n"
            "Chrome akan langsung dibuka dalam mode terlihat agar sesi ini tidak membuang waktu pada retry tersembunyi."
        ),
        "offer_retry_note_fresh": "membuat profil device Pixel baru dan mencoba lagi.",
        "offer_retry_note_same": "menggunakan device sesi yang sama dan mencoba lagi.",
        "offer_retry_attempt": "🔄 Percobaan ulang {attempt}/{max_attempts}: {note}",
        "offer_proxy_precheck_failed_rotate": (
            "⚠️ Precheck proxy gagal sebelum Chrome dibuka. Mengganti proxy..."
        ),
        "offer_proxy_precheck_failed_error": (
            "Precheck proxy gagal sebelum Chrome dibuka: {error}"
        ),
        "offer_manual_verification_reopen": (
            "🔐 Google meminta verifikasi manual.\n"
            "Membuka ulang Chrome dalam mode terlihat dengan device sesi yang sama..."
        ),
        "offer_auto_totp_rejected": (
            "❌ Kode TOTP otomatis ditolak. Silakan periksa secret key TOTP Anda."
        ),
        "offer_login_success_checking": (
            "✅ Login berhasil ({attempt}/{max_attempts}).\n"
            "Sedang memeriksa offer Gemini Pro sekarang..."
        ),
        "offer_auto_totp_error": (
            "❌ Error Auto-TOTP: {error}\n"
            "Silakan periksa secret key TOTP Anda."
        ),
        "offer_2fa_required": (
            "🔐 *Autentikasi Dua Faktor Diperlukan*\n\n"
            "Silakan kirim kode autentikator 6 digit Anda *hanya di Telegram ini*.\n"
            "Jangan ketik kode itu di jendela Chrome."
        ),
        "offer_manual_required": (
            "🔐 Verifikasi manual diperlukan.\n\n"
            "Google meminta: {challenge_type}\n"
            "Selesaikan langkah itu di jendela Chrome yang baru terbuka.\n"
            "Setelah browser keluar dari halaman login Google, kirim `done` di sini.\n"
            "Kirim /cancel untuk menghentikan pengecekan ini."
        ),
        "offer_proxy_transport_rotating": (
            "⚠️ Terdeteksi masalah transport proxy. Mengganti proxy..."
        ),
        "offer_runtime_network_rotating": (
            "⚠️ Terdeteksi masalah jaringan saat runtime. Mengganti proxy..."
        ),
        "offer_not_found_retrying": (
            "⏳ Offer belum ditemukan. Mencoba lagi dalam {delay} detik..."
        ),
        "offer_retry_device_fresh": "profil device Pixel baru",
        "offer_retry_device_same": "device sesi yang sama",
        "offer_starting_retry": (
            "🔄 Memulai percobaan ulang {next_attempt}/{max_attempts}: "
            "menyiapkan {device_note} dan login kembali."
        ),
        "offer_automation_error": "❌ <b>Error Otomasi:</b> {error}",
        "offer_unexpected_error": "❌ Terjadi error yang tidak terduga: {error}",
        "offer_session_expired": "⚠️ Sesi kedaluwarsa. Silakan jalankan /check_offer lagi.",
        "offer_verification_session_closed": (
            "⚠️ Sesi verifikasi Chrome sudah tertutup atau crash.\n"
            "Silakan jalankan /check_offer lagi."
        ),
        "offer_invalid_code": "⚠️ Kode tidak valid. Masukkan 6 digit angka.",
        "offer_verifying_code": "🔄 Sedang memverifikasi kode…",
        "offer_code_rejected": (
            "❌ Kode ditolak atau sudah kedaluwarsa.\n"
            "Silakan kirim kode autentikator 6 digit yang baru.\n"
            "Kirim /cancel untuk menghentikan pengecekan ini."
        ),
        "offer_generic_error": "❌ Error: {error}",
        "offer_verification_window_closed": (
            "⚠️ Jendela verifikasi Chrome sudah tertutup atau crash.\n"
            "Silakan jalankan /check_offer lagi."
        ),
        "offer_checking_chrome_window": "🔄 Sedang memeriksa jendela Chrome…",
        "offer_2fa_required_after_manual": (
            "🔐 *Autentikasi Dua Faktor Diperlukan*\n\n"
            "Google sudah berpindah ke langkah kode autentikator.\n"
            "Silakan kirim kode 6 digit Anda *hanya di Telegram ini*.\n"
            "Jangan ketik kode itu di jendela Chrome."
        ),
        "offer_google_waiting_verification": (
            "⏳ Google masih menunggu verifikasi di Chrome.\n"
            "Langkah tertunda: {challenge_type}\n"
            "Selesaikan dulu di sana, lalu kirim `done` lagi.\n"
            "Kirim /cancel untuk menghentikan pengecekan ini."
        ),
        "offer_verification_completed_checking": (
            "✅ Verifikasi selesai. Sedang memeriksa offer Gemini Pro sekarang..."
        ),
        "offer_verification_cancelled": "❌ Verifikasi dibatalkan.",
        "offer_verification_timed_out": (
            "⏰ Waktu verifikasi habis. Silakan jalankan /check_offer lagi."
        ),
        "offer_found_html": (
            "🎉 <b>Offer Gemini Pro Ditemukan!</b>\n\n"
            "Gunakan link di bawah untuk mengaktifkan Gemini Pro gratis 12 bulan:\n\n"
            "🔗 {offer_link}\n\n"
            "Anda bisa menjalankan /get_link kapan saja untuk mengambil link ini lagi."
        ),
        "offer_found_plain": (
            "🎉 Offer Gemini Pro Ditemukan!\n\n"
            "🔗 {offer_link}\n\n"
            "Anda bisa menjalankan /get_link kapan saja untuk mengambil link ini lagi."
        ),
        "offer_not_found_now": (
            "😔 Tidak ada offer Gemini Pro aktif yang terdeteksi di akun Google One Anda saat ini.\n\n"
            "Offer ini mungkin belum tersedia untuk region akun Anda atau mungkin sudah pernah diaktifkan. "
            "Anda bisa mencoba lagi nanti.{diagnostic_note}{artifact_note}"
        ),
        "offer_embedded_trial_detected": (
            "🧪 Offer trial Google One terdeteksi untuk akun ini, tetapi AutoPixel belum berhasil menangkap "
            "link checkout secara otomatis.\n\n"
            "Biasanya ini berarti offer berada di balik alur tombol Google, bukan link klaim langsung."
            "{diagnostic_note}{artifact_note}"
        ),
        "offer_not_found_after_attempts": (
            "❌ Tidak ditemukan offer Gemini Pro setelah {attempts} percobaan.\n\n"
            "Kemungkinan penyebab:\n"
            "• Region akun Anda tidak memenuhi syarat\n"
            "• Sudah ada langganan Gemini aktif\n"
            "• Kelayakan grup keluarga sudah pernah digunakan\n"
            "• Kontrol risiko untuk akun baru sedang aktif"
            "{diagnostic_note}{artifact_note}"
        ),
        "offer_diagnosis_label": "Diagnosa",
        "offer_debug_saved": "Artefak debug disimpan:",
        "offer_debug_screenshot": "Screenshot: {path}",
        "offer_debug_html": "HTML: {path}",
        "offer_diag_ai_mixed": (
            "Google One menampilkan produk terkait AI, tetapi status promonya campur "
            "dan perlu ditinjau manual."
        ),
        "offer_diag_paid_no_free": (
            "Google One menampilkan paket Google AI Pro berbayar reguler untuk akun ini, "
            "tetapi tidak ada link klaim promo gratis."
        ),
        "offer_diag_normal_plan_no_promo": (
            "Google One memuat halaman paket normal akun Anda, tetapi tidak ada kartu promo."
        ),
        "offer_diag_embedded_ai_trial": (
            "Google One menampilkan offer trial Google AI yang tertanam di halaman paket, "
            "tetapi AutoPixel belum berhasil menangkap link checkout secara otomatis."
        ),
        "offer_diag_embedded_trial": (
            "Google One menampilkan offer trial yang tertanam di halaman paket, "
            "tetapi AutoPixel belum berhasil menangkap link checkout secara otomatis."
        ),
        "lang_set": "🌐 Bahasa diubah ke Indonesia.",
        "login_prompt_email": (
            "📧 [·] Login\n"
            "Kirim alamat email Google Anda.\n"
            "Didukung: Gmail dan Google Workspace."
        ),
        "login_invalid_email": (
            "⚠️ [·] Email Tidak Valid\n"
            "Masukkan alamat email yang valid.\n"
            "Contoh: user@gmail.com atau user@company.com."
        ),
        "login_password_prompt": (
            "✅ [·] Email Diterima\n"
            "<code>{email}</code>\n\n"
            "🔒 Sekarang kirim password Anda.\n"
            "Format opsional: <code>password|totp_secret</code>"
        ),
        "login_saved_title": "✅ [·] Sesi Siap",
        "login_saved_body": "Kredensial berhasil disimpan. Profil device Pixel baru sudah siap untuk sesi ini.",
        "login_saved_totp": "🔑 TOTP terdeteksi. Auto-2FA tersedia untuk sesi ini.",
        "login_saved_next": "Langkah berikutnya: jalankan <code>/check_offer</code>",
        "login_cancelled": "❌ Alur login dibatalkan.",
        "wit_ai_prompt": (
            "🧠 Kirim token server Wit.ai Anda sekarang.\n\n"
            "Tip: Anda juga bisa langsung kirim `/witai TOKEN_ANDA`.\n"
            "Kirim `clear` untuk menghapus token yang tersimpan.\n"
            "Kirim /cancel untuk batal."
        ),
        "wit_ai_invalid": "⚠️ Token Wit.ai terlihat kosong atau terlalu pendek. Silakan coba lagi.",
        "wit_ai_saved": (
            "✅ Token Wit.ai berhasil disimpan.\n\n"
            "Token tersamarkan: <code>{token}</code>\n"
            "Auto-solve audio captcha sekarang aktif.\n"
            "Disimpan ke: <code>{path}</code>"
        ),
        "wit_ai_cleared": (
            "🗑️ Token Wit.ai berhasil dihapus.\n\n"
            "Solver audio captcha akan kembali ke verifikasi manual.\n"
            "File yang diperbarui: <code>{path}</code>"
        ),
        "wit_ai_cancelled": "❌ Input token Wit.ai dibatalkan.",
        "logout_success": "🗑️ Sesi, kredensial, dan state browser sementara berhasil dibersihkan.",
        "logout_none": "ℹ️ Tidak ada sesi aktif untuk dibersihkan.",
        "doctor_running": "🩺 Sedang menjalankan self-check setup...",
        "doctor_title": "<b>🩺 Dokter Setup</b>",
        "doctor_summary_ok": "✅ Baseline setup Anda terlihat siap untuk pengguna baru.",
        "doctor_summary_warn": "⚠️ Bot sudah bisa berjalan, tetapi masih ada beberapa hal setup yang sebaiknya dirapikan dulu.",
        "doctor_summary_fail": "❌ Bot belum siap untuk setup pengguna baru yang bersih.",
        "doctor_token_ok": "✅ Token bot Telegram sudah termuat.",
        "doctor_token_fail": "❌ Token bot Telegram belum ada. Isi <code>TELEGRAM_BOT_TOKEN</code> di .env terlebih dahulu.",
        "doctor_chrome_ok": "✅ Versi Chrome terdeteksi: <code>{version}</code> (major <code>{major}</code>).",
        "doctor_chrome_fail": "❌ Chrome tidak terdeteksi dengan benar. Instal Chrome atau isi <code>CHROME_BIN</code> / <code>CHROME_VERSION</code>.",
        "doctor_env_ok": "✅ File .env terdeteksi di <code>{path}</code>.",
        "doctor_env_warn": "⚠️ File .env lokal tidak ditemukan di <code>{path}</code>. Environment variable sistem masih bisa dipakai.",
        "doctor_header_local_ok": "✅ File header media ditemukan: <code>{value}</code>.",
        "doctor_header_remote_ok": "✅ Header media dikonfigurasi sebagai URL remote: <code>{value}</code>.",
        "doctor_header_disabled": "⚠️ Header media kosong atau dinonaktifkan.",
        "doctor_header_warn": "⚠️ Path/URL header media terlihat tidak valid: <code>{value}</code>.",
        "doctor_proxy_disabled": "✅ Mode proxy nonaktif secara default. Pengguna baru akan mulai dengan direct mode.",
        "doctor_proxy_missing": "⚠️ Mode proxy aktif, tetapi file proxy tidak ditemukan: <code>{path}</code>.",
        "doctor_proxy_unreadable": "⚠️ Path proxy ada, tetapi bukan file yang bisa dibaca: <code>{path}</code>.",
        "doctor_proxy_empty": "⚠️ File proxy ada, tetapi tidak ditemukan entri proxy valid: <code>{path}</code>.",
        "doctor_proxy_warn_invalid": "⚠️ Pool proxy termuat dengan <code>{valid}</code> entri valid dan <code>{invalid}</code> entri tidak valid.",
        "doctor_proxy_ok": "✅ Pool proxy terlihat baik: <code>{count}</code> entri valid di <code>{path}</code>.",
        "doctor_driver_auto": "✅ CHROMEDRIVER_PATH tidak dipatok. Resolusi driver otomatis aktif.",
        "doctor_driver_ok": "✅ CHROMEDRIVER_PATH tersedia: <code>{path}</code>.",
        "doctor_driver_warn": "⚠️ CHROMEDRIVER_PATH diisi, tetapi file-nya tidak ada: <code>{path}</code>.",
        "doctor_next_steps": "Langkah berikutnya: jalankan <code>/login</code> untuk sesi nyata, atau benahi warning di atas sebelum repo dibagikan ke pengguna baru.",
        "status_no_session": "ℹ️ Tidak ada sesi aktif. Jalankan /login untuk memulai.",
        "status_title": "📊 Ringkasan Sesi",
        "status_account": "👤 Akun",
        "status_creds": "🔐 Kredensial dimuat",
        "status_offer": "🎁 Link offer tertangkap",
        "status_yes": "✅ Ya",
        "status_no": "❌ Tidak",
        "proxy_summary_direct": "direct / IP lokal",
        "proxy_summary_direct_locked": "direct / IP lokal (override manual)",
        "proxy_summary_pool": "🧩 Pool proxy: {available}/{total} tersedia",
        "proxy_disabled_set": "⛔ [·] Mode Direct Aktif\nSesi ini sekarang akan memakai IP lokal/direct Anda.",
        "proxy_disabled_already": "⛔ [·] Mode Direct Sudah Aktif\nSesi ini memang sudah memakai IP lokal/direct Anda.",
        "proxy_rotated": "🔄 [·] Proxy Diganti\nProxy baru: <code>{proxy}</code>",
        "proxy_no_pool": "ℹ️ Tidak ada proxy yang dimuat dari pool.\nBot akan lanjut memakai koneksi direct.",
        "proxy_no_healthy": "⚠️ Tidak ada proxy alternatif yang sehat saat ini.\nBot akan lanjut memakai koneksi direct.",
        "ip_checking": "🔎 Sedang memeriksa identitas jaringan...",
        "ip_check_failed": "⚠️ Cek IP gagal.\n\nAlasan: {reason}",
        "network_title": "🌍 Identitas Koneksi",
        "ip_emulation_title": "🧪 Emulasi Browser Aktif",
        "ip_emulation_source_route": "Sumber: data route aktif dari /ip",
        "ip_emulation_source_fallback": "Sumber: nilai fallback dari .env",
        "ip_emulation_copy_note": "Salin baris ini ke .env jika Anda ingin mengunci nilai emulasi saat ini:",
        "proxy_panel_title": "🌍 Panel Proxy Aktif",
        "proxy_rotated_title": "🔄 Panel Proxy Baru",
        "direct_panel_title": "🧷 Panel Jaringan Direct",
        "menu_login": "🚀 Login",
        "menu_check_offer": "🎯 Cek Offer",
        "menu_status": "📊 Status",
        "menu_get_link": "🔗 Ambil Link",
        "menu_proxy": "🌐 Proxy",
        "menu_ip": "🧭 Cek IP",
        "menu_rotate_proxy": "🔄 Ganti Proxy",
        "menu_disable_proxy": "⛔ Mode Direct",
        "menu_device": "📱 Pilih Device",
        "menu_lang_en": "🇺🇸 Inggris",
        "menu_lang_id": "🇮🇩 Indonesia",
        "menu_home": "🏠 Beranda",
        "menu_logout": "🗑️ Logout",
        "menu_panel_header": "⌬ PANEL KONTROL PIXEL",
        "menu_panel_refresh": "🪄 Buka Dashboard",
        "device_prompt": (
            "📱 <b>Pilih Device Pixel</b>\n\n"
            "Pilih Pixel yang akan disimulasikan bot untuk sesi Anda. "
            "Hanya device yang memenuhi syarat trial Google One AI Premium "
            "(2 TB) selama 12 bulan yang ditampilkan.\n\n"
            "Aktif: <code>{active}</code>"
        ),
        "device_set_title": "✅ <b>Device Diperbarui</b>",
        "device_set_body": (
            "Bot sekarang akan menyimulasikan <b>{model}</b> (Android {android}) untuk sesi Anda."
        ),
        "device_set_next": "Langkah berikutnya: jalankan <code>/login</code> atau <code>/check_offer</code>.",
        "device_set_toast": "Device diatur ke {model}",
        "device_unknown": "Preset device tidak dikenal.",
    },
}


def get_user_lang(context) -> str:
    """Return active language code for a user context."""
    lang = getattr(context, "user_data", {}).get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def set_user_lang(context, lang: str) -> str:
    """Persist language preference and return the active language."""
    active = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    context.user_data["lang"] = active
    return active


def _resolve_lang(context=None, lang: str | None = None) -> str:
    if lang in SUPPORTED_LANGS:
        return lang
    if context is not None:
        return get_user_lang(context)
    return DEFAULT_LANG


def tr(context, key: str, **kwargs) -> str:
    """Translate a UI message key based on current user language."""
    lang = _resolve_lang(context)
    template = I18N.get(lang, I18N[DEFAULT_LANG]).get(
        key,
        I18N[DEFAULT_LANG].get(key, key),
    )
    return template.format(**kwargs) if kwargs else template


def menu_label(key: str, context=None, lang: str | None = None) -> str:
    """Return a translated menu label."""
    active_lang = _resolve_lang(context, lang)
    return I18N.get(active_lang, I18N[DEFAULT_LANG]).get(key, key)


def button_regex(key: str) -> str:
    """Return an exact-match regex for a menu button across all languages."""
    labels = [
        re.escape(I18N[lang][key])
        for lang in sorted(SUPPORTED_LANGS)
        if key in I18N[lang]
    ]
    return f"^({'|'.join(labels)})$"


def section_header(context, key: str) -> str:
    """Return a consistent section header."""
    return f"[·] <b>{html.escape(tr(context, key))}</b>"


def menu_callback_data(key: str) -> str:
    """Return callback data for an inline control-panel button."""
    if key in {INLINE_PANEL_HEADER_KEY, INLINE_PANEL_FOOTER_KEY, "menu_home"}:
        return "menu:home"
    return f"menu:{key.removeprefix('menu_')}"


async def prepare_action_message(update: Update):
    """Answer callback queries when needed and return the best reply target."""
    query = getattr(update, "callback_query", None)
    if query:
        try:
            await query.answer()
        except Exception:
            pass
    return update.effective_message


def send_header_media(context, chat_id: int, caption: str | None = None) -> None:
    """Compatibility shim for callers that may import this name directly."""
    raise RuntimeError("send_header_media is async; use send_header_media_async instead.")


async def send_header_media_async(context, chat_id: int, caption: str | None = None) -> None:
    """Send a header image or GIF when configured."""
    media_url = (config.BOT_HEADER_MEDIA_URL or "").strip()
    if not media_url:
        return

    try:
        lowered = media_url.lower()
        is_local_file = os.path.exists(media_url)
        if is_local_file:
            with open(media_url, "rb") as handle:
                if lowered.endswith((".gif", ".mp4")):
                    await context.bot.send_animation(
                        chat_id=chat_id,
                        animation=handle,
                        caption=caption,
                        parse_mode="HTML" if caption else None,
                    )
                else:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=handle,
                        caption=caption,
                        parse_mode="HTML" if caption else None,
                    )
            return

        if lowered.endswith((".gif", ".mp4")):
            await context.bot.send_animation(
                chat_id=chat_id,
                animation=media_url,
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
        else:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=media_url,
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
    except Exception as exc:
        logger.warning("Failed to send header media to chat %s: %s", chat_id, exc)


def main_menu_keyboard(context=None) -> ReplyKeyboardMarkup:
    """Return a persistent, emoji-rich navigation keyboard."""
    keyboard = [
        [menu_label(key, context) for key in row]
        for row in MENU_ROWS
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def quick_actions_inline_keyboard(context=None) -> InlineKeyboardMarkup:
    """Return a tidy inline action grid."""
    rows = [
        [
            InlineKeyboardButton(
                menu_label(INLINE_PANEL_HEADER_KEY, context),
                callback_data=menu_callback_data("menu_home"),
            )
        ]
    ]
    for row in MENU_ROWS:
        rows.append(
            [
                InlineKeyboardButton(
                    menu_label(key, context),
                    callback_data=menu_callback_data(key),
                )
                for key in row
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                menu_label(INLINE_PANEL_FOOTER_KEY, context),
                callback_data=menu_callback_data(INLINE_PANEL_FOOTER_KEY),
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_welcome_message(context) -> str:
    """Return the redesigned start/welcome card."""
    lines = [
        f"<b>{html.escape(tr(context, 'start_title'))}</b>",
        f"<code>{html.escape(tr(context, 'start_subtitle'))}</code>",
        f"👑 <b>{html.escape(tr(context, 'creator_line'))}</b>",
        "",
        html.escape(tr(context, "start_body")),
        "",
        f"🔥 {section_header(context, 'section_tools')}",
        html.escape(tr(context, "start_deck_intro")),
        "",
        f"⚡ {section_header(context, 'section_quick_start')}",
        f"• 🩺 <code>/doctor</code> · {html.escape(tr(context, 'command_doctor_desc'))}",
        f"• 🚀 <code>/login</code> · {html.escape(tr(context, 'command_login_desc'))}",
        f"• 🧠 <code>/witai</code> · {html.escape(tr(context, 'command_witai_desc'))}",
        f"• 🎯 <code>/check_offer</code> · {html.escape(tr(context, 'command_check_offer_desc'))}",
        f"• 🔗 <code>/get_link</code> · {html.escape(tr(context, 'command_get_link_desc'))}",
        "",
        f"🧭 {section_header(context, 'section_flow')}",
        f"• 1 · {html.escape(tr(context, 'start_flow_1'))}",
        f"• 2 · {html.escape(tr(context, 'start_flow_2'))}",
        f"• 3 · {html.escape(tr(context, 'start_flow_3'))}",
        "",
        f"🧩 {section_header(context, 'section_commands')}",
        f"• 📊 <code>/status</code> · {html.escape(tr(context, 'command_status_desc'))}",
        f"• 🌐 <code>/proxy</code> · {html.escape(tr(context, 'command_proxy_desc'))}",
        f"• 🧭 <code>/ip</code> · {html.escape(tr(context, 'command_ip_desc'))}",
        f"• 🔄 <code>/rotate_proxy</code> · {html.escape(tr(context, 'command_rotate_proxy_desc'))}",
        f"• ⛔ <code>/disable_proxy</code> · {html.escape(tr(context, 'command_disable_proxy_desc'))}",
        "",
        f"🛠️ {section_header(context, 'section_power')}",
        f"• 🇺🇸 <code>/lang_en</code> · {html.escape(tr(context, 'command_lang_en_desc'))}",
        f"• 🇮🇩 <code>/lang_id</code> · {html.escape(tr(context, 'command_lang_id_desc'))}",
        f"• 🗑️ <code>/logout</code> · {html.escape(tr(context, 'command_logout_desc'))}",
        "",
        f"🛡️ {html.escape(tr(context, 'start_privacy'))}",
        f"💡 {html.escape(tr(context, 'start_tip'))}",
    ]
    return "\n".join(lines)


def build_session_overview(
    context,
    email: str,
    has_creds: bool,
    has_offer_link: bool,
    device_summary: str | None,
    proxy_summary: str | None = None,
) -> str:
    """Return a formatted HTML status card for `/status`."""
    lines = [
        f"<b>{html.escape(tr(context, 'status_title'))}</b>",
        f"<code>{html.escape(tr(context, 'start_subtitle'))}</code>",
        f"👑 <b>{html.escape(tr(context, 'creator_line'))}</b>",
        "",
        section_header(context, "section_session"),
        f"{html.escape(tr(context, 'status_account'))}: <code>{html.escape(email)}</code>",
        f"{html.escape(tr(context, 'status_creds'))}: {tr(context, 'status_yes') if has_creds else tr(context, 'status_no')}",
        f"{html.escape(tr(context, 'status_offer'))}: {tr(context, 'status_yes') if has_offer_link else tr(context, 'status_no')}",
    ]
    if proxy_summary:
        lines.append("")
        lines.append(section_header(context, "section_proxy"))
        lines.append(proxy_summary)
    if device_summary:
        lines.append("")
        lines.append(section_header(context, "section_device"))
        lines.append(device_summary)
    return "\n".join(lines)
