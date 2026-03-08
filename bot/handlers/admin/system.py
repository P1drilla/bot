"""
Обработчики раздела «Настройки бота» в админ-панели.

Функционал:
- Просмотр и редактирование настроек бота
- Управление платежными системами (Stars, Crypto, Cards, QR)
- Управление пробной подпиской
- Просмотр статистики бота
- Рассылка сообщений
- Проверка обновлений
"""
import logging
import os
import subprocess
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramNetworkError

from config import ADMIN_IDS
from database.requests import (
    get_setting, set_setting, get_all_users_count, get_daily_payments_stats,
    get_keys_stats, get_new_users_count_today, get_users_stats
)
from bot.utils.admin import is_admin
from bot.utils.text import escape_md
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import (
    system_menu_kb, settings_list_kb, setting_edit_kb, setting_toggle_kb,
    edit_texts_menu_kb,
    broadcast_menu_kb, broadcast_filter_kb, broadcast_confirm_kb,
    update_check_kb, admin_logs_menu_kb, home_only_kb, back_and_home_kb
)
from bot.services.scheduler import run_daily_tasks

logger = logging.getLogger(__name__)

router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def format_setting_value(key: str, value: str) -> str:
    """Форматирует значение настройки для отображения."""
    if key in ['crypto_enabled', 'stars_enabled', 'cards_enabled', 
               'yookassa_qr_enabled', 'trial_enabled']:
        return "✅ Включено" if value == '1' else "❌ Выключено"
    elif key in ['crypto_item_url', 'cards_provider_token', 
                 'yookassa_shop_id', 'yookassa_secret_key']:
        return f"`{'*' * len(value) if value else 'не задано'}`"
    elif key in ['notification_days', 'trial_tariff_id']:
        return value if value else "не задано"
    else:
        return value if value else "не задано"


def get_setting_description(key: str) -> str:
    """Возвращает описание настройки."""
    descriptions = {
        'crypto_enabled': 'Включить оплату криптовалютой (USDT)',
        'crypto_item_url': 'Ссылка на товар в криптопроцессинге',
        'stars_enabled': 'Включить оплату Telegram Stars',
        'cards_enabled': 'Включить оплату картами (ЮКасса)',
        'cards_provider_token': 'Provider Token для ЮКассы',
        'yookassa_qr_enabled': 'Включить QR-оплату через ЮКассу',
        'yookassa_shop_id': 'Shop ID магазина ЮКассы',
        'yookassa_secret_key': 'Секретный ключ ЮКассы',
        'trial_enabled': 'Включить пробную подписку',
        'trial_tariff_id': 'ID тарифа для пробной подписки',
        'notification_days': 'За сколько дней уведомлять о истечении',
        'notification_text': 'Текст уведомления о истечении',
        'trial_page_text': 'Текст страницы пробной подписки',
        'main_page_text': 'Текст главной страницы',
        'help_page_text': 'Текст страницы помощи',
        'news_channel_link': 'Ссылка на канал новостей',
        'support_channel_link': 'Ссылка на канал поддержки',
        'broadcast_filter': 'Фильтр по умолчанию для рассылки',
        'broadcast_in_progress': 'Флаг активной рассылки'
    }
    return descriptions.get(key, key)


# ============================================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================================

async def _show_system_menu(callback: CallbackQuery, state: FSMContext):
    """Общая логика: показывает главное меню настроек бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.system_menu)
    
    text = (
        "⚙️ *Настройки бота*\n\n"
        "Выберите раздел для управления:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=system_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_system")
async def show_system_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главное меню настроек (из админ-панели)."""
    await _show_system_menu(callback, state)


@router.callback_query(F.data == "admin_bot_settings")
async def show_bot_settings_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главное меню настроек (кнопка «Настройки бота»)."""
    await _show_system_menu(callback, state)


# ============================================================================
# РЕДАКТИРОВАНИЕ ТЕКСТОВ
# ============================================================================

@router.callback_query(F.data == "admin_edit_texts")
async def show_edit_texts_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню редактирования текстов (главная, справка, уведомления и т.д.)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.settings_list)
    
    text = (
        "📝 *Редактирование текстов*\n\n"
        "Выберите, какой текст изменить:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=edit_texts_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


# ============================================================================
# ПРОСМОТР НАСТРОЕК
# ============================================================================

@router.callback_query(F.data == "admin_settings")
async def show_settings_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.settings_list)
    
    # Получаем все настройки
    settings = [
        'crypto_enabled', 'crypto_item_url', 'stars_enabled',
        'cards_enabled', 'cards_provider_token',
        'yookassa_qr_enabled', 'yookassa_shop_id', 'yookassa_secret_key',
        'trial_enabled', 'trial_tariff_id', 'notification_days',
        'notification_text', 'main_page_text', 'help_page_text',
        'news_channel_link', 'support_channel_link',
        'broadcast_filter', 'broadcast_in_progress'
    ]
    
    # Формируем текст
    lines = ["⚙️ *Настройки бота*\n"]
    
    for key in settings:
        value = await get_setting(key, '')
        description = get_setting_description(key)
        formatted_value = format_setting_value(key, value)
        
        lines.append(f"• *{escape_md(key)}* — {formatted_value}")
        lines.append(f"  _{escape_md(description)}_")
        lines.append("")
    
    text = "\n".join(lines)
    
    await callback.message.edit_text(
        text,
        reply_markup=settings_list_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_setting_edit:"))
async def start_edit_setting(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования настройки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    key = callback.data.split(":")[1]
    value = await get_setting(key, '')
    description = get_setting_description(key)
    
    # Определяем тип настройки
    if key in ['crypto_enabled', 'stars_enabled', 'cards_enabled', 
               'yookassa_qr_enabled', 'trial_enabled']:
        # Переключатель
        await state.set_state(AdminStates.edit_setting_toggle)
        await state.update_data(edit_setting_key=key)
        
        status_text = "✅ Включено" if value == '1' else "❌ Выключено"
        
        await callback.message.edit_text(
            f"⚙️ *Редактирование настройки*\n\n"
            f"Ключ: `{escape_md(key)}`\n"
            f"Описание: {escape_md(description)}\n"
            f"Текущее значение: {status_text}\n\n"
            "Выберите новое значение:",
            reply_markup=setting_toggle_kb(key, value == '1'),
            parse_mode="Markdown"
        )
    else:
        # Текстовое поле
        await state.set_state(AdminStates.edit_setting_value)
        await state.update_data(edit_setting_key=key)
        
        current_value = value if value else "не задано"
        
        await callback.message.edit_text(
            f"⚙️ *Редактирование настройки*\n\n"
            f"Ключ: `{escape_md(key)}`\n"
            f"Описание: {escape_md(description)}\n"
            f"Текущее значение: `{escape_md(current_value)}`\n\n"
            "Введите новое значение:",
            reply_markup=setting_edit_kb(key),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.message(AdminStates.edit_setting_value, F.text)
async def process_edit_setting_value(message: Message, state: FSMContext):
    """Обработка ввода нового значения настройки."""
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    data = await state.get_data()
    key = data.get('edit_setting_key')
    
    if not key:
        await message.answer("❌ Ошибка данных")
        return
    
    # Валидация значения в зависимости от ключа
    if key == 'crypto_item_url' and text and not text.startswith(('http://', 'https://')):
        await message.answer("❌ Ссылка должна начинаться с http:// или https://")
        return
    elif key == 'news_channel_link' and text and not text.startswith(('http://', 'https://', '@')):
        await message.answer("❌ Ссылка должна быть в формате http://, https:// или @username")
        return
    elif key == 'support_channel_link' and text and not text.startswith(('http://', 'https://', '@')):
        await message.answer("❌ Ссылка должна быть в формате http://, https:// или @username")
        return
    elif key == 'notification_days' and text and (not text.isdigit() or int(text) < 1 or int(text) > 30):
        await message.answer("❌ Количество дней должно быть числом от 1 до 30")
        return
    elif key == 'trial_tariff_id' and text and (not text.isdigit() or int(text) < 1):
        await message.answer("❌ ID тарифа должно быть положительным числом")
        return
    
    # Сохраняем новое значение
    await set_setting(key, text)
    
    await message.answer(f"✅ Настройка `{key}` успешно обновлена!")
    
    # Возвращаемся к просмотру настроек
    await state.set_state(AdminStates.settings_list)


@router.callback_query(F.data.startswith("admin_setting_toggle:"))
async def process_edit_setting_toggle(callback: CallbackQuery, state: FSMContext):
    """Обработка переключения настройки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    key = parts[1]
    new_value = parts[2]
    
    await set_setting(key, new_value)
    
    status_text = "✅ Включено" if new_value == '1' else "❌ Выключено"
    await callback.answer(f"✅ Настройка `{key}` изменена на: {status_text}")
    
    # Возвращаемся к просмотру настроек
    await state.set_state(AdminStates.settings_list)


# ============================================================================
# СТАТИСТИКА БОТА
# ============================================================================

@router.callback_query(F.data == "admin_stats")
async def show_bot_stats(callback: CallbackQuery, state: FSMContext):
    """Показывает статистику бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.bot_stats)
    
    # Получаем статистику
    total_users = await get_all_users_count()
    new_users_today = await get_new_users_count_today()
    
    payments_stats = await get_daily_payments_stats()
    keys_stats = await get_keys_stats()
    users_stats = await get_users_stats()
    
    # Формируем текст
    text = (
        "📊 *Статистика бота*\n\n"
        "👥 *Пользователи:*\n"
        f"  Всего: *{total_users}*\n"
        f"  Новых сегодня: *{new_users_today}*\n\n"
        "💳 *Платежи за 24 часа:*\n"
        f"  Успешных: *{payments_stats['paid_count']}*\n"
        f"  USDT: *${payments_stats['paid_cents'] / 100:g}*\n"
        f"  Stars: *{payments_stats['paid_stars']} ⭐*\n"
        f"  Рубли: *{payments_stats['paid_rub']} ₽*\n\n"
        "🔑 *VPN-ключи:*\n"
        f"  Всего: *{keys_stats['total']}*\n"
        f"  Активных: *{keys_stats['active']}*\n"
        f"  Истёкших: *{keys_stats['expired']}*\n"
        f"  Создано сегодня: *{keys_stats['created_today']}*\n\n"
        "👥 *Пользователи по статусу:*\n"
        f"  С активными ключами: *{users_stats['active']}*\n"
        f"  Без активных ключей: *{users_stats['inactive']}*\n"
        f"  Никогда не покупали: *{users_stats['never_paid']}*\n"
        f"  Ключ истёк: *{users_stats['expired']}*"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=home_only_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


# ============================================================================
# РАССЫЛКА СООБЩЕНИЙ
# ============================================================================

@router.callback_query(F.data == "admin_broadcast")
async def show_broadcast_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.broadcast_menu)
    
    # Проверяем активную рассылку
    broadcast_in_progress = await get_setting('broadcast_in_progress', '0')
    
    if broadcast_in_progress == '1':
        await callback.message.edit_text(
            "📢 *Рассылка*\n\n"
            "⚠️ В данный момент уже запущена рассылка!\n"
            "Дождитесь её завершения.",
            reply_markup=home_only_kb(),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "📢 *Рассылка*\n\n"
            "Выберите действие:",
            reply_markup=broadcast_menu_kb(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_start")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начало создания рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.broadcast_message)
    
    await callback.message.edit_text(
        "📢 *Создание рассылки*\n\n"
        "Введите сообщение для рассылки.\n\n"
        "*Поддерживаемые форматы:*\n"
        "• Простой текст\n"
        "• MarkdownV2 (рекомендуется)\n"
        "• HTML (если включено в настройках)\n\n"
        "Для отмены отправьте /cancel",
        reply_markup=back_and_home_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.broadcast_message, F.text)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Обработка ввода сообщения для рассылки."""
    if not is_admin(message.from_user.id):
        return
    
    text = message.text
    
    await state.set_state(AdminStates.broadcast_filter)
    await state.update_data(broadcast_message=text)
    
    await message.answer(
        "📢 *Создание рассылки*\n\n"
        f"Сообщение:\n\n{text}\n\n"
        "Выберите фильтр получателей:",
        reply_markup=broadcast_filter_kb(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("admin_broadcast_filter:"))
async def select_broadcast_filter(callback: CallbackQuery, state: FSMContext):
    """Выбор фильтра для рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    filter_type = callback.data.split(":")[1]
    
    # Получаем количество пользователей для этого фильтра
    from database.requests import count_users_for_broadcast
    count = await count_users_for_broadcast(filter_type)
    
    await state.set_state(AdminStates.broadcast_confirm)
    await state.update_data(broadcast_filter=filter_type)
    
    await callback.message.edit_text(
        f"📢 *Подтверждение рассылки*\n\n"
        f"Фильтр: {filter_type}\n"
        f"Получателей: {count}\n\n"
        "Запустить рассылку?",
        reply_markup=broadcast_confirm_kb(filter_type),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_broadcast_confirm:"))
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и запуск рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    filter_type = callback.data.split(":")[1]
    data = await state.get_data()
    message_text = data.get('broadcast_message')
    
    if not message_text:
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    # Проверяем что рассылка не запущена
    broadcast_in_progress = await get_setting('broadcast_in_progress', '0')
    if broadcast_in_progress == '1':
        await callback.answer("⚠️ Рассылка уже запущена!", show_alert=True)
        return
    
    # Запускаем рассылку в фоновом режиме
    await set_setting('broadcast_in_progress', '1')
    
    # Запускаем задачу рассылки
    from bot.services.scheduler import run_broadcast
    from bot.keyboards.admin import BROADCAST_FILTERS
    
    filter_name = BROADCAST_FILTERS.get(filter_type, filter_type)
    
    # Запускаем рассылку в фоновом режиме
    import asyncio
    asyncio.create_task(
        run_broadcast(
            bot=callback.bot,
            message_text=message_text,
            filter_type=filter_type,
            filter_name=filter_name,
            state=state
        )
    )
    
    await callback.answer("🚀 Рассылка запущена!", show_alert=True)
    
    # Возвращаемся в меню
    await state.set_state(AdminStates.broadcast_menu)
    
    await callback.message.edit_text(
        "📢 *Рассылка*\n\n"
        "Выберите действие:",
        reply_markup=broadcast_menu_kb(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_broadcast_cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отмена создания рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.broadcast_menu)
    await callback.answer("❌ Создание рассылки отменено")
    
    await callback.message.edit_text(
        "📢 *Рассылка*\n\n"
        "Выберите действие:",
        reply_markup=broadcast_menu_kb(),
        parse_mode="Markdown"
    )


# ============================================================================
# ПРОВЕРКА ОБНОВЛЕНИЙ
# ============================================================================

@router.callback_query(F.data == "admin_update_check")
async def check_for_updates(callback: CallbackQuery, state: FSMContext):
    """Проверка наличия обновлений."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.update_check)
    
    try:
        # Проверяем наличие git
        if not os.path.exists('.git'):
            await callback.message.edit_text(
                "⚠️ *Проверка обновлений*\n\n"
                "❌ Репозиторий не найден. Убедитесь, что бот запущен из git-репозитория.",
                reply_markup=update_check_kb(),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        # Получаем текущую ветку
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            await callback.message.edit_text(
                "⚠️ *Проверка обновлений*\n\n"
                f"❌ Ошибка получения ветки: {result.stderr}",
                reply_markup=update_check_kb(),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        branch = result.stdout.strip()
        
        # Получаем текущий коммит
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            await callback.message.edit_text(
                "⚠️ *Проверка обновлений*\n\n"
                f"❌ Ошибка получения коммита: {result.stderr}",
                reply_markup=update_check_kb(),
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        
        current_commit = result.stdout.strip()
        
        # Получаем дату текущего коммита
        result = subprocess.run(
            ['git', 'show', '-s', '--format=%ci', current_commit],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        commit_date = result.stdout.strip() if result.returncode == 0 else "неизвестно"
        
        # Пытаемся получить информацию о последнем коммите в ветке
        try:
            result = subprocess.run(
                ['git', 'ls-remote', 'origin', branch],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                remote_commit = result.stdout.split()[0] if result.stdout.split() else None
                
                if remote_commit and remote_commit != current_commit:
                    await callback.message.edit_text(
                        "⚠️ *Проверка обновлений*\n\n"
                        f"🟢 Доступно обновление!\n\n"
                        f"Ветка: `{branch}`\n"
                        f"Текущий коммит: `{current_commit[:7]}...`\n"
                        f"Последний коммит: `{remote_commit[:7]}...`\n"
                        f"Дата коммита: {commit_date}\n\n"
                        "Рекомендуется обновиться.",
                        reply_markup=update_check_kb(has_update=True),
                        parse_mode="Markdown"
                    )
                else:
                    await callback.message.edit_text(
                        "⚠️ *Проверка обновлений*\n\n"
                        "✅ Бот обновлён до последней версии!\n\n"
                        f"Ветка: `{branch}`\n"
                        f"Текущий коммит: `{current_commit[:7]}...`\n"
                        f"Дата коммита: {commit_date}",
                        reply_markup=update_check_kb(),
                        parse_mode="Markdown"
                    )
            else:
                raise Exception(f"Ошибка получения remote: {result.stderr}")
                
        except Exception as e:
            logger.warning(f"Ошибка проверки обновлений: {e}")
            await callback.message.edit_text(
                "⚠️ *Проверка обновлений*\n\n"
                "⚠️ Не удалось проверить обновления.\n\n"
                f"Ветка: `{branch}`\n"
                f"Текущий коммит: `{current_commit[:7]}...`\n"
                f"Дата коммита: {commit_date}\n\n"
                "Проверьте подключение к интернету.",
                reply_markup=update_check_kb(),
                parse_mode="Markdown"
            )
        
    except subprocess.TimeoutExpired:
        await callback.message.edit_text(
            "⚠️ *Проверка обновлений*\n\n"
            "❌ Таймаут при проверке обновлений.\n\n"
            "Попробуйте позже.",
            reply_markup=update_check_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка проверки обновлений: {e}")
        await callback.message.edit_text(
            "⚠️ *Проверка обновлений*\n\n"
            f"❌ Ошибка: {e}",
            reply_markup=update_check_kb(),
            parse_mode="Markdown"
        )
    
    await callback.answer()


# ============================================================================
# ОТМЕНЫ
# ============================================================================

@router.callback_query(F.data == "admin_setting_cancel")
async def cancel_setting_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования настройки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.settings_list)
    await callback.answer("❌ Редактирование отменено")
    
    # Возвращаемся к просмотру настроек
    settings = [
        'crypto_enabled', 'crypto_item_url', 'stars_enabled',
        'cards_enabled', 'cards_provider_token',
        'yookassa_qr_enabled', 'yookassa_shop_id', 'yookassa_secret_key',
        'trial_enabled', 'trial_tariff_id', 'notification_days',
        'notification_text', 'main_page_text', 'help_page_text',
        'news_channel_link', 'support_channel_link',
        'broadcast_filter', 'broadcast_in_progress'
    ]
    
    lines = ["⚙️ *Настройки бота*\n"]
    
    for key in settings:
        value = await get_setting(key, '')
        description = get_setting_description(key)
        formatted_value = format_setting_value(key, value)
        
        lines.append(f"• *{escape_md(key)}* — {formatted_value}")
        lines.append(f"  _{escape_md(description)}_")
        lines.append("")
    
    text = "\n".join(lines)
    
    await callback.message.edit_text(
        text,
        reply_markup=settings_list_kb(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_broadcast_back")
async def back_to_broadcast_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.broadcast_menu)
    await callback.answer("⬅️ Назад")
    
    await callback.message.edit_text(
        "📢 *Рассылка*\n\n"
        "Выберите действие:",
        reply_markup=broadcast_menu_kb(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_update_check_back")
async def back_to_system_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.system_menu)
    await callback.answer("⬅️ Назад")
    
    await callback.message.edit_text(
        "⚙️ *Настройки бота*\n\n"
        "Выберите раздел для управления:",
        reply_markup=system_menu_kb(),
        parse_mode="Markdown"
    )


# ============================================================================
# СКАЧИВАНИЕ ЛОГОВ
# ============================================================================

LOG_FILE = "logs/bot.log"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB — меньше размер, чтобы отправка реже обрывалась по таймауту


def _read_log_file(path: str, errors_only: bool = False) -> bytes | None:
    """Читает файл лога. Если errors_only — только строки с ERROR или WARNING."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if errors_only:
        lines = [line for line in content.splitlines() if "ERROR" in line or "WARNING" in line]
        content = "\n".join(lines)
    data = content.encode("utf-8")
    if len(data) > MAX_LOG_BYTES:
        data = data[-MAX_LOG_BYTES:]
    return data if data else None


@router.callback_query(F.data == "admin_logs_menu")
async def show_logs_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню скачивания логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.system_menu)
    await callback.message.edit_text(
        "📥 *Скачать логи*\n\n"
        "Выберите тип лога для скачивания:",
        reply_markup=admin_logs_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_download_log_full")
async def download_log_full(callback: CallbackQuery, state: FSMContext):
    """Отправляет полный лог файлом."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = _read_log_file(LOG_FILE, errors_only=False)
    if not data:
        await callback.answer("❌ Файл логов не найден или пуст", show_alert=True)
        return
    
    await callback.answer("📄 Отправляю лог...")
    try:
        doc = BufferedInputFile(data, filename="bot_full.log")
        await callback.message.answer_document(document=doc, caption="📄 Полный лог бота")
    except TelegramNetworkError as e:
        logger.warning(f"Сеть при отправке лога: {e}")
        await callback.message.answer(
            "❌ Не удалось отправить файл (обрыв соединения или таймаут).\n"
            "Попробуйте ещё раз или скачайте файл `logs/bot.log` с сервера вручную."
        )
    except Exception as e:
        logger.exception("Ошибка отправки полного лога")
        await callback.message.answer(f"❌ Ошибка отправки лога: {e}")


@router.callback_query(F.data == "admin_download_log_errors")
async def download_log_errors(callback: CallbackQuery, state: FSMContext):
    """Отправляет лог только с ошибками и предупреждениями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = _read_log_file(LOG_FILE, errors_only=True)
    if not data:
        await callback.message.answer("📭 Записей с ошибками или предупреждениями не найдено.")
        await callback.answer()
        return
    
    await callback.answer("⚠️ Отправляю лог ошибок...")
    try:
        doc = BufferedInputFile(data, filename="bot_errors.log")
        await callback.message.answer_document(document=doc, caption="⚠️ Лог ошибок и предупреждений")
    except TelegramNetworkError as e:
        logger.warning(f"Сеть при отправке лога ошибок: {e}")
        await callback.message.answer(
            "❌ Не удалось отправить файл (обрыв соединения или таймаут).\n"
            "Попробуйте ещё раз или посмотрите логи на сервере в `logs/bot.log`."
        )
    except Exception as e:
        logger.exception("Ошибка отправки лога ошибок")
        await callback.message.answer(f"❌ Ошибка отправки лога: {e}")