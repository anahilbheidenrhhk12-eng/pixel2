# Railway setup
1. Revoke the Telegram bot token embedded in the original uploaded config.py using @BotFather. Generate a new token.
2. Upload this folder to a PRIVATE GitHub repository (do not upload the original ZIP).
3. Railway > New Project > Deploy from GitHub Repo. Select your repository.
4. In Variables, set TELEGRAM_BOT_TOKEN to the newly generated secret. Optionally set PYTHONUNBUFFERED=1.
5. Railway should build with the root Dockerfile. Leave Start Command blank. Set replicas to 1.
6. Inspect deployment logs; then send /start to your bot.

Limitations: Google may require passkey/security-key/manual verification; a headless Railway container cannot complete a visible interactive login. Browser fingerprint spoofing does not establish offer eligibility. No guarantee of offer extraction. Credentials are handled by Telegram messages and held in process memory, which is risky; do not use important accounts. Container restarts lose sessions. Do not expose Telegram tokens or passwords in logs.
