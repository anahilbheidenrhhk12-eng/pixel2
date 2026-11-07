# Changelog

This file documents the feature baseline of AutoPixel.

## [Unreleased]

### Added
- Added per-user device profile selection inside the bot. Each Telegram user can now run `/device` (or tap the new **📱 Pick Device** button on the Control Panel) to choose which Pixel preset the bot should simulate for their session. The selection is stored per chat and is applied automatically the next time a device profile is generated (e.g. on `/login`, `/check_offer`, `/rotate_proxy`, `/disable_proxy`). Active sessions are refreshed in place when a new device is picked.
- Added `pixel_9_pro`, `pixel_9_pro_xl`, `pixel_9_pro_fold`, `pixel_10_pro_xl`, and `pixel_10_pro_fold` device presets. These are the Pixel models eligible for the Google One AI Premium (2 TB) 12-month trial, in addition to the existing `pixel_10_pro` default.

### Removed
- Dropped the `pixel_4a`, `pixel_5_android_11`, `pixel_6`, `pixel_7_pro`, and `pixel_8_pro` device presets. The Google One / Pixel offer is only eligible on the Pixel 10 series, so the bot now simulates the Pixel 10 Pro exclusively and the default profile is `pixel_10_pro`.

## [1.1.0] - 2026-03-31

### User-Facing Google One / Pixel Improvements
- Added `/doctor` onboarding diagnostics so new users can validate bot token, Chrome detection, `.env`, header media, and proxy pool readiness before running a live login.
- Expanded `/ip` output with `.env`-ready emulation values so timezone, latitude, longitude, and accuracy can be copied into fallback config when needed.
- Clarified direct-mode and proxy behavior in the sample configuration so users understand that `PROXY_ENABLED=0` is the clean way to start without proxies.
- Kept `proxies.txt` as a tracked sample file so first-time users can start from a ready format instead of creating the file from scratch.

### Product Readiness
- Improved onboarding documentation across `README.md`, `HOW TO RUN IT .txt`, and `.env.example` so fresh installs are easier to complete on Windows and Termux.
- Documented the current Google One / Pixel offer support matrix and eligibility caveats more clearly for users checking the promo in different regions.
- Added a clearer release summary path so channel notifications can explain Google One / Pixel improvements in a user-facing way instead of only mentioning internal workflow changes.

## [1.0.0] - 2026-03-26

### Product Scope
- Telegram-first automation workflow for Google One Gemini promotional offer checks
- Pixel 10 Pro device simulation profile with anti-detection oriented browser attributes
- Offer eligibility automation for user-provided Google accounts

### Core Features
- Account login conversation flow:
  - `/login` captures email and password interactively
  - Optional combined credential input format: `password|totp_secret`
- Offer check flow:
  - `/check_offer` launches browser automation and checks Google One offer pages
  - Multi-attempt retry strategy with fresh device profile per attempt
  - Structured user feedback during each attempt
- Session utilities:
  - `/status` returns account/session/device summary
  - `/get_link` returns last captured activation URL
  - `/logout` securely clears session and credentials
- 2FA handling:
  - TOTP auto-generation when secret is provided
  - Manual 2FA code input fallback when required
  - Timeout and cancellation handling for pending 2FA flow

### Architecture
- Modular project layout:
  - `core/` for runtime state and session lifecycle
  - `handlers/` for Telegram commands and UX flow
  - `services/` for automation and simulation business logic
- Internal service decomposition:
  - `services/google_automation_core/` for driver, login, scanner, and API modules
  - `services/device_simulator_core/` for generators, constants, profile, and factory modules
- Facade modules retained for clean external imports:
  - `services/google_automation.py`
  - `services/device_simulator.py`

### Bot UX
- Modernized command UX with persistent main menu keyboard
- Inline quick actions for frequent commands
- Added `/doctor` first-run setup diagnostics for new-user onboarding
- Localized language preference switch commands:
  - `/lang_en`
  - `/lang_id`
- Message templates centralized through UI helper utilities for cleaner handler code
- Consistent status/error/progress messaging style across auth and offer flows

### Reliability and Safety
- Session credential storage uses in-memory `bytearray` values
- Secure wipe routine for credentials at flow termination
- Password and sensitive code chat message deletion attempts
- Environment parsing now falls back safely on bad numeric `.env` values instead of crashing at import time
- Per-user cooldown for offer checks
- Concurrency limiting for browser sessions to reduce resource contention

### Runtime and Platform Support
- Cross-platform runtime support:
  - Windows
  - Linux
  - macOS
- Browser/driver detection strategy:
  - Auto-detect browser binaries where possible
  - Support explicit `CHROME_BIN`
  - Support explicit `CHROMEDRIVER_PATH`
  - Selenium Manager fallback when driver path is not manually set

### Deployment
- Dockerized runtime with Chromium/Chromedriver support
- Compose service standardized to container name: `autpixel`
- `.env.example` provided for required and optional environment setup

### Documentation Baseline
- README redesigned with:
  - Product-style overview and highlights
  - Region support matrix
  - Eligibility checklist
  - Troubleshooting by symptom
  - Windows PowerShell, Windows CMD, and Android Termux quick-start guidance
