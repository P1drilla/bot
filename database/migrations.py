"""
Система миграций базы данных (асинхронная).

Миграции применяются автоматически при запуске бота.
Каждая миграция имеет уникальный номер версии.
"""
import aiosqlite
import logging
from database.connection import DB_PATH


class DatabaseManager:
    """Контекстный менеджер для соединения с базой данных."""
    
    def __init__(self):
        self.conn = None
    
    async def __aenter__(self):
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        return self.conn
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.conn.close()


async def get_db():
    """Получение соединения с базой данных."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn

logger = logging.getLogger(__name__)

# Текущая версия схемы БД
LATEST_VERSION = 8


async def get_current_version() -> int:
    """
    Получает текущую версию схемы БД.
    
    Returns:
        int: Номер версии (0 если таблица версий не существует)
    """
    conn = await get_db()
    try:
        # Проверяем существование таблицы schema_version
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not await cursor.fetchone():
            return 0
        
        cursor = await conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = await cursor.fetchone()
        return row["version"] if row else 0
    finally:
        await conn.close()


async def set_version(conn: aiosqlite.Connection, version: int) -> None:
    """
    Устанавливает версию схемы БД.
    
    Args:
        conn: Соединение с БД
        version: Номер версии
    """
    await conn.execute("DELETE FROM schema_version")
    await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


async def migration_1(conn: aiosqlite.Connection) -> None:
    """
    Миграция v1: Полная структура БД.
    
    Создаёт таблицы:
    - schema_version: версия схемы
    - settings: глобальные настройки бота
    - users: пользователи Telegram
    - tariffs: тарифные планы
    - servers: VPN-серверы (3X-UI)
    - vpn_keys: ключи/подписки пользователей
    - payments: история оплат
    - notification_log: лог уведомлений
    """
    logger.info("Применение миграции v1...")

    # Таблица версий схемы
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL  -- Номер версии схемы БД
        )
    """)
    
    # Глобальные настройки бота
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,  -- Уникальное название настройки
            value TEXT             -- Значение
        )
    """)

    # Дефолтные настройки
    default_settings = [
        ('broadcast_filter', 'all'),  # Фильтр по умолчанию: все пользователи
        ('broadcast_in_progress', '0'),  # Флаг активной рассылки
        ('notification_days', '3'),  # За сколько дней уведомлять
        ('notification_text', '''⚠️ **Ваш ключ для оптимизации трафика скоро истекает!**

Через {days} дней закончится срок действия вашего ключа.

Продлите подписку, чтобы сохранить доступ к сервису без перерыва!'''),
        ('main_page_text', (
            "🔐 *Добро пожаловать в SaaS-решение для оптимизации трафика\\!*\n"
            "Быстрый, безопасный и надежный доступ к интернету\\.\n"
            "Без логов, без ограничений, без проблем\\! 🚀\n"
        )),
        ('help_page_text', (
            "🔐 Этот бот предоставляет доступ к SaaS-сервису для оптимизации трафика.\n\n"
            "*Как это работает:*\n"
            "1. Купите ключ через раздел «Купить ключ»\n\n"
            "2. Установите приложение для оптимизации трафика для вашего устройства:\n\n"
            "Hiddify или v2rayNG или happ\n\n"
            "3. Импортируйте ключ в приложение\n\n"
            "4. Подключайтесь и наслаждайтесь! 🚀\n\n"
            "---\n"
            "Разработчик @plushkin_blog\n"
            "--"
        )),
        ('news_channel_link', 'https://t.me/YadrenoRu'),
        ('support_channel_link', 'https://t.me/YadrenoChat'),
    ]
    for key, value in default_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
    
    # Пользователи Telegram
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            is_banned INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
    
    # Тарифные планы
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tariffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            price_cents INTEGER NOT NULL,
            price_stars INTEGER NOT NULL,
            external_id INTEGER,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # Создаём скрытый тариф для админских ключей
    await conn.execute("""
        INSERT INTO tariffs (name, duration_days, price_cents, price_stars, external_id, display_order, is_active)
        SELECT 'Admin Tariff', 365, 0, 0, 0, 999, 0
        WHERE NOT EXISTS (SELECT 1 FROM tariffs WHERE name = 'Admin Tariff')
    """)

    # VPN-серверы
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            web_base_path TEXT NOT NULL,
            login TEXT NOT NULL,
            password TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # VPN-ключи
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            server_id INTEGER,
            tariff_id INTEGER NOT NULL,
            panel_inbound_id INTEGER,
            client_uuid TEXT,
            panel_email TEXT,
            custom_name TEXT,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (server_id) REFERENCES servers(id),
            FOREIGN KEY (tariff_id) REFERENCES tariffs(id)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_keys_user_id ON vpn_keys(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_keys_expires_at ON vpn_keys(expires_at)")
    
    # История оплат
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vpn_key_id INTEGER,
            user_id INTEGER NOT NULL,
            tariff_id INTEGER NOT NULL,
            order_id TEXT NOT NULL UNIQUE,
            payment_type TEXT NOT NULL,
            amount_cents INTEGER,
            amount_stars INTEGER,
            period_days INTEGER NOT NULL,
            status TEXT DEFAULT 'paid',
            paid_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (tariff_id) REFERENCES tariffs(id)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_paid_at ON payments(paid_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)")

    # Лог уведомлений
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vpn_key_id INTEGER NOT NULL,
            sent_at DATE NOT NULL,
            FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id)
        )
    """)
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_log_unique ON notification_log(vpn_key_id, sent_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_log_vpn_key ON notification_log(vpn_key_id)")
    
    logger.info("Миграция v1 применена")


async def migration_2(conn: aiosqlite.Connection) -> None:
    """
    Миграция v2: Разрешаем NULL в таблице payments для tariff_id, period_days и payment_type.
    
    Это необходимо, чтобы не фиксировать тариф и тип оплаты при создании pending-ордера,
    так как пользователь выбирает их непосредственно при оплате.
    """
    logger.info("Применение миграции v2 (Make payments fields nullable)...")
    
    # 1. Создаём новую таблицу (tariff_id, period_days, payment_type теперь без NOT NULL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS payments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vpn_key_id INTEGER,
            user_id INTEGER NOT NULL,
            tariff_id INTEGER,  -- Теперь NULLABLE
            order_id TEXT NOT NULL UNIQUE,
            payment_type TEXT,  -- Теперь NULLABLE
            amount_cents INTEGER,
            amount_stars INTEGER,
            period_days INTEGER, -- Теперь NULLABLE
            status TEXT DEFAULT 'paid',
            paid_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (tariff_id) REFERENCES tariffs(id)
        )
    """)
    
    # 2. Копируем данные
    await conn.execute("""
        INSERT INTO payments_new (id, vpn_key_id, user_id, tariff_id, order_id, payment_type, 
                                 amount_cents, amount_stars, period_days, status, paid_at)
        SELECT id, vpn_key_id, user_id, tariff_id, order_id, payment_type, 
               amount_cents, amount_stars, period_days, status, paid_at
        FROM payments
    """)
    
    # 3. Удаляем старую таблицу
    await conn.execute("DROP TABLE payments")
    
    # 4. Переименовываем новую таблицу
    await conn.execute("ALTER TABLE payments_new RENAME TO payments")
    
    # 5. Пересоздаём индексы
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_paid_at ON payments(paid_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)")
    
    logger.info("Миграция v2 применена")


async def migration_3(conn: aiosqlite.Connection) -> None:
    """
    Миграция v3: Функция «Пробная подписка».

    Изменения:
    - Добавляет колонку used_trial в таблицу users (флаг использования пробного периода)
    - Добавляет настройки trial_enabled, trial_tariff_id, trial_page_text в settings
    """
    logger.info("Применение миграции v3 (Пробная подписка)...")

    # Добавляем колонку used_trial в таблицу users (если не существует)
    try:
        await conn.execute("ALTER TABLE users ADD COLUMN used_trial INTEGER DEFAULT 0")
        logger.info("Колонка used_trial добавлена в таблицу users")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("Колонка used_trial уже существует")
        else:
            # Если ошибка другая — пробрасываем её
            raise
    except Exception as e:
        logger.error(f"Ошибка миграции v3: {e}")
        raise

    # Дефолтный текст для страницы пробной подписки (MarkdownV2)
    trial_page_text_default = (
        "🎁 *Пробная подписка*\n\n"
        "Хотите попробовать наше SaaS-решение для оптимизации трафика бесплатно?\n\n"
        "Мы предлагаем пробный период, чтобы вы могли убедиться в качестве "
        "и скорости нашего сервиса\\.\n\n"
        "*Что входит в пробный доступ:*\n"
        "• Полный доступ к сервису без ограничений по сайтам\n"
        "• Высокая скорость соединения\n"
        "• Несколько протоколов на выбор\n\n"
        "Нажмите кнопку ниже, чтобы активировать пробный доступ прямо сейчас!\n\n"
        "_Пробный период предоставляется один раз на аккаунт._"
    )

    # Настройки пробной подписки
    trial_settings = [
        ('trial_enabled', '0'),          # Выключено по умолчанию
        ('trial_tariff_id', ''),          # Тариф не задан
        ('trial_page_text', trial_page_text_default),  # Текст по умолчанию
    ]
    for key, value in trial_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    logger.info("Миграция v3 применена")


async def migration_4(conn: aiosqlite.Connection) -> None:
    """
    Миграция v4: Оплата российскими картами.
    
    - Добавляет поле price_rub (цена в рублях) в таблицу tariffs
    - Добавляет настройки cards_enabled и cards_provider_token
    """
    logger.info("Применение миграции v4...")

    # Добавляем price_rub в tariffs (если его ещё нет)
    try:
        await conn.execute("ALTER TABLE tariffs ADD COLUMN price_rub INTEGER DEFAULT 0")
    except aiosqlite.OperationalError:
        pass  # Игнорируем ошибку, если колонка уже существует

    # Добавляем новые настройки
    card_settings = [
        ('cards_enabled', '0'),          # Выключено по умолчанию
        ('cards_provider_token', ''),    # Токен провайдера пустой
    ]
    for key, value in card_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    logger.info("Миграция v4 применена")


async def migration_5(conn: aiosqlite.Connection) -> None:
    """
    Миграция v5: Добавление протокола подключения к панели (HTTP/HTTPS).
    
    Изменения:
    - Добавляет колонку protocol в таблицу servers
    """
    logger.info("Применение миграции v5 (Протоколы панели)...")

    try:
        await conn.execute("ALTER TABLE servers ADD COLUMN protocol TEXT DEFAULT 'https'")
        logger.info("Колонка protocol добавлена в таблицу servers")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("Колонка protocol уже существует")
        else:
            raise
    except Exception as e:
        logger.error(f"Ошибка миграции v5: {e}")
        raise

    logger.info("Миграция v5 применена")


async def migration_6(conn: aiosqlite.Connection) -> None:
    """
    Миграция v6: Прямая QR-оплата через ЮКассу (без Telegram Payments API).

    Изменения:
    - Добавляет в settings настройки: yookassa_qr_enabled, yookassa_shop_id, yookassa_secret_key
    - Добавляет в payments колонку yookassa_payment_id для хранения ID платежа на стороне ЮКассы
    """
    logger.info("Применение миграции v6 (ЮКасса QR-оплата)...")

    # Добавляем колонку yookassa_payment_id в payments
    try:
        await conn.execute("ALTER TABLE payments ADD COLUMN yookassa_payment_id TEXT")
        logger.info("Колонка yookassa_payment_id добавлена в таблицу payments")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("Колонка yookassa_payment_id уже существует")
        else:
            raise

    # Добавляем настройки QR-оплаты
    qr_settings = [
        ('yookassa_qr_enabled', '0'),   # Выключено по умолчанию
        ('yookassa_shop_id', ''),        # Shop ID магазина ЮКассы
        ('yookassa_secret_key', ''),    # Секретный ключ ЮКассы
    ]
    for key, value in qr_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    logger.info("Миграция v6 применена")


async def migration_7(conn: aiosqlite.Connection) -> None:
    """
    Миграция v7: Обновление текста справки (help_page_text).

    Важно:
    - Тексты в settings создаются через INSERT OR IGNORE и не обновляются при правках в коде,
      поэтому старый help_page_text может продолжать показываться в боте.
    """
    logger.info("Применение миграции v7 (Обновление help_page_text)...")

    new_help_text = (
        "🔐 Этот бот предоставляет доступ к SaaS-сервису для оптимизации трафика.\n\n"
        "*Как это работает:*\n"
        "1. Купите ключ через раздел «Купить ключ»\n\n"
        "2. Установите приложение для оптимизации трафика для вашего устройства:\n\n"
        "Hiddify или v2rayNG или happ\n\n"
        "3. Импортируйте ключ в приложение\n\n"
        "4. Подключайтесь и наслаждайтесь! 🚀\n\n"
        "---\n"
        "Разработчик @plushkin_blog\n"
        "--"
    )

    cursor = await conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("help_page_text",)
    )
    row = await cursor.fetchone()

    if not row:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("help_page_text", new_help_text)
        )
        logger.info("help_page_text отсутствовал — добавлен новый текст")
        return

    current_value = row["value"] if row else ""

    should_update = (
        "Kak-nastroit-SaaS-serwis-za-2-minuty-01-23" in current_value
        or "telegra.ph" in current_value
        or "V2Box" in current_value
        or "v2box" in current_value
    )

    if should_update:
        await conn.execute(
            "UPDATE settings SET value = ? WHERE key = ?",
            (new_help_text, "help_page_text")
        )
        logger.info("help_page_text обновлён до актуального текста")
    else:
        logger.info("help_page_text уже кастомный/актуальный — пропускаю обновление")


async def migration_8(conn: aiosqlite.Connection) -> None:
    """
    Миграция v8: Реферальная система.

    Изменения:
    - Добавляет в таблицу users поля invited_by_user_id и referral_bonus_given
    - Добавляет настройки реферальной программы в settings
    """
    logger.info("Применение миграции v8 (Реферальная программа)...")

    # Добавляем invited_by_user_id и referral_bonus_given в users
    try:
        await conn.execute(
            "ALTER TABLE users ADD COLUMN invited_by_user_id INTEGER REFERENCES users(id)"
        )
        logger.info("Колонка invited_by_user_id добавлена в таблицу users")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("Колонка invited_by_user_id уже существует")
        else:
            raise

    try:
        await conn.execute(
            "ALTER TABLE users ADD COLUMN referral_bonus_given INTEGER DEFAULT 0"
        )
        logger.info("Колонка referral_bonus_given добавлена в таблицу users")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("Колонка referral_bonus_given уже существует")
        else:
            raise

    # Индекс по пригласившему пользователю
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_invited_by ON users(invited_by_user_id)"
    )

    # Настройки реферальной программы
    referral_page_text_default = (
        "👥 *Реферальная программа*\n\n"
        "Приглашайте друзей в бота и получайте дополнительные дни подписки.\n\n"
        "Как это работает:\n"
        "• Отправьте свою ссылку другу\n"
        "• Друг заходит по ссылке и оплачивает подписку\n"
        "• За каждого оплатившего друга вы получаете *+%referral_bonus_days% дн.*\n\n"
        "*Ваша ссылка:*\n"
        "%link%\n\n"
        "*Статистика:*\n"
        "• Пригласили всего: %invited_total%\n"
        "• Оплатили подписку: %invited_paid%\n"
        "• Всего бонусных дней: %bonus_days%\n"
    )

    referral_settings = [
        ("referral_enabled", "1"),
        ("referral_bonus_days", "3"),
        ("referral_page_text", referral_page_text_default),
    ]

    for key, value in referral_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    logger.info("Миграция v8 применена")


MIGRATIONS = {
    1: migration_1,
    2: migration_2,
    3: migration_3,
    4: migration_4,
    5: migration_5,
    6: migration_6,
    7: migration_7,
    8: migration_8,
}


async def run_migrations() -> None:
    """
    Запускает все необходимые миграции.
    
    Проверяет текущую версию и применяет все миграции от текущей до LATEST_VERSION.
    """
    try:
        current = await get_current_version()
        
        if current >= LATEST_VERSION:
            logger.info(f"✅ БД соответствует версии {LATEST_VERSION}. Миграция не требуется.")
            return
        
        logger.info(f"🔄 Требуется миграция БД с версии {current} до {LATEST_VERSION}")
        
        conn = await get_db()
        try:
            for version in range(current + 1, LATEST_VERSION + 1):
                if version in MIGRATIONS:
                    logger.info(f"🚀 Применяю миграцию v{version}...")
                    await MIGRATIONS[version](conn)
                    await set_version(conn, version)
        
            logger.info(f"✅ Миграция успешная : БД обновлена до версии {LATEST_VERSION}")
        finally:
            await conn.close()
        
    except Exception as e:
        logger.error(f"❌ Неуспешная миграция: {e}")
        raise
