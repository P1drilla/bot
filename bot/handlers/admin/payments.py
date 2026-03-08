"""
Роутер раздела «Оплаты».

Обрабатывает:
- Главный экран оплат
- Toggle для Stars/Crypto
- Настройка крипто-платежей
- Редактирование крипто-настроек
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database.requests import (
    get_setting,
    set_setting,
    is_crypto_enabled,
    is_stars_enabled,
    is_cards_enabled,
    is_yookassa_qr_enabled
)
from bot.states.admin_states import (
    AdminStates,
    CRYPTO_PARAMS,
    get_crypto_param_by_index,
    get_total_crypto_params
)
from bot.utils.admin import is_admin
from bot.keyboards.admin import (
    payments_menu_kb,
    crypto_setup_kb,
    crypto_setup_confirm_kb,
    edit_crypto_kb,
    crypto_management_kb,
    cards_management_kb,
    back_and_home_kb,
    manual_payment_review_kb,
)
from bot.utils.text import escape_markdown_url

logger = logging.getLogger(__name__)

router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================


async def has_crypto_data() -> bool:
    """Проверяет, заполнены ли данные крипто-платежей в БД."""
    url = await get_setting('crypto_item_url', '')
    secret = await get_setting('crypto_secret_key', '')
    return bool(url and secret)


def parse_item_id_from_url(url: str) -> str:
    """
    Извлекает item_id из ссылки на товар Ya.Seller.
    
    Формат: https://t.me/Ya_SellerBot?start=item-{item_id}...
    """
    try:
        if '?start=item-' in url:
            start_part = url.split('?start=item-')[1]
            # item_id — это первая часть до следующего дефиса или конца строки
            item_id = start_part.split('-')[0]
            return item_id
        elif '?start=item0-' in url:
            # Тестовый режим
            start_part = url.split('?start=item0-')[1]
            item_id = start_part.split('-')[0]
            return item_id
    except Exception:
        pass
    return ""


# ============================================================================
# ГЛАВНЫЙ ЭКРАН ОПЛАТ
# ============================================================================

@router.callback_query(F.data == "admin_payments")
async def show_payments_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главный экран раздела оплат."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.payments_menu)

    stars = await is_stars_enabled()
    crypto = await is_crypto_enabled()
    cards = await is_cards_enabled()
    qr = await is_yookassa_qr_enabled()

    text = (
        "💳 *Настройки оплаты*\n\n"
        "Здесь можно включить/выключить способы оплаты и настроить их.\n\n"
    )

    if stars:
        text += "🟢 *Telegram Stars*\n"
    else:
        text += "⚪ *Telegram Stars*\n"

    if crypto:
        item_url = await get_setting('crypto_item_url', '')
        if item_url:
            safe_url = escape_markdown_url(item_url)
            text += f"🟢 *Крипто (@Ya_SellerBot)*\n[Ссылка на товар]({safe_url})\n"
        else:
            text += "🟢 *Крипто (@Ya_SellerBot)*\n"
    else:
        text += "⚪ *Крипто (@Ya_SellerBot)*\n"

    if cards:
        text += "🟢 *Оплата картами (ЮКасса Telegram Payments)*\n"
    else:
        text += "⚪ *Оплата картами (ЮКасса Telegram Payments)*\n"

    if qr:
        shop_id = await get_setting('yookassa_shop_id', '')
        text += f"🟢 *QR-оплата (ЮКасса прямая/СБП)* | Shop ID: `{shop_id or '—'}`\n"
    else:
        text += "⚪ *QR-оплата (ЮКасса прямая/СБП)*\n"

    await callback.message.edit_text(
        text,
        reply_markup=payments_menu_kb(stars, crypto, cards, qr),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


# ============================================================================
# TOGGLE STARS
# ============================================================================

@router.callback_query(F.data == "admin_payments_toggle_stars")
async def toggle_stars(callback: CallbackQuery, state: FSMContext):
    """Переключает Telegram Stars."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    current = await is_stars_enabled()
    new_value = '0' if current else '1'
    await set_setting('stars_enabled', new_value)
    
    status = "включены ⭐" if new_value == '1' else "выключены"
    await callback.answer(f"Telegram Stars {status}")
    
    # Обновляем экран
    await show_payments_menu(callback, state)


# ============================================================================
# TOGGLE CRYPTO
# ============================================================================

@router.callback_query(F.data == "admin_payments_toggle_crypto")
async def toggle_crypto(callback: CallbackQuery, state: FSMContext):
    """Открывает настройку или меню управления крипто-платежами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Проверяем, есть ли данные в БД
    if await has_crypto_data():
        # Если данные есть → меню управления
        await show_crypto_management_menu(callback, state)
    else:
        # Если данных нет → диалог настройки
        await start_crypto_setup(callback, state)


# ============================================================================
# НАСТРОЙКА КРИПТО-ПЛАТЕЖЕЙ
# ============================================================================

async def start_crypto_setup(callback: CallbackQuery, state: FSMContext):
    """Начинает диалог настройки крипто-платежей."""
    await state.set_state(AdminStates.crypto_setup_url)
    await state.update_data(crypto_data={}, crypto_step=1)
    
    # Получаем username бота для инструкции
    bot_username = callback.bot.my_username if hasattr(callback.bot, 'my_username') else "YOUR_BOT"
    callback_url = f"https://t.me/{bot_username}"
    
    text = (
        "💰 *Настройка крипто-платежей*\n\n"
        "Для приёма криптовалюты мы используем @Ya\\_SellerBot.\n\n"
        "*Инструкция:*\n"
        "1️⃣ Создайте товар в @Ya\\_SellerBot\n"
        "2️⃣ Добавьте тарифы (помните номера 1-9!)\n"
        "3️⃣ Перейдите: Позиция → Уведомления → Обратная ссылка\n"
        "4️⃣ Вставьте туда эту ссылку:\n\n"
        f"`{callback_url}`\n\n"
        "💡 _Ya.Seller автоматически добавит параметры платежа:_\n"
        f"`{callback_url}?start=bill1-данные-подпись`\n\n"
        "5️⃣ Скопируйте ссылку на товар из бота\n\n"
        "📚 [Подробная документация](https://yadreno.ru/seller/integration.php)\n\n"
        "---\n\n"
        "Теперь *вставьте ссылку на товар* из @Ya\\_SellerBot:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=crypto_setup_kb(1),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


@router.message(AdminStates.crypto_setup_url)
async def process_crypto_url(message: Message, state: FSMContext):
    """Обрабатывает ввод ссылки на товар."""
    url = message.text.strip()
    
    # Валидация
    param = get_crypto_param_by_index(0)
    if not param['validate'](url):
        await message.answer(
            f"❌ {param['error']}\n\nПопробуйте ещё раз:",
            parse_mode="Markdown"
        )
        return
    
    # Удаляем сообщение
    try:
        await message.delete()
    except Exception:
        pass
    
    # Проверяем режим
    data = await state.get_data()
    edit_mode = data.get('edit_mode', False)
    
    if edit_mode:
        # Режим редактирования - сохраняем и возвращаемся в меню
        await set_setting('crypto_item_url', url)
        await state.update_data(edit_mode=False)
        
        safe_url = escape_markdown_url(url)
        await message.answer(
            f"✅ Ссылка обновлена!\n[Ссылка на товар]({safe_url})",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        
        # Создаём фейковый callback для показа меню
        class FakeCallback:
            def __init__(self, msg, user):
                self.message = msg
                self.from_user = user
                self.bot = msg.bot
            async def answer(self, *args, **kwargs):
                pass
        
        fake = FakeCallback(message, message.from_user)
        try:
            await show_crypto_management_menu(fake, state)
        except Exception as e:
            # Если не удалось отредактировать сообщение, создаем новое
            if "message to edit not found" in str(e):
                await message.answer(
                    "✅ Ссылка обновлена!\n[Ссылка на товар]({})".format(escape_markdown_url(url)),
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                # Создаем новое сообщение для меню
                menu_msg = await message.answer("Загрузка меню...")
                fake_new = FakeCallback(menu_msg, message.from_user)
                await show_crypto_management_menu(fake_new, state)
            else:
                raise e
    else:
        # Режим настройки - сохраняем во временные данные
        crypto_data = data.get('crypto_data', {})
        crypto_data['crypto_item_url'] = url
        await state.update_data(crypto_data=crypto_data, crypto_step=2)
        
        # Переходим к вводу секретного ключа
        await state.set_state(AdminStates.crypto_setup_secret)
        
        safe_url = escape_markdown_url(url)
        await message.answer(
            f"✅ Ссылка принята!\n[Ссылка на товар]({safe_url})\n\n"
            "Теперь введите *Секретный ключ*:\n"
            "Найти его можно в @Ya\\_SellerBot: Профиль → Ключ подписи",
            reply_markup=crypto_setup_kb(2),
            disable_web_page_preview=True,
            parse_mode="Markdown"
        )


@router.message(AdminStates.crypto_setup_secret)
async def process_crypto_secret(message: Message, state: FSMContext):
    """Обрабатывает ввод секретного ключа."""
    secret = message.text.strip()
    
    # Валидация
    param = get_crypto_param_by_index(1)
    if not param['validate'](secret):
        await message.answer(
            f"❌ {param['error']}\n\nПопробуйте ещё раз:",
            parse_mode="Markdown"
        )
        return
    
    # Удаляем сообщение (там секретный ключ!)
    try:
        await message.delete()
    except Exception:
        pass
    
    # Проверяем режим
    data = await state.get_data()
    edit_mode = data.get('edit_mode', False)
    
    if edit_mode:
        # Режим редактирования - сохраняем и возвращаемся в меню
        await set_setting('crypto_secret_key', secret)
        await state.update_data(edit_mode=False)
        await message.answer("✅ Секретный ключ обновлён!")
        
        # Создаём фейковый callback для показа меню
        class FakeCallback:
            def __init__(self, msg, user):
                self.message = msg
                self.from_user = user
                self.bot = msg.bot
            async def answer(self, *args, **kwargs):
                pass
        
        fake = FakeCallback(message, message.from_user)
        try:
            await show_crypto_management_menu(fake, state)
        except Exception as e:
            # Если не удалось отредактировать сообщение, создаем новое
            if "message to edit not found" in str(e):
                await message.answer("✅ Секретный ключ обновлён!")
                # Создаем новое сообщение для меню
                menu_msg = await message.answer("Загрузка меню...")
                fake_new = FakeCallback(menu_msg, message.from_user)
                await show_crypto_management_menu(fake_new, state)
            else:
                raise e
    else:
        # Режим настройки - сохраняем во временные данные
        crypto_data = data.get('crypto_data', {})
        crypto_data['crypto_secret_key'] = secret
        await state.update_data(crypto_data=crypto_data)
        
        # Переходим к подтверждению
        await state.set_state(AdminStates.payments_menu)
        
        item_url = crypto_data.get('crypto_item_url', '')
        safe_url = escape_markdown_url(item_url)
        
        await message.answer(
            "✅ *Все данные введены!*\n\n"
            f"📦 Товар: [Ссылка на товар]({safe_url})\n"
            f"🔐 Ключ: `{'•' * 16}`\n\n"
            "Сохранить и включить крипто-платежи?",
            reply_markup=crypto_setup_confirm_kb(),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )


@router.callback_query(F.data == "admin_crypto_setup_back")
async def crypto_setup_back(callback: CallbackQuery, state: FSMContext):
    """Возврат на предыдущий шаг настройки крипто."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    step = data.get('crypto_step', 1)
    
    if step <= 1:
        # Возврат к меню оплат
        await show_payments_menu(callback, state)
    else:
        # Возврат к вводу URL
        await state.set_state(AdminStates.crypto_setup_url)
        await state.update_data(crypto_step=1)
        await start_crypto_setup(callback, state)
    
    await callback.answer()


@router.callback_query(F.data == "admin_crypto_setup_save")
async def crypto_setup_save(callback: CallbackQuery, state: FSMContext):
    """Сохраняет настройки крипто и включает их."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    crypto_data = data.get('crypto_data', {})
    
    if not crypto_data.get('crypto_item_url') or not crypto_data.get('crypto_secret_key'):
        await callback.answer("❌ Данные не полные", show_alert=True)
        return
    
    # Сохраняем
    await set_setting('crypto_item_url', crypto_data['crypto_item_url'])
    await set_setting('crypto_secret_key', crypto_data['crypto_secret_key'])
    await set_setting('crypto_enabled', '1')
    
    await callback.answer("✅ Крипто-платежи включены!")
    
    await callback.message.edit_text(
        "✅ *Крипто-платежи настроены и включены!*\n\n"
        "Теперь пользователи смогут оплачивать криптовалютой.\n"
        "Не забудьте добавить тарифы с указанием ID тарифа (1-9)!",
        parse_mode="Markdown"
    )
    
    # Показываем меню оплат
    await show_payments_menu(callback, state)


# ============================================================================
# МЕНЮ УПРАВЛЕНИЯ КРИПТО-ПЛАТЕЖАМИ
# ============================================================================

async def show_crypto_management_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню управления крипто-платежами."""
    await state.set_state(AdminStates.payments_menu)
    
    is_enabled = await is_crypto_enabled()
    item_url = await get_setting('crypto_item_url', '')
    
    status_emoji = "🟢" if is_enabled else "⚪"
    status_text = "включены" if is_enabled else "выключены"
    
    if item_url:
        safe_url = escape_markdown_url(item_url)
        text = (
            "💰 *Управление крипто-платежами*\n\n"
            f"{status_emoji} Статус: *{status_text}*\n"
            f"📦 Товар: [Ссылка на товар]({safe_url})\n\n"
            "Выберите действие:"
        )
    else:
        text = (
            "💰 *Управление крипто-платежами*\n\n"
            f"{status_emoji} Статус: *{status_text}*\n"
            "📦 Товар: —\n\n"
            "Выберите действие:"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=crypto_management_kb(is_enabled),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_crypto_mgmt_toggle")
async def crypto_mgmt_toggle(callback: CallbackQuery, state: FSMContext):
    """Включает/выключает крипто-платежи (без потери данных)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    current = await is_crypto_enabled()
    new_value = '0' if current else '1'
    await set_setting('crypto_enabled', new_value)
    
    status = "включены ✅" if new_value == '1' else "выключены"
    await callback.answer(f"Крипто-платежи {status}")
    
    # Обновляем меню
    await show_crypto_management_menu(callback, state)


@router.callback_query(F.data == "admin_crypto_mgmt_edit_url")
async def crypto_mgmt_edit_url(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование ссылки на товар."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.crypto_setup_url)
    await state.update_data(edit_mode=True)
    
    current_url = await get_setting('crypto_item_url', '')
    
    if current_url:
        safe_url = escape_markdown_url(current_url)
        text = (
            "🔗 *Изменение ссылки на товар*\n\n"
            f"Текущая ссылка: [Ссылка на товар]({safe_url})\n\n"
            "Введите новую ссылку на товар из @Ya\\_SellerBot:"
        )
    else:
        text = (
            "🔗 *Изменение ссылки на товар*\n\n"
            "Текущая ссылка: —\n\n"
            "Введите новую ссылку на товар из @Ya\\_SellerBot:"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=back_and_home_kb("admin_crypto_management"),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "admin_crypto_mgmt_edit_secret")
async def crypto_mgmt_edit_secret(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование секретного ключа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.crypto_setup_secret)
    await state.update_data(edit_mode=True)
    
    text = (
        "🔐 *Изменение секретного ключа*\n\n"
        "Введите новый секретный ключ:\n"
        "Найти его можно в @Ya\\_SellerBot: Профиль → Ключ подписи"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=back_and_home_kb("admin_crypto_management"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_crypto_management")
async def back_to_crypto_management(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню управления крипто-платежами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await show_crypto_management_menu(callback, state)


# ============================================================================
# РЕДАКТИРОВАНИЕ КРИПТО-НАСТРОЕК
# ============================================================================

@router.callback_query(F.data == "admin_payments_crypto_settings")
async def start_edit_crypto(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование крипто-настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.edit_crypto)
    await state.update_data(edit_crypto_param=0)
    
    await show_crypto_edit_screen(callback, state, 0)


async def show_crypto_edit_screen(callback: CallbackQuery, state: FSMContext, param_index: int):
    """Показывает экран редактирования крипто-настройки."""
    param = get_crypto_param_by_index(param_index)
    total = get_total_crypto_params()
    
    current_value = await get_setting(param['key'], '')
    
    # Маскируем секретный ключ
    if param['key'] == 'crypto_secret_key' and current_value:
        display_value = '•' * min(len(current_value), 16)
    else:
        display_value = current_value or '—'
    
    text = (
        f"⚙️ *Настройки крипто-платежей* ({param_index + 1}/{total})\n\n"
        f"📌 Параметр: *{param['label']}*\n"
        f"📝 Текущее значение: `{display_value}`\n\n"
        f"Введите новое значение или используйте кнопки навигации:\n"
        f"({param['hint']})"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=edit_crypto_kb(param_index, total),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_crypto_edit_prev")
async def crypto_edit_prev(callback: CallbackQuery, state: FSMContext):
    """Предыдущий параметр крипто-настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    current = data.get('edit_crypto_param', 0)
    new_param = max(0, current - 1)
    await state.update_data(edit_crypto_param=new_param)
    
    await show_crypto_edit_screen(callback, state, new_param)
    await callback.answer()


@router.callback_query(F.data == "admin_crypto_edit_next")
async def crypto_edit_next(callback: CallbackQuery, state: FSMContext):
    """Следующий параметр крипто-настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    current = data.get('edit_crypto_param', 0)
    total = get_total_crypto_params()
    new_param = min(total - 1, current + 1)
    await state.update_data(edit_crypto_param=new_param)
    
    await show_crypto_edit_screen(callback, state, new_param)
    await callback.answer()


@router.message(AdminStates.edit_crypto)
async def edit_crypto_value(message: Message, state: FSMContext):
    """Обрабатывает ввод нового значения крипто-настройки."""
    data = await state.get_data()
    param_index = data.get('edit_crypto_param', 0)
    
    param = get_crypto_param_by_index(param_index)
    value = message.text.strip()
    
    # Валидация
    if not param['validate'](value):
        await message.answer(
            f"❌ {param['error']}",
            parse_mode="Markdown"
        )
        return
    
    # Сохраняем в БД
    await set_setting(param['key'], value)
    
    # Удаляем сообщение
    try:
        await message.delete()
    except Exception:
        pass
    
    # Показываем обновлённый экран
    await message.answer(
        f"✅ *{param['label']}* обновлено!",
        parse_mode="Markdown"
    )
    
    # Создаём фейковый callback для показа экрана
    # Это хак, но работает
    class FakeCallback:
        def __init__(self, msg, user):
            self.message = msg
            self.from_user = user
            self.bot = msg.bot
        
        async def answer(self, *args, **kwargs):
            pass
    
    fake = FakeCallback(message, message.from_user)
    try:
        await show_crypto_edit_screen(fake, state, param_index)
    except Exception as e:
        # Если не удалось отредактировать сообщение, создаем новое
        if "message to edit not found" in str(e):
            # Создаем новое сообщение для экрана редактирования
            edit_msg = await message.answer("Загрузка экрана редактирования...")
            fake_new = FakeCallback(edit_msg, message.from_user)
            await show_crypto_edit_screen(fake_new, state, param_index)
        else:
            raise e


@router.callback_query(F.data == "admin_crypto_edit_done")
async def crypto_edit_done(callback: CallbackQuery, state: FSMContext):
    """Завершение редактирования крипто-настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer("✅ Настройки сохранены")
    await show_payments_menu(callback, state)


# ============================================================================
# УПРАВЛЕНИЕ ОПЛАТОЙ КАРТАМИ
# ============================================================================

@router.callback_query(F.data == "admin_payments_cards")
async def show_cards_management_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню управления оплатой картами (ЮКасса)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.payments_menu)
    
    is_enabled = await is_cards_enabled()
    token = await get_setting('cards_provider_token', '')
    
    status_emoji = "🟢" if is_enabled else "⚪"
    status_text = "включено" if is_enabled else "выключено"
    
    if token:
        # Маскируем токен: первые 4 и последние 4 символа
        masked_token = f"{token[:4]}...{token[-4:]}"
        token_display = f"Установлен ✅ (`{masked_token}`)"
    else:
        token_display = "Не установлен ❌"
    
    text = (
        "💳 *Управление оплатой картами*\n\n"
        "Для работы этого способа необходимо настроить провайдера ЮКасса.\n\n"
        "❗️ *ШАГ 1: РЕГИСТРАЦИЯ*\n"
        "Обязательно [зарегистрируйте магазин в ЮКассе по этой ссылке](https://yookassa.ru/joinups/?source=sva)\n\n"
        "После проверки документов ЮКассой переходите к настройке токена.\n\n"
        f"{status_emoji} Статус: *{status_text}*\n"
        f"🔑 Provider Token: *{token_display}*\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=cards_management_kb(is_enabled),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cards_mgmt_toggle")
async def cards_mgmt_toggle(callback: CallbackQuery, state: FSMContext):
    """Включает/выключает оплату картами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    # Нельзя включить, если нет токена
    if not await is_cards_enabled() and not await get_setting('cards_provider_token', ''):
        await callback.answer("❌ Сначала укажите Provider Token!", show_alert=True)
        return

    current = await is_cards_enabled()
    new_value = '0' if current else '1'
    await set_setting('cards_enabled', new_value)
    
    status = "включена ✅" if new_value == '1' else "выключена"
    await callback.answer(f"Оплата картами {status}")
    
    # Обновляем меню
    await show_cards_management_menu(callback, state)


@router.callback_query(F.data == "admin_cards_mgmt_edit_token")
async def cards_mgmt_edit_token(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование токена ЮКасса."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.cards_setup_token)
    # Сохраняем ID сообщения, чтобы потом его отредактировать
    await state.update_data(last_menu_msg_id=callback.message.message_id)
    
    text = (
        "🔗 *Установка Provider Token*\n\n"
        "❗️ *ШАГ 1: РЕГИСТРАЦИЯ В ЮКАССЕ*\n"
        "Обязательно [зарегистрируйтесь по этой ссылке](https://yookassa.ru/joinups/?source=sva)\n\n"
        "*ШАГ 2: ПОЛУЧЕНИЕ ТОКЕНА В @BotFather*\n"
        "1. Отправьте команду `/mybots` и выберите бота.\n"
        "2. Нажмите `Payments` → `YooKassa`.\n"
        "3. Подключите магазин в боте провайдера и **обязательно вернитесь в @BotFather**.\n"
        "4. В BotFather снова откройте `Payments`, там появится токен.\n\n"
        "Отправьте полученный токен ответом на это сообщение:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=back_and_home_kb("admin_payments_cards"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.cards_setup_token)
async def cards_setup_token_value(message: Message, state: FSMContext):
    """Обрабатывает ввод токена ЮКасса."""
    data = await state.get_data()
    last_menu_msg_id = data.get('last_menu_msg_id')

    token = message.text.strip()
    
    if len(token) < 20 or ':' not in token:
        await message.answer("❌ Неверный формат токена. Попробуйте ещё раз:")
        return
    
    await set_setting('cards_provider_token', token)
    
    try:
        await message.delete()
    except Exception:
        pass
    
    # Если у нас есть ID сообщения меню, используем его для редактирования
    menu_message = message
    if last_menu_msg_id:
        try:
            # Создаем объект сообщения с нужным ID для редактирования
            menu_message = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_menu_msg_id,
                text="⌛ Сохранение..."
            )
        except Exception:
            # Если не вышло (например, сообщение удалено), будем отвечать новым
            menu_message = await message.answer("⌛ Сохранение...")

    # Возвращаемся в меню через FakeCallback
    class FakeCallback:
        def __init__(self, msg, user, success_msg=None):
            self.message = msg
            self.from_user = user
            self.bot = msg.bot
            self.data = "admin_payments_cards"
            self.success_msg = success_msg
        
        async def answer(self, text=None, show_alert=False, *args, **kwargs):
            # Если передали текст для popup, запоминаем его (он будет показан при нажатии кнопок)
            # Но так как в AIOGram answerCallbackQuery работает только для реальных инстансов,
            # мы просто выведем информацию в консоль или пропустим.
            # Для пользователя мы добавим текст в само сообщение.
            pass

    fake = FakeCallback(menu_message, message.from_user)
    await show_cards_management_menu(fake, state)


# ============================================================================
# НАСТРОЙКА QR-ОПЛАТЫ ЮКАССА (прямой API)
# ============================================================================

def qr_management_kb(is_enabled: bool) -> "InlineKeyboardMarkup":
    """Клавиатура управления QR-оплатой ЮКасса."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    from bot.keyboards.admin import back_button, home_button

    builder = InlineKeyboardBuilder()

    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data="admin_qr_mgmt_toggle"))
    builder.row(InlineKeyboardButton(text="🏪 Изменить Shop ID", callback_data="admin_qr_edit_shop_id"))
    builder.row(InlineKeyboardButton(text="🔐 Изменить Secret Key", callback_data="admin_qr_edit_secret"))
    builder.row(back_button("admin_payments"), home_button())

    return builder.as_markup()


@router.callback_query(F.data == "admin_payments_qr")
async def show_qr_management_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню управления QR-оплатой ЮКасса."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.payments_menu)

    from database.requests import is_yookassa_qr_enabled
    is_enabled = await is_yookassa_qr_enabled()
    shop_id = await get_setting('yookassa_shop_id', '')
    secret_key = await get_setting('yookassa_secret_key', '')

    status_emoji = "🟢" if is_enabled else "⚪"
    status_text = "включено" if is_enabled else "выключено"

    shop_display = f"`{shop_id}`" if shop_id else "❌ Не задан"
    secret_display = f"Установлен ✅ (`{secret_key[:4]}...{secret_key[-4:]}`)" if len(secret_key) >= 8 else "❌ Не задан"

    text = (
        "📱 *QR-оплата ЮКасса (прямой API)*\n\n"
        "Позволяет принимать оплату картами и через СБП по QR-коду,\n"
        "без Telegram Payments.\n\n"
        "📋 *Как получить доступ:*\n"
        "1. Зарегистрируйте магазин: [yookassa.ru](https://yookassa.ru/joinups/?source=sva)\n"
        "2. Перейдите: Настройки → API-интеграция\n"
        "3. Скопируйте Shop ID и сгенерируйте новый Secret Key\n\n"
        f"{status_emoji} Статус: *{status_text}*\n"
        f"🏪 Shop ID: {shop_display}\n"
        f"🔑 Secret Key: {secret_display}\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=qr_management_kb(is_enabled),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "admin_qr_mgmt_toggle")
async def qr_mgmt_toggle(callback: CallbackQuery, state: FSMContext):
    """Включает/выключает QR-оплату ЮКасса."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from database.requests import is_yookassa_qr_enabled

    # Нельзя включить без реквизитов
    if not await is_yookassa_qr_enabled():
        shop_id = await get_setting('yookassa_shop_id', '')
        secret_key = await get_setting('yookassa_secret_key', '')
        if not shop_id or not secret_key:
            await callback.answer("❌ Сначала укажите Shop ID и Secret Key!", show_alert=True)
            return

    current = await is_yookassa_qr_enabled()
    new_value = '0' if current else '1'
    await set_setting('yookassa_qr_enabled', new_value)

    status = "включена ✅" if new_value == '1' else "выключена"
    await callback.answer(f"QR-оплата {status}")
    await show_qr_management_menu(callback, state)


@router.callback_query(F.data == "admin_qr_edit_shop_id")
async def qr_edit_shop_id(callback: CallbackQuery, state: FSMContext):
    """Запрашивает Shop ID ЮКасса."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.qr_setup_shop_id)
    await state.update_data(last_menu_msg_id=callback.message.message_id)

    current = await get_setting('yookassa_shop_id', '')
    current_display = f"\nТекущий: `{current}`" if current else ""

    await callback.message.edit_text(
        f"🏪 *Введите Shop ID ЮКасса*{current_display}\n\n"
        "Найдите в разделе: *Настройки → API-интеграция* вашего магазина.\n"
        "(Это числовой ID, например: `123456`)",
        reply_markup=back_and_home_kb("admin_payments_qr"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.qr_setup_shop_id)
async def qr_setup_shop_id_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод Shop ID."""
    shop_id = message.text.strip()

    if not shop_id.isdigit() or len(shop_id) < 3:
        await message.answer("❌ Некорректный Shop ID. Должен быть числом (например, `123456`).",
                             parse_mode="Markdown")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await set_setting('yookassa_shop_id', shop_id)

    data = await state.get_data()
    last_menu_msg_id = data.get('last_menu_msg_id')

    class FakeCallback:
        def __init__(self, msg, user):
            self.message = msg
            self.from_user = user
            self.bot = msg.bot
        async def answer(self, *args, **kwargs):
            pass

    menu_message = message
    if last_menu_msg_id:
        try:
            menu_message = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_menu_msg_id,
                text="⌛"
            )
        except Exception:
            menu_message = await message.answer("⌛")

    fake = FakeCallback(menu_message, message.from_user)
    await show_qr_management_menu(fake, state)



@router.callback_query(F.data == "admin_qr_edit_secret")
async def qr_edit_secret(callback: CallbackQuery, state: FSMContext):
    """Запрашивает Secret Key ЮКасса."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.qr_setup_secret_key)
    await state.update_data(last_menu_msg_id=callback.message.message_id)

    await callback.message.edit_text(
        "🔐 *Введите Secret Key ЮКасса*\n\n"
        "Найдите в разделе: *Настройки → API-интеграция* вашего магазина.\n"
        "_(Секретный ключ будет скрыт после сохранения)_",
        reply_markup=back_and_home_kb("admin_payments_qr"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.qr_setup_secret_key)
async def qr_setup_secret_key_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод Secret Key."""
    secret_key = message.text.strip()

    if len(secret_key) < 16:
        await message.answer("❌ Слишком короткий ключ. Попробуйте ещё раз.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await set_setting('yookassa_secret_key', secret_key)

    data = await state.get_data()
    last_menu_msg_id = data.get('last_menu_msg_id')

    class FakeCallback:
        def __init__(self, msg, user):
            self.message = msg
            self.from_user = user
            self.bot = msg.bot
        async def answer(self, *args, **kwargs):
            pass

    menu_message = message
    if last_menu_msg_id:
        try:
            menu_message = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=last_menu_msg_id,
                text="⌛"
            )
        except Exception:
            menu_message = await message.answer("⌛")

    fake = FakeCallback(menu_message, message.from_user)
    await show_qr_management_menu(fake, state)


@router.callback_query(F.data == "admin_manual_payments_info")
async def manual_payments_info(callback: CallbackQuery, state: FSMContext):
    """
    Информационный экран про ручные переводы на карту.
    Здесь админ видит, как работает схема оплаты без эквайринга.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.payments_menu)

    text = (
        "💸 *Ручные переводы на карту*\n\n"
        "Этот способ оплаты работает *без эквайринга* — пользователь переводит деньги\n"
        "на вашу карту вручную, отправляет скриншот чека, а вы проверяете платёж\n"
        "в банковском приложении и выдаёте ключ через админ-панель.\n\n"
        "✅ Что уже делает бот:\n"
        "• Показывает пользователю сумму и ваши реквизиты\n"
        "• Принимает скриншот/фото чека\n"
        "• Отправляет чек в этот админ-аккаунт с кнопками подтверждения/отклонения\n\n"
        "⚠️ Важно:\n"
        "• Статус платежа в БД НЕ меняется автоматически\n"
        "• После подтверждения вам нужно самостоятельно выдать ключ\n"
        "  через раздел «Пользователи» → выбранный пользователь → «➕ Добавить ключ».\n\n"
        "Реквизиты карты сейчас зашиты в коде в `bot/handlers/user/payments.py`\n"
        "(переменная `card_text` в блоке ручной оплаты) — при необходимости\n"
        "измените их на свои."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_and_home_kb("admin_payments"),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_manual_payment_confirm:"))
async def admin_manual_payment_confirm(callback: CallbackQuery, state: FSMContext):
    """
    Администратор подтверждает ручную оплату перевода на карту.
    При наличии tariff_id ключ создаётся автоматически и выдаётся пользователю.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return

    user_telegram_id = int(parts[1])
    tariff_id = int(parts[2]) if len(parts) > 2 else 0

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    from database.requests import (
        get_user_by_telegram_id,
        get_or_create_user,
        get_tariff_by_id,
        get_active_servers,
        get_server_by_id,
        create_initial_vpn_key,
        update_vpn_key_config,
    )
    from bot.services.vpn_api import get_client_from_server_data, VPNAPIError
    from bot.handlers.admin.users import generate_unique_email
    from config import DEFAULT_TOTAL_GB

    key_created = False
    key_id = None

    if tariff_id > 0:
        user = await get_user_by_telegram_id(user_telegram_id)
        if not user:
            user = await get_or_create_user(user_telegram_id, None)

        tariff = await get_tariff_by_id(tariff_id)
        if tariff and user:
            days = tariff.get("duration_days") or 30
            servers = await get_active_servers()
            if servers:
                server = await get_server_by_id(servers[0]["id"])
                if server:
                    try:
                        client = get_client_from_server_data(server)
                        inbounds = await client.get_inbounds()
                        if inbounds:
                            inbound_id = inbounds[0]["id"]
                            panel_email = generate_unique_email(user)
                            flow = await client.get_inbound_flow(inbound_id)
                            limit_gb = int(DEFAULT_TOTAL_GB / (1024**3))
                            res = await client.add_client(
                                inbound_id=inbound_id,
                                email=panel_email,
                                total_gb=limit_gb,
                                expire_days=days,
                                limit_ip=1,
                                enable=True,
                                tg_id=str(user_telegram_id),
                                flow=flow,
                            )
                            client_uuid = res.get("uuid")
                            if client_uuid:
                                key_id = await create_initial_vpn_key(
                                    user["id"], tariff_id, days
                                )
                                await update_vpn_key_config(
                                    key_id=key_id,
                                    server_id=server["id"],
                                    panel_inbound_id=inbound_id,
                                    panel_email=panel_email,
                                    client_uuid=client_uuid,
                                )
                                key_created = True
                    except VPNAPIError as e:
                        logger.warning(f"Ошибка создания ключа при подтверждении ручной оплаты: {e}")
                    except Exception as e:
                        logger.exception(f"Неожиданная ошибка при авто-выдаче ключа: {e}")

    if key_created and key_id:
        await callback.answer("✅ Оплата подтверждена, ключ выдан!", show_alert=True)
        try:
            await callback.bot.send_message(
                chat_id=user_telegram_id,
                text=(
                    "✅ *Оплата подтверждена!*\n\n"
                    "🔑 Ваш VPN-ключ создан. Зайдите в раздел «Мои ключи» для получения конфигурации и ссылки."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить пользователю уведомление о ключе: {e}")
    else:
        await callback.answer("✅ Отметили как оплаченный")
        try:
            await callback.bot.send_message(
                chat_id=user_telegram_id,
                text=(
                    "✅ *Оплата подтверждена администратором!*\n\n"
                    "Скоро вам выдадут VPN-ключ.\n"
                    "Если ключ уже выдан, проверьте раздел «Мои ключи»."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить пользователю уведомление о подтверждении оплаты: {e}")


@router.callback_query(F.data.startswith("admin_manual_payment_reject:"))
async def admin_manual_payment_reject(callback: CallbackQuery, state: FSMContext):
    """
    Администратор отклоняет ручную оплату перевода на карту.
    Бот уведомляет пользователя.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return

    user_telegram_id = int(parts[1])

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("❌ Отметили как отклонённый")

    # Уведомляем пользователя
    try:
        await callback.bot.send_message(
            chat_id=user_telegram_id,
            text=(
                "❌ *Оплата не подтверждена*\n\n"
                "Мы не нашли платёж на карте или возникла ошибка.\n"
                "Проверьте, что перевод выполнен корректно, и свяжитесь с поддержкой при необходимости."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить пользователю уведомление об отклонении оплаты: {e}")
