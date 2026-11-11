"""Customer-facing language support: en / ar / vi / es, chosen by each customer.

Only customer screens are translated (menus, login flow, wallet, buy, join gate,
progress card, final browser). The ADMIN panel stays in English on purpose.
Admin-authored free text (maintenance message, instructions, top-up
instructions) is shown exactly as the admin wrote it, in whatever language
that was, because the admin may already have written it in Arabic.
"""
from admin_store import STORE

LANGS = ('en', 'ar', 'vi', 'es')
DEFAULT_LANG = 'en'
RTL_LANGS = {'ar'}

LANG_NAMES = {
    'en': '🇬🇧 English',
    'ar': '🇸🇦 العربية',
    'vi': '🇻🇳 Tiếng Việt',
    'es': '🇪🇸 Español',
}


def init():
    with STORE.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS user_lang(owner INTEGER PRIMARY KEY, lang TEXT)')


def get(uid):
    """The customer's saved language, or None if they have not picked one yet."""
    init()
    with STORE.db() as db:
        row = db.execute('SELECT lang FROM user_lang WHERE owner=?', (uid,)).fetchone()
    lang = row[0] if row else None
    return lang if lang in LANGS else None


def set_lang(uid, lang):
    if lang not in LANGS:
        raise ValueError('Unknown language')
    init()
    with STORE.db() as db:
        db.execute('INSERT OR REPLACE INTO user_lang VALUES (?,?)', (uid, lang))
    return lang


def resolve(uid):
    """The customer's language, defaulting to English until they pick one."""
    return get(uid) or DEFAULT_LANG


def is_rtl(lang):
    return lang in RTL_LANGS


# ── Translation table ────────────────────────────────────────────────────────
# key -> {lang: text}; "{placeholders}" use str.format().

T = {
    'choose_language': {
        'en': '🌐 Please choose your language:',
        'ar': '🌐 اختر لغتك من فضلك:',
        'vi': '🌐 Vui lòng chọn ngôn ngữ của bạn:',
        'es': '🌐 Por favor elige tu idioma:',
    },
    'language_saved': {
        'en': '✅ Language set to English.',
        'ar': '✅ تم تعيين اللغة إلى العربية.',
        'vi': '✅ Đã đặt ngôn ngữ thành Tiếng Việt.',
        'es': '✅ Idioma establecido en Español.',
    },
    'btn_buy': {'en': '🛒 BUY', 'ar': '🛒 شراء', 'vi': '🛒 MUA', 'es': '🛒 COMPRAR'},
    'btn_login': {'en': '🔐 LOGIN', 'ar': '🔐 تسجيل الدخول', 'vi': '🔐 ĐĂNG NHẬP', 'es': '🔐 INICIAR SESIÓN'},
    'btn_wallet': {'en': '👛 WALLET', 'ar': '👛 المحفظة', 'vi': '👛 VÍ TIỀN', 'es': '👛 BILLETERA'},
    'btn_order': {'en': '🛍️ ORDER', 'ar': '🛍️ الطلبات', 'vi': '🛍️ ĐƠN HÀNG', 'es': '🛍️ PEDIDOS'},
    'btn_support': {'en': '💬 SUPPORT', 'ar': '💬 الدعم', 'vi': '💬 HỖ TRỢ', 'es': '💬 SOPORTE'},
    'btn_api': {'en': '🔌 API', 'ar': '🔌 API', 'vi': '🔌 API', 'es': '🔌 API'},
    'btn_lang': {'en': '🌐 LANGUAGE', 'ar': '🌐 اللغة', 'vi': '🌐 NGÔN NGỮ', 'es': '🌐 IDIOMA'},
    'btn_admin': {'en': '🛠️ ADMIN', 'ar': '🛠️ الإدارة', 'vi': '🛠️ QUẢN TRỊ', 'es': '🛠️ ADMIN'},
    'btn_cancel': {'en': '❌ CANCEL', 'ar': '❌ إلغاء', 'vi': '❌ HỦY', 'es': '❌ CANCELAR'},
    'placeholder_menu': {
        'en': 'Select an option',
        'ar': 'اختر خيارًا',
        'vi': 'Chọn một tùy chọn',
        'es': 'Selecciona una opción',
    },

    'welcome': {
        'en': ('🤖 DIGIPRO • ACCOUNT SERVICES\n\nWelcome. Select an option below.\n\n'
               '🔐 LOGIN — Start with your activation code\n'
               '🛒 BUY — Buy activation codes (same wallet as the store)\n'
               '👛 WALLET — Your available login credits\n'
               '🛍️ ORDER — Your order history\n'
               '💬 SUPPORT — Contact support\n'
               '🔌 API — Personal API access\n'
               '🌐 LANGUAGE — Change language'),
        'ar': ('🤖 ديجي برو • خدمات الحساب\n\nمرحبًا بك. اختر خيارًا بالأسفل.\n\n'
               '🔐 تسجيل الدخول — ابدأ بكود التفعيل الخاص بك\n'
               '🛒 شراء — اشترِ أكواد تفعيل (نفس محفظة المتجر)\n'
               '👛 المحفظة — رصيد الدخول المتوفر لديك\n'
               '🛍️ الطلبات — سجل طلباتك\n'
               '💬 الدعم — تواصل مع الدعم\n'
               '🔌 API — وصول API شخصي\n'
               '🌐 اللغة — تغيير اللغة'),
        'vi': ('🤖 DIGIPRO • DỊCH VỤ TÀI KHOẢN\n\nChào mừng. Chọn một tùy chọn bên dưới.\n\n'
               '🔐 ĐĂNG NHẬP — Bắt đầu bằng mã kích hoạt của bạn\n'
               '🛒 MUA — Mua mã kích hoạt (cùng ví với cửa hàng)\n'
               '👛 VÍ TIỀN — Số lượt đăng nhập bạn có\n'
               '🛍️ ĐƠN HÀNG — Lịch sử đơn hàng của bạn\n'
               '💬 HỖ TRỢ — Liên hệ hỗ trợ\n'
               '🔌 API — Quyền truy cập API cá nhân\n'
               '🌐 NGÔN NGỮ — Đổi ngôn ngữ'),
        'es': ('🤖 DIGIPRO • SERVICIOS DE CUENTA\n\nBienvenido. Elige una opción abajo.\n\n'
               '🔐 INICIAR SESIÓN — Empieza con tu código de activación\n'
               '🛒 COMPRAR — Compra códigos de activación (misma billetera que la tienda)\n'
               '👛 BILLETERA — Tus créditos de inicio de sesión disponibles\n'
               '🛍️ PEDIDOS — Tu historial de pedidos\n'
               '💬 SOPORTE — Contacta con soporte\n'
               '🔌 API — Acceso API personal\n'
               '🌐 IDIOMA — Cambiar idioma'),
    },
    'private_only': {
        'en': 'Please open a private chat with this bot.',
        'ar': 'يرجى فتح محادثة خاصة مع هذا البوت.',
        'vi': 'Vui lòng mở trò chuyện riêng với bot này.',
        'es': 'Por favor abre un chat privado con este bot.',
    },
    'instructions_title': {
        'en': '📘 INSTRUCTIONS',
        'ar': '📘 التعليمات',
        'vi': '📘 HƯỚNG DẪN',
        'es': '📘 INSTRUCCIONES',
    },
    'instructions_continue_btn': {
        'en': '✅ I understand — Continue',
        'ar': '✅ فهمت — متابعة',
        'vi': '✅ Tôi đã hiểu — Tiếp tục',
        'es': '✅ Entendido — Continuar',
    },
    'step1_code': {
        'en': '🎟️ STEP 1 OF 5 • ACTIVATION CODE\n\nSend your activation code only. Example: A7KM9PX4RD2W\nEach code allows one successful login.',
        'ar': '🎟️ الخطوة 1 من 5 • كود التفعيل\n\nأرسل كود التفعيل فقط. مثال: A7KM9PX4RD2W\nكل كود يسمح بتسجيل دخول ناجح واحد.',
        'vi': '🎟️ BƯỚC 1/5 • MÃ KÍCH HOẠT\n\nChỉ gửi mã kích hoạt của bạn. Ví dụ: A7KM9PX4RD2W\nMỗi mã cho phép một lần đăng nhập thành công.',
        'es': '🎟️ PASO 1 DE 5 • CÓDIGO DE ACTIVACIÓN\n\nEnvía solo tu código de activación. Ejemplo: A7KM9PX4RD2W\nCada código permite un inicio de sesión exitoso.',
    },
    'too_many_codes': {
        'en': 'Too many invalid codes. Please wait one minute and try again.',
        'ar': 'عدد كبير من الأكواد الخاطئة. يرجى الانتظار دقيقة والمحاولة مرة أخرى.',
        'vi': 'Quá nhiều mã không hợp lệ. Vui lòng đợi một phút và thử lại.',
        'es': 'Demasiados códigos no válidos. Espera un minuto e inténtalo de nuevo.',
    },
    'invalid_code': {
        'en': 'Invalid, used, revoked or already assigned code.',
        'ar': 'الكود غير صالح، أو مستعمل، أو ملغى، أو مستخدم من قبل.',
        'vi': 'Mã không hợp lệ, đã dùng, đã bị thu hồi hoặc đã được gán.',
        'es': 'Código no válido, usado, revocado o ya asignado.',
    },
    'step2_email': {
        'en': '📧 STEP 2 OF 5 • EMAIL\n\nCode accepted. Send your Gmail address.',
        'ar': '📧 الخطوة 2 من 5 • البريد الإلكتروني\n\nتم قبول الكود. أرسل عنوان بريدك الإلكتروني (Gmail).',
        'vi': '📧 BƯỚC 2/5 • EMAIL\n\nMã đã được chấp nhận. Gửi địa chỉ Gmail của bạn.',
        'es': '📧 PASO 2 DE 5 • CORREO\n\nCódigo aceptado. Envía tu dirección de Gmail.',
    },
    'invalid_email': {
        'en': 'Please send a valid email address, or select CANCEL.',
        'ar': 'يرجى إرسال عنوان بريد إلكتروني صالح، أو اختر إلغاء.',
        'vi': 'Vui lòng gửi địa chỉ email hợp lệ, hoặc chọn HỦY.',
        'es': 'Envía una dirección de correo válida, o selecciona CANCELAR.',
    },
    'step3_password': {
        'en': '🔒 STEP 3 OF 5 • PASSWORD\n\nSend your password. Your message will be deleted when possible.',
        'ar': '🔒 الخطوة 3 من 5 • كلمة السر\n\nأرسل كلمة السر. سيتم حذف رسالتك عند الإمكان.',
        'vi': '🔒 BƯỚC 3/5 • MẬT KHẨU\n\nGửi mật khẩu của bạn. Tin nhắn sẽ được xóa nếu có thể.',
        'es': '🔒 PASO 3 DE 5 • CONTRASEÑA\n\nEnvía tu contraseña. Tu mensaje se eliminará cuando sea posible.',
    },
    'step4_totp': {
        'en': '🔐 STEP 4 OF 5 • TWO-FACTOR AUTHENTICATION (REQUIRED)\n\nTwo-factor authentication must be enabled on this account. Send your authenticator secret key (the long letters/numbers code shown when you set up Google Authenticator — not a 6-digit code). Your message will be deleted when possible.',
        'ar': '🔐 الخطوة 4 من 5 • المصادقة الثنائية (إلزامية)\n\nيجب أن تكون المصادقة الثنائية مفعّلة على هذا الحساب. أرسل المفتاح السري للمصادقة (الرمز الطويل من حروف وأرقام الذي ظهر عند تفعيل Google Authenticator — ليس رمز الـ6 أرقام). سيتم حذف رسالتك عند الإمكان.',
        'vi': '🔐 BƯỚC 4/5 • XÁC THỰC HAI YẾU TỐ (BẮT BUỘC)\n\nTài khoản này phải bật xác thực hai yếu tố. Gửi khóa bí mật xác thực (mã chữ/số dài hiện khi bạn thiết lập Google Authenticator — không phải mã 6 số). Tin nhắn sẽ được xóa nếu có thể.',
        'es': '🔐 PASO 4 DE 5 • VERIFICACIÓN EN DOS PASOS (OBLIGATORIA)\n\nLa verificación en dos pasos debe estar activada en esta cuenta. Envía tu clave secreta del autenticador (el código largo de letras/números que aparece al configurar Google Authenticator, no el código de 6 dígitos). Tu mensaje se eliminará cuando sea posible.',
    },
    'invalid_totp': {
        'en': "⚠️ That doesn't look like a valid authenticator secret key. Two-factor authentication is required — enable it on the account, then send the long letters/numbers secret key (not a 6-digit code).",
        'ar': '⚠️ هذا لا يشبه مفتاح مصادقة صالح. المصادقة الثنائية إلزامية — فعّلها على الحساب، ثم أرسل المفتاح السري الطويل (حروف وأرقام)، وليس رمز الـ6 أرقام.',
        'vi': '⚠️ Mã này không giống khóa bí mật xác thực hợp lệ. Xác thực hai yếu tố là bắt buộc — hãy bật nó trên tài khoản, rồi gửi khóa bí mật dài (chữ/số), không phải mã 6 số.',
        'es': '⚠️ Eso no parece una clave secreta de autenticador válida. La verificación en dos pasos es obligatoria — actívala en la cuenta y envía la clave secreta larga (letras/números), no el código de 6 dígitos.',
    },
    'active_browser': {
        'en': 'A browser is active. Use /payment to reconnect or /close_checkout to close it.',
        'ar': 'يوجد متصفح نشط حاليًا. استخدم /payment لإعادة الاتصال أو /close_checkout لإغلاقه.',
        'vi': 'Có một trình duyệt đang hoạt động. Dùng /payment để kết nối lại hoặc /close_checkout để đóng.',
        'es': 'Hay un navegador activo. Usa /payment para reconectar o /close_checkout para cerrarlo.',
    },
    'cancelled': {
        'en': 'Cancelled. You can start again from the menu. A code already used for a successful login stays used.',
        'ar': 'تم الإلغاء. يمكنك البدء من جديد من القائمة. الكود الذي تم استخدامه لتسجيل دخول ناجح يبقى مستعملًا.',
        'vi': 'Đã hủy. Bạn có thể bắt đầu lại từ menu. Mã đã dùng cho một lần đăng nhập thành công vẫn được tính là đã dùng.',
        'es': 'Cancelado. Puedes empezar de nuevo desde el menú. Un código ya usado para un inicio de sesión exitoso sigue marcado como usado.',
    },
    'menu_fallback': {
        'en': 'Select LOGIN to begin, or choose an option below.',
        'ar': 'اختر تسجيل الدخول للبدء، أو اختر خيارًا بالأسفل.',
        'vi': 'Chọn ĐĂNG NHẬP để bắt đầu, hoặc chọn một tùy chọn bên dưới.',
        'es': 'Selecciona INICIAR SESIÓN para empezar, o elige una opción abajo.',
    },

    'wallet_title': {
        'en': 'WALLET',
        'ar': 'المحفظة',
        'vi': 'VÍ TIỀN',
        'es': 'BILLETERA',
    },
    'wallet_body': {
        'en': 'Available login credits: {n}\nEach accepted, unused activation code represents one login credit.\nUse LOGIN to redeem a code, or BUY to get more.',
        'ar': 'رصيد تسجيل الدخول المتوفر: {n}\nكل كود تفعيل مقبول وغير مستخدم يمثل رصيد تسجيل دخول واحد.\nاستخدم تسجيل الدخول لاستبدال كود، أو شراء للحصول على المزيد.',
        'vi': 'Số lượt đăng nhập khả dụng: {n}\nMỗi mã kích hoạt đã nhận và chưa dùng tương ứng với một lượt đăng nhập.\nDùng ĐĂNG NHẬP để sử dụng mã, hoặc MUA để có thêm.',
        'es': 'Créditos de inicio de sesión disponibles: {n}\nCada código de activación aceptado y sin usar representa un crédito de inicio de sesión.\nUsa INICIAR SESIÓN para usar un código, o COMPRAR para obtener más.',
    },
    'wallet_topup_btn': {
        'en': '💰 Top up wallet',
        'ar': '💰 شحن المحفظة',
        'vi': '💰 Nạp tiền vào ví',
        'es': '💰 Recargar billetera',
    },
    'wallet_howto_btn': {
        'en': 'ℹ️ How to add balance',
        'ar': 'ℹ️ كيفية إضافة رصيد',
        'vi': 'ℹ️ Cách nạp số dư',
        'es': 'ℹ️ Cómo añadir saldo',
    },
    'store_wallet_unavailable': {
        'en': 'Store wallet: unavailable right now.',
        'ar': 'محفظة المتجر: غير متوفرة حاليًا.',
        'vi': 'Ví cửa hàng: hiện không khả dụng.',
        'es': 'Billetera de la tienda: no disponible ahora.',
    },
    'store_wallet_balance': {
        'en': 'Store wallet balance: {money} (the same wallet as the store bot)',
        'ar': 'رصيد محفظة المتجر: {money} (نفس محفظة بوت المتجر)',
        'vi': 'Số dư ví cửa hàng: {money} (cùng ví với bot cửa hàng)',
        'es': 'Saldo de la billetera de la tienda: {money} (la misma billetera que el bot de la tienda)',
    },
    'store_wallet_open_once': {
        'en': 'Store wallet: open the store bot once to create your account.',
        'ar': 'محفظة المتجر: افتح بوت المتجر مرة واحدة لإنشاء حسابك.',
        'vi': 'Ví cửa hàng: mở bot cửa hàng một lần để tạo tài khoản của bạn.',
        'es': 'Billetera de la tienda: abre el bot de la tienda una vez para crear tu cuenta.',
    },
    'recent_purchases': {
        'en': 'Recent purchases:',
        'ar': 'المشتريات الأخيرة:',
        'vi': 'Giao dịch mua gần đây:',
        'es': 'Compras recientes:',
    },

    'order_title': {
        'en': 'ORDER HISTORY',
        'ar': 'سجل الطلبات',
        'vi': 'LỊCH SỬ ĐƠN HÀNG',
        'es': 'HISTORIAL DE PEDIDOS',
    },
    'order_empty': {
        'en': 'No orders yet. Select LOGIN to start.',
        'ar': 'لا توجد طلبات حتى الآن. اختر تسجيل الدخول للبدء.',
        'vi': 'Chưa có đơn hàng nào. Chọn ĐĂNG NHẬP để bắt đầu.',
        'es': 'Aún no hay pedidos. Selecciona INICIAR SESIÓN para empezar.',
    },
    'order_status': {'en': 'Status', 'ar': 'الحالة', 'vi': 'Trạng thái', 'es': 'Estado'},
    'order_review': {'en': 'Review', 'ar': 'المراجعة', 'vi': 'Đánh giá', 'es': 'Revisión'},
    'order_pending': {'en': 'Pending', 'ar': 'قيد الانتظار', 'vi': 'Đang chờ', 'es': 'Pendiente'},

    'support_title': {
        'en': 'SUPPORT',
        'ar': 'الدعم',
        'vi': 'HỖ TRỢ',
        'es': 'SOPORTE',
    },
    'support_prompt': {
        'en': 'Describe your issue in one message. Do not include passwords or payment details.\nSelect CANCEL to return.',
        'ar': 'اشرح مشكلتك في رسالة واحدة. لا تدرج كلمات السر أو تفاصيل الدفع.\nاختر إلغاء للرجوع.',
        'vi': 'Hãy mô tả vấn đề của bạn trong một tin nhắn. Không gửi mật khẩu hoặc thông tin thanh toán.\nChọn HỦY để quay lại.',
        'es': 'Describe tu problema en un mensaje. No incluyas contraseñas ni datos de pago.\nSelecciona CANCELAR para volver.',
    },
    'support_too_long': {
        'en': 'Please keep your message under 3000 characters.',
        'ar': 'يرجى أن تكون رسالتك أقل من 3000 حرف.',
        'vi': 'Vui lòng giữ tin nhắn của bạn dưới 3000 ký tự.',
        'es': 'Mantén tu mensaje por debajo de 3000 caracteres.',
    },
    'support_created': {
        'en': 'Support ticket #{id} created. The administrator can review it in the bot.',
        'ar': 'تم إنشاء تذكرة الدعم رقم #{id}. يمكن للمسؤول مراجعتها في البوت.',
        'vi': 'Đã tạo yêu cầu hỗ trợ #{id}. Quản trị viên có thể xem trong bot.',
        'es': 'Ticket de soporte #{id} creado. El administrador puede revisarlo en el bot.',
    },

    'api_title': {
        'en': 'API ACCESS\n\nRead your own wallet credits and order history. Browser/login automation is not exposed through this API.\nGenerate a personal API key below. Regenerating invalidates your previous key.',
        'ar': 'الوصول عبر API\n\nاقرأ رصيد محفظتك وسجل طلباتك. لا تتوفر أتمتة المتصفح/تسجيل الدخول عبر هذا API.\nولّد مفتاح API شخصيًا بالأسفل. إعادة التوليد تُلغي المفتاح السابق.',
        'vi': 'TRUY CẬP API\n\nXem số dư và lịch sử đơn hàng của bạn. API này không hỗ trợ tự động hóa trình duyệt/đăng nhập.\nTạo khóa API cá nhân bên dưới. Tạo lại sẽ hủy khóa cũ.',
        'es': 'ACCESO API\n\nConsulta tu saldo y tu historial de pedidos. La automatización de navegador/inicio de sesión no está disponible por esta API.\nGenera tu clave API personal abajo. Regenerarla invalida la anterior.',
    },
    'api_generate_btn': {
        'en': 'Generate / reset API key',
        'ar': 'توليد / إعادة تعيين مفتاح API',
        'vi': 'Tạo / đặt lại khóa API',
        'es': 'Generar / restablecer clave API',
    },
    'api_private_only': {
        'en': 'Private chat only',
        'ar': 'المحادثة الخاصة فقط',
        'vi': 'Chỉ trò chuyện riêng tư',
        'es': 'Solo chat privado',
    },
    'api_key_message': {
        'en': 'API key (keep private):\n{token}\n\nAuthorization: Bearer YOUR_KEY\n\nGET {url}/api/v1/wallet\nGET {url}/api/v1/orders',
        'ar': 'مفتاح API (احتفظ به سريًا):\n{token}\n\nAuthorization: Bearer YOUR_KEY\n\nGET {url}/api/v1/wallet\nGET {url}/api/v1/orders',
        'vi': 'Khóa API (giữ kín):\n{token}\n\nAuthorization: Bearer YOUR_KEY\n\nGET {url}/api/v1/wallet\nGET {url}/api/v1/orders',
        'es': 'Clave API (manténla privada):\n{token}\n\nAuthorization: Bearer YOUR_KEY\n\nGET {url}/api/v1/wallet\nGET {url}/api/v1/orders',
    },

    'buy_unavailable': {
        'en': 'BUY is not available yet. Please contact support.',
        'ar': 'الشراء غير متوفر حاليًا. يرجى التواصل مع الدعم.',
        'vi': 'Chức năng MUA chưa khả dụng. Vui lòng liên hệ hỗ trợ.',
        'es': 'COMPRAR no está disponible todavía. Contacta con soporte.',
    },
    'buy_disabled': {
        'en': 'Activation codes are not on sale right now. Please check back soon.',
        'ar': 'أكواد التفعيل غير معروضة للبيع حاليًا. يرجى المحاولة لاحقًا.',
        'vi': 'Mã kích hoạt hiện không được bán. Vui lòng quay lại sau.',
        'es': 'Los códigos de activación no están en venta ahora. Vuelve a consultar pronto.',
    },
    'buy_header': {
        'en': '🛒 BUY ACTIVATION CODES\n\nPrice: {price} per code. You pay from the same wallet you use in the store.{bal}\n\nHow many codes?',
        'ar': '🛒 شراء أكواد التفعيل\n\nالسعر: {price} لكل كود. تدفع من نفس المحفظة التي تستخدمها في المتجر.{bal}\n\nكم كودًا تريد؟',
        'vi': '🛒 MUA MÃ KÍCH HOẠT\n\nGiá: {price} mỗi mã. Bạn thanh toán từ cùng ví dùng trong cửa hàng.{bal}\n\nBạn muốn mua bao nhiêu mã?',
        'es': '🛒 COMPRAR CÓDIGOS DE ACTIVACIÓN\n\nPrecio: {price} por código. Pagas desde la misma billetera que usas en la tienda.{bal}\n\n¿Cuántos códigos quieres?',
    },
    'buy_wallet_line': {
        'en': '\nYour wallet: {money}',
        'ar': '\nمحفظتك: {money}',
        'vi': '\nVí của bạn: {money}',
        'es': '\nTu billetera: {money}',
    },
    'buy_n_btn': {
        'en': 'Buy {n} — {price}',
        'ar': 'شراء {n} — {price}',
        'vi': 'Mua {n} — {price}',
        'es': 'Comprar {n} — {price}',
    },
    'buy_howto_title': {
        'en': '💰 HOW TO ADD BALANCE\n\n{guide}',
        'ar': '💰 كيفية إضافة رصيد\n\n{guide}',
        'vi': '💰 CÁCH NẠP SỐ DƯ\n\n{guide}',
        'es': '💰 CÓMO AÑADIR SALDO\n\n{guide}',
    },
    'buy_back_btn': {
        'en': '🛒 Back to BUY',
        'ar': '🛒 رجوع للشراء',
        'vi': '🛒 Quay lại MUA',
        'es': '🛒 Volver a COMPRAR',
    },
    'buy_still_processing': {
        'en': 'Your purchase is still being processed…',
        'ar': 'طلبك لا يزال قيد المعالجة…',
        'vi': 'Đơn mua của bạn vẫn đang được xử lý…',
        'es': 'Tu compra todavía se está procesando…',
    },
    'buy_processing': {
        'en': 'Processing…',
        'ar': 'جارٍ المعالجة…',
        'vi': 'Đang xử lý…',
        'es': 'Procesando…',
    },
    'buy_restart': {
        'en': 'Please start again with BUY.',
        'ar': 'يرجى البدء من جديد باستخدام شراء.',
        'vi': 'Vui lòng bắt đầu lại bằng MUA.',
        'es': 'Vuelve a empezar con COMPRAR.',
    },
    'buy_issued': {
        'en': '✅ PURCHASE COMPLETE\n\nYour activation code{plural}:\n\n{codes}\n\nSelect LOGIN and send the code to begin. Each code allows one successful login.',
        'ar': '✅ اكتملت عملية الشراء\n\nكود (أكواد) التفعيل الخاص بك:\n\n{codes}\n\nاختر تسجيل الدخول وأرسل الكود للبدء. كل كود يسمح بتسجيل دخول ناجح واحد.',
        'vi': '✅ MUA HÀNG HOÀN TẤT\n\nMã kích hoạt của bạn:\n\n{codes}\n\nChọn ĐĂNG NHẬP và gửi mã để bắt đầu. Mỗi mã cho phép một lần đăng nhập thành công.',
        'es': '✅ COMPRA COMPLETADA\n\nTu(s) código(s) de activación:\n\n{codes}\n\nSelecciona INICIAR SESIÓN y envía el código para empezar. Cada código permite un inicio de sesión exitoso.',
    },
    'buy_issued_balance': {
        'en': 'Wallet balance: {money}',
        'ar': 'رصيد المحفظة: {money}',
        'vi': 'Số dư ví: {money}',
        'es': 'Saldo de la billetera: {money}',
    },
    'buy_insufficient': {
        'en': 'Not enough balance.\nYou have {have}; this needs {need} (you are {missing} short).\n\n💰 HOW TO ADD BALANCE\n{guide}',
        'ar': 'الرصيد غير كافٍ.\nلديك {have}؛ هذا يتطلب {need} (ينقصك {missing}).\n\n💰 كيفية إضافة رصيد\n{guide}',
        'vi': 'Không đủ số dư.\nBạn có {have}; cần {need} (thiếu {missing}).\n\n💰 CÁCH NẠP SỐ DƯ\n{guide}',
        'es': 'Saldo insuficiente.\nTienes {have}; se necesitan {need} (te faltan {missing}).\n\n💰 CÓMO AÑADIR SALDO\n{guide}',
    },
    'buy_added_now_btn': {
        'en': "✅ I've added balance — buy {n} now",
        'ar': '✅ أضفت الرصيد — اشترِ {n} الآن',
        'vi': '✅ Tôi đã nạp tiền — mua {n} ngay',
        'es': '✅ Ya añadí saldo — comprar {n} ahora',
    },
    'buy_no_account': {
        'en': 'You need an account in the store bot first (it also holds your wallet). Open it once, then come back and select BUY.',
        'ar': 'تحتاج أولًا إلى حساب في بوت المتجر (فيه محفظتك أيضًا). افتحه مرة واحدة، ثم رجع واختر شراء.',
        'vi': 'Bạn cần có tài khoản trong bot cửa hàng trước (nơi lưu ví của bạn). Mở nó một lần, rồi quay lại và chọn MUA.',
        'es': 'Primero necesitas una cuenta en el bot de la tienda (ahí está tu billetera). Ábrelo una vez y vuelve a seleccionar COMPRAR.',
    },
    'buy_open_store_btn': {
        'en': 'Open the store bot',
        'ar': 'افتح بوت المتجر',
        'vi': 'Mở bot cửa hàng',
        'es': 'Abrir el bot de la tienda',
    },
    'buy_banned': {
        'en': 'This account cannot make purchases. Please contact support.',
        'ar': 'لا يمكن لهذا الحساب إجراء عمليات شراء. يرجى التواصل مع الدعم.',
        'vi': 'Tài khoản này không thể mua hàng. Vui lòng liên hệ hỗ trợ.',
        'es': 'Esta cuenta no puede realizar compras. Contacta con soporte.',
    },
    'buy_pending': {
        'en': '⏳ Your payment is being confirmed. Your code will be sent here automatically within a few minutes. You do not need to pay again.',
        'ar': '⏳ جاري تأكيد دفعتك. سيتم إرسال كودك هنا تلقائيًا في غضون دقائق. لا حاجة للدفع مرة أخرى.',
        'vi': '⏳ Thanh toán của bạn đang được xác nhận. Mã sẽ được gửi tự động trong vài phút. Bạn không cần thanh toán lại.',
        'es': '⏳ Tu pago se está confirmando. Tu código se enviará aquí automáticamente en unos minutos. No necesitas pagar de nuevo.',
    },
    'buy_error': {
        'en': 'Something went wrong and you were not charged for an unusable code. {note}\nPlease contact support if your wallet balance looks wrong.',
        'ar': 'حدث خطأ ولم يتم خصم أي رصيد مقابل كود غير صالح. {note}\nيرجى التواصل مع الدعم إذا بدا رصيد محفظتك غير صحيح.',
        'vi': 'Đã xảy ra lỗi và bạn không bị trừ tiền cho mã không dùng được. {note}\nVui lòng liên hệ hỗ trợ nếu số dư ví của bạn có vẻ không đúng.',
        'es': 'Algo salió mal y no se te cobró por un código inutilizable. {note}\nContacta con soporte si el saldo de tu billetera se ve incorrecto.',
    },

    'join_prompt_title': {
        'en': '📢 JOIN OUR CHANNEL FIRST\n\nTo use this bot, please join our channel:\n1. Tap "Join channel".\n2. Come back here and tap "✅ I joined — Continue".',
        'ar': '📢 انضم إلى قناتنا أولًا\n\nلاستخدام هذا البوت، يرجى الانضمام إلى قناتنا:\n1. اضغط على "الانضمام للقناة".\n2. رجع إلى هنا واضغط "✅ انضممت — متابعة".',
        'vi': '📢 HÃY THAM GIA KÊNH CỦA CHÚNG TÔI TRƯỚC\n\nĐể dùng bot này, vui lòng tham gia kênh:\n1. Nhấn "Tham gia kênh".\n2. Quay lại đây và nhấn "✅ Tôi đã tham gia — Tiếp tục".',
        'es': '📢 ÚNETE PRIMERO A NUESTRO CANAL\n\nPara usar este bot, únete a nuestro canal:\n1. Toca "Unirse al canal".\n2. Vuelve aquí y toca "✅ Ya me uní — Continuar".',
    },
    'join_channel_btn': {
        'en': '📢 Join channel',
        'ar': '📢 الانضمام للقناة',
        'vi': '📢 Tham gia kênh',
        'es': '📢 Unirse al canal',
    },
    'join_continue_btn': {
        'en': '✅ I joined — Continue',
        'ar': '✅ انضممت — متابعة',
        'vi': '✅ Tôi đã tham gia — Tiếp tục',
        'es': '✅ Ya me uní — Continuar',
    },
    'join_please_first': {
        'en': 'Please join our channel first.',
        'ar': 'يرجى الانضمام إلى قناتنا أولًا.',
        'vi': 'Vui lòng tham gia kênh của chúng tôi trước.',
        'es': 'Únete primero a nuestro canal.',
    },
    'join_not_yet': {
        'en': 'You have not joined yet. Join the channel, then tap again.',
        'ar': 'لم تنضم بعد. انضم إلى القناة، ثم اضغط مرة أخرى.',
        'vi': 'Bạn chưa tham gia. Hãy tham gia kênh, rồi nhấn lại.',
        'es': 'Aún no te has unido. Únete al canal y vuelve a tocar.',
    },
    'join_thanks': {
        'en': '✅ Thank you! Select an option below.',
        'ar': '✅ شكرًا لك! اختر خيارًا بالأسفل.',
        'vi': '✅ Cảm ơn bạn! Chọn một tùy chọn bên dưới.',
        'es': '✅ ¡Gracias! Elige una opción abajo.',
    },

    'ready_title': {
        'en': 'READY • FINAL BROWSER',
        'ar': 'جاهز • المتصفح النهائي',
        'vi': 'SẴN SÀNG • TRÌNH DUYỆT CUỐI',
        'es': 'LISTO • NAVEGADOR FINAL',
    },
    'ready_body': {
        'en': ('Your private browser is ready.\n\n'
               'Tap LIVE BROWSER to continue. '
               'Do not send card numbers, expiry dates, or CVV into Telegram.\n\n'
               'You control the final payment confirmation. '
               'There is no session countdown. Close the browser when finished.'),
        'ar': ('متصفحك الخاص جاهز الآن.\n\n'
               'اضغط على المتصفح المباشر للمتابعة. '
               'لا ترسل أرقام البطاقة أو تاريخ الانتهاء أو CVV داخل تيليجرام.\n\n'
               'أنت من يتحكم في تأكيد الدفع النهائي. '
               'لا يوجد عداد زمني للجلسة. أغلق المتصفح عند الانتهاء.'),
        'vi': ('Trình duyệt riêng tư của bạn đã sẵn sàng.\n\n'
               'Nhấn TRÌNH DUYỆT TRỰC TIẾP để tiếp tục. '
               'Không gửi số thẻ, ngày hết hạn hoặc CVV vào Telegram.\n\n'
               'Bạn kiểm soát việc xác nhận thanh toán cuối cùng. '
               'Không có đồng hồ đếm ngược phiên. Hãy đóng trình duyệt khi hoàn tất.'),
        'es': ('Tu navegador privado está listo.\n\n'
               'Toca NAVEGADOR EN VIVO para continuar. '
               'No envíes números de tarjeta, fecha de vencimiento ni CVV por Telegram.\n\n'
               'Tú controlas la confirmación final del pago. '
               'No hay cuenta atrás de sesión. Cierra el navegador cuando termines.'),
    },
    'live_browser_btn': {
        'en': 'LIVE BROWSER',
        'ar': 'المتصفح المباشر',
        'vi': 'TRÌNH DUYỆT TRỰC TIẾP',
        'es': 'NAVEGADOR EN VIVO',
    },
    'error_generic': {
        'en': 'Unable to finish this session. Check ORDER for its status, or contact SUPPORT.',
        'ar': 'تعذر إنهاء هذه الجلسة. تحقق من حالتها في الطلبات، أو تواصل مع الدعم.',
        'vi': 'Không thể hoàn tất phiên này. Kiểm tra trạng thái ở ĐƠN HÀNG, hoặc liên hệ HỖ TRỢ.',
        'es': 'No se pudo completar esta sesión. Revisa su estado en PEDIDOS, o contacta con SOPORTE.',
    },

    'progress_title_preparing': {'en': '⚡ PREPARING YOUR BROWSER', 'ar': '⚡ تجهيز متصفحك', 'vi': '⚡ ĐANG CHUẨN BỊ TRÌNH DUYỆT', 'es': '⚡ PREPARANDO TU NAVEGADOR'},
    'progress_title_ready': {'en': '✅ YOUR BROWSER IS READY', 'ar': '✅ متصفحك جاهز', 'vi': '✅ TRÌNH DUYỆT CỦA BẠN ĐÃ SẴN SÀNG', 'es': '✅ TU NAVEGADOR ESTÁ LISTO'},
    'progress_title_failed': {'en': '⚠️ PREPARATION STOPPED', 'ar': '⚠️ توقف التجهيز', 'vi': '⚠️ ĐÃ DỪNG CHUẨN BỊ', 'es': '⚠️ PREPARACIÓN DETENIDA'},
    'progress_title_cancelled': {'en': '⏹️ SESSION CANCELLED', 'ar': '⏹️ تم إلغاء الجلسة', 'vi': '⏹️ ĐÃ HỦY PHIÊN', 'es': '⏹️ SESIÓN CANCELADA'},
    'progress_elapsed': {'en': '⏱ Elapsed: {t}', 'ar': '⏱ الوقت المنقضي: {t}', 'vi': '⏱ Thời gian trôi qua: {t}', 'es': '⏱ Transcurrido: {t}'},
    'progress_stage_of': {'en': '📍 Stage {n} of 6', 'ar': '📍 المرحلة {n} من 6', 'vi': '📍 Giai đoạn {n}/6', 'es': '📍 Etapa {n} de 6'},
    'progress_footer': {'en': 'Updates automatically • CANCEL to stop', 'ar': 'يتحدث تلقائيًا • اختر إلغاء للتوقف', 'vi': 'Tự động cập nhật • HỦY để dừng', 'es': 'Se actualiza automáticamente • CANCELAR para detener'},
    'progress_waiting': {'en': 'Waiting for the current step to respond…', 'ar': 'في انتظار استجابة الخطوة الحالية…', 'vi': 'Đang chờ bước hiện tại phản hồi…', 'es': 'Esperando respuesta del paso actual…'},
    'progress_stages': {
        'en': ('🖥️ Starting browser', '📧 Opening sign-in', '🔒 Checking password',
               '🛡️ Verifying account', '🌐 Preparing Google One', '💳 Preparing final window'),
        'ar': ('🖥️ تشغيل المتصفح', '📧 فتح تسجيل الدخول', '🔒 فحص كلمة السر',
               '🛡️ التحقق من الحساب', '🌐 تجهيز Google One', '💳 تجهيز النافذة النهائية'),
        'vi': ('🖥️ Đang khởi động trình duyệt', '📧 Đang mở đăng nhập', '🔒 Đang kiểm tra mật khẩu',
               '🛡️ Đang xác minh tài khoản', '🌐 Đang chuẩn bị Google One', '💳 Đang chuẩn bị cửa sổ cuối cùng'),
        'es': ('🖥️ Iniciando navegador', '📧 Abriendo inicio de sesión', '🔒 Comprobando contraseña',
               '🛡️ Verificando cuenta', '🌐 Preparando Google One', '💳 Preparando ventana final'),
    },
}


def t(key, lang, **kw):
    entry = T.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or ''
    return text.format(**kw) if kw else text


def picker_markup():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
    rows = [[B(LANG_NAMES[a], callback_data=f'lang:{a}'), B(LANG_NAMES[b], callback_data=f'lang:{b}')]
            for a, b in zip(LANGS[0::2], LANGS[1::2])]
    return K(rows)
