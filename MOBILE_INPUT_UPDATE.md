# Two requested changes

1. Stage-six Telegram screenshots: crop the bottom 8% (minimum 32 pixels). Applies to annual-plan selection, checkout/card-form progress, the final photo, and errors after entering stage six. Earlier screenshots, captions/icons, login timing, the extension and live browser pixels are unchanged.
2. Mini App input: an editable input bridge opens a phone keyboard and forwards text over the existing authenticated noVNC connection. Keyboard/123 choose text/numeric input. Paste supports clipboard permission with long-press fallback. Copy requests selected remote text, then offers Copy to phone (or native long-press). Next, Enter and Backspace controls are included. IME composition is sent once. Temporary input/copy buffers are cleared on disconnect or page exit, with no logging or storage.

## Use on a phone

Tap the target field in the live browser. If the phone keyboard does not open automatically, tap Keyboard or 123. Type using the input box beneath the browser. Tap Paste, or long-press that box and choose Paste if Telegram denies direct clipboard access. For copying, select text in the remote page, tap Copy, then Copy to phone.

Same deployment variables and /data volume. Replace the application files and redeploy. Pillow is added to requirements.txt for cropping; no browser engine or login workflow changes.

## Validation

47 Python tests pass. A mobile Chromium simulation with a mock noVNC transport verifies digit entry, deletion, paste, IME without duplicates, Next/Enter and the remote-copy panel. A real Android/iPhone Telegram WebView and live x11vnc text entry were not available for end-to-end verification.
