# DigiPro — Native Telegram Admin & Customer Flow

Read SETUP_AR.md for deployment and upgrade instructions.

Customer keyboard: LOGIN, WALLET, ORDER, SUPPORT, API. CANCEL is available during the flow. ADMIN is shown only to configured administrators. Native persistent Telegram keyboards replace the web admin dashboard. Telegram users can still hide/show their keyboard themselves.

LOGIN prompts for a plain 12-character activation code and then the named email, password, two-factor and preparation steps. Existing long codes remain valid. One code permits one successful Google login; it is consumed even when a subsequent final-stage action fails. An unused code remains retryable by its bound owner if login fails.

The existing Chrome/Xvfb/x11vnc/noVNC browser is preserved and becomes available only at the final stage. There is no session countdown. Session browsers end on explicit cancellation, configured completion, or service restart.

WALLET counts bound, unused login codes (not cash). ORDER shows the caller's history and reconnect button. SUPPORT stores tickets for administrator replies. API supplies read-only owner-scoped wallet/orders endpoints using a resettable personal bearer token.

Deploy the included Dockerfile. Set TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_IDS, PUBLIC_BASE_URL and DATA_DIR=/data. Attach a persistent volume to /data. Run one service replica. Existing admin.sqlite3 data is retained and new support/API tables are added automatically.

Tests: python -m unittest discover -s tests -v
