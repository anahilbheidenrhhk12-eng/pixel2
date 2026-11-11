# Changes: English UI + Annual Offer Step 6

- Preserved original email/password/2FA sign-in control flow.
- Step 6/6 now navigates to the Google AI offer URL specified in `config.GOOGLE_ONE_AI_URL` instead of the general Google One homepage.
- Clicks **Annual**, verifies the **Google AI Pro** yearly card, and clicks **Get Google AI Pro**. Stops before payment.
- Sends one Telegram screenshot **after** clicking the Pro button. Login progress is text only.
- Replaced Chinese status text in bot automation and CLI with English.
- Added permanent Telegram keyboard and slash-command menu.
- Fixed the Login keyboard button to enter the same existing conversation handler as `/login`.
- Saved any captured checkout URL for `/get_link` without automatically sending a separate message.
- Added offline tests for the final screenshot callback and plan selection.


## Responsive Mini App and icons
- Owner-authenticated viewport fitting resizes Chrome to the viewer's width and aspect ratio.
- x11vnc streams the page region, with a default 48-pixel bottom crop. Set BROWSER_BOTTOM_CROP (0–120) to adjust it.
- Phone and desktop widths are handled independently; reconnect retries screen fitting.
- Existing admin settings, access keys and extension controls are preserved.
- Customer and native admin buttons now have icons; legacy button text remains supported.
- Removed two fixed 2-second waits before explicitly awaited sign-in fields, and the implicit timeout on optional login error detection.
- Browser sizing and final-stage operations share the session lock.
- Validation: 40 unit/integration tests and JavaScript syntax check. Live Chrome/VNC could not be exercised in the build environment.

## Faster preparation and live progress
- A single Telegram progress card shows six real stages and elapsed time, refreshed every three seconds. No estimated countdown is invented.
- Raw callbacks, emails and credentials are never rendered in the progress card.
- Disabled unused intermediate and final screenshot capture for the native customer flow.
- Removed implicit per-selector waits while scanning the Google One plan controls; explicit polling deadlines remain.
- Chromium uses eager page loading; explicit control waits continue to guard interaction.
- Stage durations are logged for diagnosis. No end-to-end speed measurement was possible without a live session.
- 44 automated tests passed.
