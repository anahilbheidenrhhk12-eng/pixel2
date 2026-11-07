# AutoPixel

**Pixel Google One Assistant**

AutoPixel is a Telegram bot that simulates a Pixel device session (Pixel 10 Pro by default, with the rest of the Google One AI Premium-eligible Pixel 9 Pro and Pixel 10 Pro lineup also available), signs in to a Google account, checks Google One / Gemini offer availability, and gives you a modern control panel for session, proxy, IP, and diagnostic tools.

## Highlights

- Simulates a fresh Pixel device profile for each login session (defaults to Pixel 10 Pro)
- Switchable device profiles for the Google One AI Premium 2 TB 12-month-eligible Pixel lineup (Pixel 9 Pro / 9 Pro XL / 9 Pro Fold and Pixel 10 Pro / 10 Pro XL / 10 Pro Fold) via `DEVICE_PROFILE` or, per Telegram user, the new `/device` picker
- Supports Gmail and Google Workspace accounts
- Handles Google sign-in with TOTP / authenticator flow support
- Can attempt audio captcha solving through `wit.ai` before falling back to manual verification
- Checks Google One pages for Gemini / AI Pro offer availability
- Supports proxy pool rotation and direct/local IP mode
- Shows public IP, region, ZIP, org, ISP, ASN, timezone, and other proxy identity details
- Saves screenshot + HTML debug artifacts when no offer is found
- Supports English and Indonesian UI
- Ships with a modern Telegram dashboard:
  - header media
  - 2-column grid buttons
  - `[·]` section cards
  - emoji-rich menu labels

## Latest Product Update

As of **March 31, 2026**, the current user-facing baseline includes:

- `/doctor` to validate first-run setup before you test a real Google account
- `/ip` output that now exposes `.env`-ready emulation timezone and GPS values
- safer `.env` handling so bad numeric fallback values do not break startup
- a tracked sample `proxies.txt` file for quicker proxy onboarding
- refreshed Google One / Pixel onboarding docs and region guidance

This update is meant to make the project easier for first-time users to configure, diagnose, and understand before they run a live offer check.

## Documentation

| File | Purpose |
|---|---|
| `README.md` | Product overview, setup summary, commands, and troubleshooting |
| `HOW TO RUN IT .txt` | Plain-text run guide for Windows PowerShell, Windows CMD, and Android Termux |
| `CHANGELOG.md` | Baseline release notes and architecture history |

## Pixel Promo Region Matrix

As of **March 31, 2026**, Google's official Pixel offer page lists the **Pixel 10 Pro / Pixel 10 Pro XL / Pixel 10 Pro Fold** Google AI Pro promo across the following region groups. Actual eligibility still depends on device purchase + activation, account status, billing profile, and Google's live eligibility checks.

| Region Group | Countries / Regions Listed by Google | Notes |
|---|---|---|
| USA & North America | Canada, Mexico, United States | Listed on the official Pixel offer help page |
| Europe | Austria, Belgium, Czechia, Denmark, Estonia, Finland, France, Germany, Hungary, Ireland, Italy, Latvia, Lithuania, Netherlands, Norway, Poland, Portugal, Romania, Slovakia, Slovenia, Spain, Sweden, Switzerland, United Kingdom | Listed on the official Pixel offer help page |
| Asia-Pacific | Australia, India, Japan, Malaysia, Singapore, Taiwan | Listed on the official Pixel offer help page |

Important notes:

- Google also lists **Japan** separately on the same Pixel offer page for a shorter trial on some Pixel Pro offer rows, so trial length can vary by country and device row.
- Google AI Pro itself is supported in a much wider set of countries and regions than the Pixel-device promo. That means the plan may exist in a country even when the Pixel promo is not officially listed there.
- This bot can only check for offer visibility and eligibility. It cannot make an account eligible in a country or billing profile that Google does not support.

Official sources:

- [Google One offers for Pixel devices](https://support.google.com/pixelphone/answer/13529884?hl=en-GB)
- [Get a Google AI Pro membership](https://support.google.com/googleone/answer/16476811?co=GENIE.Platform%3DDesktop&hl=en)

## Main Commands

| Command | Function |
|---|---|
| `/start` | Open the Pixel Control Panel |
| `/doctor` | Run a first-time setup self-check |
| `/login` | Save Google email + password and create a fresh device session |
| `/witai` | Save or clear the Wit.ai token used for audio captcha solving |
| `/check_offer` | Start login automation and scan Google One for an offer |
| `/get_link` | Show the last captured offer link |
| `/status` | Show account, proxy, and device session info |
| `/proxy` | Show the active proxy and proxy pool status |
| `/ip` | Show public IP and geo/identity data |
| `/rotate_proxy` | Switch to another proxy from the pool |
| `/disable_proxy` | Force the session to use direct/local IP |
| `/lang_en` | Switch bot UI to English |
| `/lang_id` | Switch bot UI to Indonesian |
| `/langid` | Alias for `/lang_id` |
| `/logout` | Clear active session, credentials, and temporary browser state |
| `/cancel` | Cancel the current login / verification flow |

## Current UI

The bot now uses:

- a modern welcome card
- a local banner/header image on `/start`
- a 2-column inline control panel
- reply-keyboard navigation buttons

Important: old inline panels sent before the latest update still contain the old non-working inline-query buttons. Send `/start` again to get the new working control panel.

## Project Structure

```text
AUTOPIXEL/
├── main.py
├── config.py
├── requirements.txt
├── README.md
├── core/
│   ├── proxy_manager.py
│   └── session_manager.py
├── handlers/
│   ├── auth_handlers.py
│   ├── offer_handlers.py
│   ├── session_handlers.py
│   └── ui.py
├── services/
│   ├── device_simulator.py
│   ├── google_automation.py
│   └── network_diagnostics.py
└── assets/
    └── telegram/
        └── pixel-header.png
```

## Requirements

- Python 3.10+
- Google Chrome installed
- A Telegram bot token from `@BotFather`
- Internet connection
- Optional: `proxies.txt` if you want proxy mode
- Full browser automation is best supported on Windows, Linux, or macOS with desktop Chrome available

## Quick Start

For the full plain-text run guide, see [`HOW TO RUN IT .txt`](HOW%20TO%20RUN%20IT%20.txt).

After the bot starts for the first time, run `/doctor` in Telegram to verify token, Chrome detection, header media, proxy pool readiness, and driver configuration before testing a real account.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe main.py
```

### Windows Command Prompt (CMD)

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe main.py
```

### Android Termux

```bash
pkg update && pkg upgrade -y
pkg install -y python git clang rust libffi openssl
cd /path/to/AUTOPIXEL
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Termux note: the Telegram bot process can run in Termux, but Chrome-based Google login automation normally requires a desktop-class Chrome/WebDriver environment.

## Detailed Setup Notes

### Environment file

Copy `.env.example` to `.env` and fill what you need:

```env
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
BOT_HEADER_MEDIA_URL=
CHROME_BIN=
CHROMEDRIVER_PATH=
GOOGLE_CAPTCHA_AUTO_SOLVE=1
WIT_AI_TOKEN=
PROXY_ENABLED=1
PROXY_FILE_PATH=
PROXY_FAILURE_COOLDOWN_SECONDS=90
PROXY_QUARANTINE_SECONDS=300
PROXY_QUARANTINE_THRESHOLD=3
PROXY_DIAGNOSTICS_VERIFY_SSL=0
```

Notes:

- `BOT_HEADER_MEDIA_URL` supports a local image path, image URL, GIF URL, or MP4 URL
- if `BOT_HEADER_MEDIA_URL` is empty, the bot uses the bundled local banner asset
- if `CHROMEDRIVER_PATH` is empty, the runtime falls back to automatic driver resolution
- you can also set the Wit.ai token from Telegram with `/witai` and the bot will store it in `.env`
- set `WIT_AI_TOKEN` if you want AutoPixel to try solving audio captcha challenges automatically
- if you need help getting a Wit.ai token, see `HOW TO GET A WIT.AI API KEY.txt`
- `PROXY_DIAGNOSTICS_VERIFY_SSL=0` lets `/ip` and proxy precheck tolerate self-signed/intercepted TLS chains often seen on proxy routes

### Optional device profile

AutoPixel defaults to a **Pixel 10 Pro on Android 16** profile. Only Pixel devices eligible for the Google One AI Premium (2 TB) 12-month trial are bundled — that means the Pixel 9 Pro / 9 Pro XL / 9 Pro Fold and Pixel 10 Pro / 10 Pro XL / 10 Pro Fold. To switch to another preset, set it in `.env`:

```env
DEVICE_PROFILE=pixel_9_pro
```

Available presets:

| Preset | Device | Android | SDK | GPU | RAM |
|---|---|---|---|---|---|
| `pixel_10_pro` (default) | Pixel 10 Pro | 16 | 36 | Adreno 750 | 12 GB |
| `pixel_10_pro_xl` | Pixel 10 Pro XL | 16 | 36 | Adreno 750 | 16 GB |
| `pixel_10_pro_fold` | Pixel 10 Pro Fold | 16 | 36 | Adreno 750 | 16 GB |
| `pixel_9_pro` | Pixel 9 Pro | 16 | 36 | Mali-G715 Immortalis MP7 | 16 GB |
| `pixel_9_pro_xl` | Pixel 9 Pro XL | 16 | 36 | Mali-G715 Immortalis MP7 | 16 GB |
| `pixel_9_pro_fold` | Pixel 9 Pro Fold | 16 | 36 | Mali-G715 Immortalis MP7 | 16 GB |

Switching the profile changes the simulated user-agent, build IDs, screen metrics, WebGL renderer, RAM, and Client Hints headers so the session matches the chosen device. An unknown value logs a warning and falls back to the default Pixel 10 Pro / Android 16 profile.

`DEVICE_PROFILE` only sets the **default** for new chats. From inside Telegram you can override it per user without restarting the bot:

- send `/device` (or tap the **📱 Pick Device** button on the Control Panel)
- pick any preset from the inline keyboard
- the bot stores the choice in your chat session and applies it next time a fresh device profile is generated (e.g. on `/login`, `/check_offer`, `/rotate_proxy`, `/disable_proxy`)
- if there is already an active session, the device profile is rebuilt in place so the change takes effect immediately

### Optional proxies

The repository includes a sample `proxies.txt` in the project root.
Edit that file directly if you want proxy mode.

If you want the bot to start in direct mode by default, set `PROXY_ENABLED=0`.
Leaving `PROXY_FILE_PATH` empty does not disable proxy mode. It only falls back to the default `proxies.txt` path.

Supported formats:

```text
http://ip:port
http://user:pass@ip:port
https://user:pass@ip:port
socks5://ip:port
ip:port:user:pass
user:pass@ip:port
```

## Typical Flow

1. Send `/start`
2. Send `/doctor` to validate first-run setup
3. Send `/lang_id` if you want Indonesian UI
4. Send `/login`
5. Enter email
6. Enter password, or `password|totp_secret`
7. Check `/ip` or `/proxy`
8. Send `/check_offer`
9. If 2FA is requested, send the 6-digit code in Telegram
10. Review the result or debug artifacts

## Success Example

This is a simple example so users can recognize a normal successful flow:

```text
You: /start
Bot: Pixel Control Panel opens

You: /login
Bot: Please enter your Google email address

You: user@gmail.com
Bot: Email accepted. Now send your password

You: yourpassword
Bot: ✅ Session Ready
Bot: A fresh Pixel device profile is ready for this session

You: /check_offer
Bot: ⏳ Starting secure check...
Bot: 🌍 Active Proxy Panel ...
Bot: ✅ Login successful
Bot: 🎉 Gemini Pro Offer Found! 🔗 https://one.google.com/...
```

## How Users Know It Worked

- Login step is successful when the bot shows `✅ Session Ready`
- Proxy/direct check is successful when `/ip` or `/proxy` shows the active network identity
- Offer check is successful when the bot shows `🎉 Gemini Pro Offer Found!`
- If no offer exists, the bot will say no active offer was found and may attach screenshot/HTML debug artifacts

## Proxy and IP Notes

- `/proxy` shows the active proxy for the session and pool availability
- `/ip` shows the effective network identity
- `/disable_proxy` locks the session to direct/local IP
- `/rotate_proxy` re-enables proxy mode for the session and chooses another proxy
- when proxy transport fails, `/check_offer` can rotate automatically

## Debug Artifacts

When no offer is found, the bot can save:

- screenshot `.png`
- page source `.html`

Artifacts are stored under:

```text
logs/offer_debug/chat_<chat_id>/
```

This helps distinguish:

- no eligible promo
- regular paid Google AI Pro plan only
- page rendering or scanner mismatch

## BotFather Copy

### Short Description

```text
Pixel 10 Pro Google One assistant with login automation, proxy tools, IP diagnostics, and Gemini offer checking.
```

### Description

```text
This bot helps you manage secure Google One / Gemini offer checks with a modern Pixel-style control panel.

✅ Secure Login: Save a session and launch Google sign-in safely
✅ Offer Check: Scan Google One pages for Gemini / AI Pro offer availability
✅ Proxy Tools: Rotate proxy, disable proxy, or inspect IP identity in real time
✅ Session Status: Review account, device, and connection details instantly

Tap /start to open the Pixel Control Panel.
```

## Security Notes

- Credentials are kept in memory for the active session only
- Passwords are wiped after use in the offer-check flow
- Sessions expire automatically after the configured TTL
- Automation may still trigger Google security challenges depending on account risk and region context

## Troubleshooting

| Issue | Fix |
|---|---|
| You are not sure whether the bot is ready for first-time use | Run `/doctor` in Telegram and fix any warning before testing a real account |
| `No module named 'telegram'` or another missing package | Activate `.venv`, then run `pip install -r requirements.txt` again |
| `409 Conflict` | Stop duplicate `main.py` bot processes and restart one instance only |
| `/check_offer` says no credentials | Run `/login` again because the session password has already been cleared |
| Google gets stuck on an audio captcha | Set `WIT_AI_TOKEN` in `.env` so AutoPixel can try the audio challenge automatically, or finish it manually in Chrome |
| Proxy is selected but traffic still looks direct, or proxy precheck fails | Check `/proxy` and `/ip`, then rotate or replace the proxy pool, or switch to direct mode |
| No offer found | Review account region, billing profile, payments setup, and whether the promo was already claimed |
| Termux runs the bot but browser automation fails | Use Windows, Linux, or macOS with desktop Chrome for full automation support |

## Disclaimer

Use this project responsibly and only with accounts you own or are authorized to use. Automation against third-party services may be restricted by their policies or terms.
