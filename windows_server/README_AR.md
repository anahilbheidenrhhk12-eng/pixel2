# Digi Pixel Server for Windows

هذا هو السيرفر المحلي الخاص بالمحاكي. **ليس APK**.

- افتح START_PIXEL_SERVER.bat على Windows 10/11 (64-bit).
- يبدأ تنزيل Android SDK وGoogle Play Android Emulator تلقائياً عند أول تشغيل.
- يبدأ المحاكي باسم Digi_Pixel_11_Pro_XL ويحافظ على بياناته بين التشغيلات.
- إذا لم يكن تطبيق Google One مثبتاً يفتح Play Store داخل المحاكي للتثبيت مرة واحدة.
- استعمل ADD GOOGLE ACCOUNT من النافذة وسجّل الدخول على شاشة Android الرسمية.
- OPEN GOOGLE ONE APP يفتح التطبيق الأصلي داخل المحاكي.
- PIXEL CHROME (CDP) يشغّل Chrome داخل المحاكي ببصمة المتصفح الموجودة في مشروع Pixel السابق.
- CHECK FOR OFFERS يفتح Google One ويحاول الوصول إلى Settings > Check for offers.
- SCREENSHOT يلتقط صورة شاشة Android.

## ربط Railway وTelegram

نسخة ZIP المخصصة تحتوي connection.json محفوظ محلياً، ولا ترفعه إلى GitHub أو ترسله لأي شخص.
بعد تشغيل السيرفر سيظهر رقم ربط مكون من 8 أرقام.
في بوت Telegram أرسل /winpixel pair XXXXXXXX مرة واحدة، ثم /winpixel لظهور أزرار التحكم.

السيرفر يتصل بـRailway عبر HTTPS من حاسوبك، ولا يفتح ADB للإنترنت.
Android Studio غير مطلوب إن نجح التنزيل الآلي للأدوات.
يجب تفعيل Virtualization من BIOS وWindows Hypervisor Platform على الحاسوب.
المحاكي يستخدم صورة Google Play رسمية، والتطبيق يُثبت من Play Store.
ملف ZIP لا يحتوي نسخة من تطبيق Google One ولا يحزم محتوى Google المملوك.

## صيانة

- لا تحذف المجلد %LOCALAPPDATA%\DigiPixelServer لأنه يحتوي أدوات SDK.
- حسابات Google وGoogle One تحفظ في AVD تحت %USERPROFILE%\.android\avd.
- لا تدخل كلمة مرور Google في Telegram ولا في حقل الربط.
- يمكن متابعة الكود المصدري في branch android-test داخل pixel2.
