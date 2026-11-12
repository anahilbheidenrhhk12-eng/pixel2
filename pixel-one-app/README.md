# Digi Pixel One for Android

Standalone Android tester APK built in the existing pixel2 repository on the android-test branch.

## One-tap actions

- Open Google One launches the actual installed Google One Android app, or directs to the official Play Store listing if missing.
- Pixel browser mode opens the Google One web page using a Pixel 11 Pro XL Android 17 WebView user-agent and basic navigator hardware fields.
- Add / Switch Google Account opens the official Android Accounts settings. The app does not collect passwords or 2FA codes.

The embedded Pixel browser and Google One native Android app are separate contexts; browser user-agent settings do not change the Android OS model or the signed native app.

## APK installation

Download the artifact DigiPixelOne-APK from the Build Digi Pixel One APK workflow under GitHub Actions and extract app-debug.apk. Install it on an Android phone running Android 8 or later.

The app is self-contained. It does not need Phonebox, Railway Android emulator, or the Telegram bot. The app does not request contacts, SMS, camera, location, or account-reading permissions.

## Development

Open pixel-one-app/ in Android Studio with JDK 17 and Android SDK 35, then Build > Build APK(s). Debug builds use the standard Android debug signing key. This project is for testing and should not be published as a Google-affiliated application.
