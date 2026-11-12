# اختبار Google One الأصلي داخل Android — مشروع pixel2

هذا التحديث موجود على فرع `android-test` فقط. لا يغيّر تشغيل بوت `PIXEL` الأصلي.

## تجربة بنقرة واحدة على Windows (الأفضل)

1. نزّل [Android Studio](https://developer.android.com/studio) و[Python 3](https://www.python.org/downloads/windows/).
2. في Android Studio افتح **More Actions → Virtual Device Manager → Create Device**.
3. اختر هاتف Pixel أو أي ملف عتاد يحمل شعار **Play Store**، ثم صورة نظام **Google Play** (يفضّل Android 17 إذا كانت متاحة) واضغط Finish.
4. شغّل `START_GOOGLE_ONE_WINDOWS.bat` بنقرتين من نفس مجلد ملفات المشروع، أو شغّل المحاكي أولًا ثم الملف.
5. السكريبت يبحث عن Android SDK وADB تلقائيًا، ويفتح المحاكي إن لم يكن مفتوحًا.
6. سجّل حساب Google من **شاشة المحاكي فقط**. بعد ذلك ثبّت Google One من Play Store عندما يفتح، وستُستكمل محاولة فتح التطبيق.
7. شوف التقرير في `native_test_results/report.json` والصور في نفس المجلد.

**تنبيه:** ليس مطلوبًا إدخال كلمة السر أو رمز 2FA في Terminal أو Telegram. لا ترسل ملفات screenshots لحساباتك إلى مستودع GitHub عام. المحاكي يختبر التطبيق الأصلي، لكنه ليس جهاز Pixel 11 Pro XL حقيقيًا وقد لا يكون مؤهلًا لعرض الستة أشهر.

## التسلسل المنفذ

1. تشغيل جهاز Android المتصل بواسطة ADB (هاتف حقيقي أو Android Studio Emulator مع Google Play).
2. فحص حساب Google داخل Android عبر AccountManager.
3. إذا لا يوجد حساب، يفتح إعدادات **Add Google Account** الرسمية، وينتظر تسجيل الدخول على شاشة الهاتف.
4. بعد نجاح تسجيل حساب Android، يثبت Google One من Play Store إذا كان غير موجود، أو يمكن توفير APK محلي للتثبيت.
5. يفتح تطبيق `com.google.android.apps.subscriptions.red` الأصلي **بنفس حساب Android**.
6. يحاول فتح **Settings → Check for offers** ويكتب تقريرًا بصيغة JSON.

## تشغيل تفاعلي على Windows

شغّل Android Studio Emulator مع صورة Google Play (Android 17، API 37)، أو وصل هاتف Android مسموحًا له بتصحيح USB.

```powershell
adb devices
py native_google_one_probe.py --interactive --wait-seconds 600 --screenshots
```

على الشاشة التي تظهر من Android:
- سجّل دخول حساب Google من واجهة Android الرسمية.
- إن لم يكن Google One مثبتًا، اضغط Install داخل Play Store.
- بعد ذلك يكمل السكريبت فتح التطبيق واكتشاف شاشة العروض.

التقرير في `native_test_results/report.json`. الصور محلية فقط عندما تفعّل `--screenshots`؛ لا ترسل صور تسجيل الدخول أو بيانات الحساب إلى مستودع عام.

بديل إذا لديك ملف APK محلي أصلي ومتوافق:

```powershell
py native_google_one_probe.py --interactive --wait-seconds 600 --apk "C:\\path\\to\\GoogleOne.apk"
```

## الاختبار الآلي على GitHub

من تبويب Actions شغّل `Google One native Android 17 test`، أو ارفع تعديلًا على ملف السكريبت.

GitHub Actions يختبر:
- تشغيل Android 17 مع KVM وGoogle Play.
- وحدة منطق الانتقال بين تسجيل Android وفتح Google One.
- اكتشاف إذا كان حساب Google أو التطبيق الأصلي مفقودًا.

**GitHub Actions غير تفاعلي**، ولن يسجّل الدخول إلى حساب Google ولا يثبت التطبيق من Play Store بدلًا عن المستخدم. النتيجة `requires_android_google_login` تعني أن التطبيق لم يختبر تسجيل الدخول الحقيقي بعد؛ نجاح CI لا يعني ظهور عرض اشتراك.

## حدود الربط مع Pixel 11 في المتصفح

جلسة تسجيل الدخول في مشروع Pixel القائم تستخدم Selenium/CDP داخل Chrome؛ تلك الجلسة **ليست حساب Android نظاميًا** ولا تنتقل إلى Google One تلقائيًا. لتشغيل Google One بنفس الحساب يجب تسجيل Google مباشرة داخل **Android نفسه** في الخطوة 3. لا يبدّل السكريبت بصمة الجهاز أو توقيع التطبيق أو أهلية عرض Google One.
