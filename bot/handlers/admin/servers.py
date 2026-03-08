"""
Обработчики раздела «Серверы» в админ-панели.

Функционал:
- Список серверов с пагинацией
- Добавление/редактирование/удаление серверов
- Переключение активности сервера
- Просмотр статистики сервера
- Выбор сервера для добавления ключа
"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database.requests import (
    get_all_servers, get_server_by_id, add_server, update_server,
    update_server_field, delete_server, toggle_server_active, get_active_servers
)
from bot.utils.admin import is_admin
from bot.utils.text import escape_md
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import (
    servers_menu_kb, servers_list_kb, server_view_kb, server_edit_kb,
    server_edit_field_kb, server_delete_confirm_kb, server_active_confirm_kb,
    back_and_home_kb, home_only_kb
)
from bot.services.vpn_api import (
    get_client_from_server_data, VPNAPIError, format_traffic
)

logger = logging.getLogger(__name__)

router = Router()

# Количество серверов на странице
SERVERS_PER_PAGE = 10


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def format_server_display(server: dict) -> str:
    """Форматирует имя сервера для отображения."""
    return f"{server['name']} ({server['host']}:{server['port']})"


async def _show_servers_page(
    callback: CallbackQuery, 
    state: FSMContext, 
    page: int
):
    """Отображает страницу списка серверов."""
    offset = page * SERVERS_PER_PAGE
    servers = await get_all_servers()
    
    # Пагинация вручную
    total = len(servers)
    total_pages = max(1, (total + SERVERS_PER_PAGE - 1) // SERVERS_PER_PAGE)
    
    start_idx = page * SERVERS_PER_PAGE
    end_idx = start_idx + SERVERS_PER_PAGE
    page_servers = servers[start_idx:end_idx]
    
    # Формируем текст
    if page_servers:
        text = (
            f"🖥️ *Серверы* — Страница {page + 1} из {total_pages}\n\n"
            f"Показано: {len(page_servers)} из {total}"
        )
    else:
        text = (
            f"🖥️ *Серверы* — Страница {page + 1} из {total_pages}\n\n"
            "😕 Серверов не найдено"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=servers_list_kb(page_servers, page, total_pages),
        parse_mode="Markdown"
    )
    await callback.answer()


async def _format_server_card(server: dict) -> tuple[str, any]:
    """Форматирует карточку сервера."""
    status_emoji = "🟢" if server['is_active'] else "🔴"
    
    # Базовая информация
    lines = [
        f"{status_emoji} *{escape_md(server['name'])}*",
        "",
        f"🌐 *Хост:* `{server['host']}`",
        f"🔌 *Порт:* `{server['port']}`",
        f"🔑 *Путь API:* `{server['web_base_path']}`",
        f"👤 *Логин:* `{escape_md(server['login'])}`",
        f"🔒 *Пароль:* `{'*' * len(server.get('password', ''))}`",
        f"🔗 *Протокол:* `{server['protocol']}`",
        f"📅 *Активен:* {'Да' if server['is_active'] else 'Нет'}",
    ]
    
    # Получаем статистику
    if server['is_active']:
        try:
            client = get_client_from_server_data(server)
            stats = await client.get_stats()
            
            if stats.get('online'):
                traffic = format_traffic(stats.get('total_traffic_bytes', 0))
                active = stats.get('active_clients', 0)
                online = stats.get('online_clients', 0)
                
                cpu_text = ""
                if stats.get('cpu_percent') is not None:
                    cpu_text = f" | 💻 {stats['cpu_percent']}% CPU"
                
                lines.extend([
                    "",
                    "📊 *Статистика:*",
                    f"  📈 Трафик: {traffic}",
                    f"  🔑 Активных: {active}",
                    f"  📱 Онлайн: {online}{cpu_text}",
                ])
            else:
                error = stats.get('error', 'Нет подключения')
                lines.extend([
                    "",
                    "⚠️ *Ошибка:*",
                    f"  {error}",
                ])
        except VPNAPIError as e:
            logger.warning(f"Ошибка получения статистики {server['name']}: {e}")
            lines.extend([
                "",
                "⚠️ *Ошибка подключения*",
            ])
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении статистики: {e}")
            lines.extend([
                "",
                "⚠️ *Ошибка получения статистики*",
            ])
    
    text = "\n".join(lines)
    keyboard = server_view_kb(server['id'], server['is_active'])
    
    return text, keyboard


# ============================================================================
# СПИСОК СЕРВЕРОВ
# ============================================================================

@router.callback_query(F.data == "admin_servers")
async def show_servers_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает главный экран раздела серверов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.servers_list)
    await state.update_data(servers_page=0)
    
    # Получаем список серверов
    servers = await get_all_servers()
    
    # Формируем текст
    active_count = sum(1 for s in servers if s['is_active'])
    total_count = len(servers)
    
    text = (
        "🖥️ *Серверы*\n\n"
        f"📊 *Статистика:*\n"
        f"🟢 Активных: *{active_count}*\n"
        f"🔴 Всего: *{total_count}*\n\n"
        "Выберите сервер для управления."
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=servers_list_kb(servers),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_servers_list")
async def show_servers_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список серверов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.servers_list)
    
    # Получаем текущую страницу
    data = await state.get_data()
    page = data.get('servers_page', 0)
    
    await _show_servers_page(callback, state, page)


@router.callback_query(F.data.startswith("admin_servers_page:"))
async def change_servers_page(callback: CallbackQuery, state: FSMContext):
    """Переход на другую страницу списка."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        page = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    await state.update_data(servers_page=page)
    await _show_servers_page(callback, state, page)


# ============================================================================
# ПРОСМОТР СЕРВЕРА
# ============================================================================

@router.callback_query(F.data.startswith("admin_server_view:"))
async def show_server_view(callback: CallbackQuery, state: FSMContext):
    """Показывает карточку сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    server = await get_server_by_id(server_id)
    
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.server_view)
    await state.update_data(current_server_id=server_id)
    
    text, keyboard = await _format_server_card(server)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


# ============================================================================
# ДОБАВЛЕНИЕ СЕРВЕРА
# ============================================================================

@router.callback_query(F.data == "admin_server_add")
async def start_add_server(callback: CallbackQuery, state: FSMContext):
    """Начало добавления сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.add_server_name)
    
    await callback.message.edit_text(
        "➕ *Добавление сервера*\n\n"
        "Введите название сервера:",
        reply_markup=back_and_home_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.add_server_name, F.text)
async def process_add_server_name(message: Message, state: FSMContext):
    """Обработка ввода названия сервера."""
    if not is_admin(message.from_user.id):
        return
    
    name = message.text.strip()
    
    if not name or len(name) > 50:
        await message.answer(
            "❌ Название должно быть от 1 до 50 символов",
            parse_mode="Markdown"
        )
        return
    
    await state.set_state(AdminStates.add_server_host)
    await state.update_data(add_server_name=name)
    
    await message.answer(
        "🌐 *Добавление сервера*\n\n"
        f"Название: {name}\n\n"
        "Введите хост (IP или домен):",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_host, F.text)
async def process_add_server_host(message: Message, state: FSMContext):
    """Обработка ввода хоста сервера."""
    if not is_admin(message.from_user.id):
        return
    
    host = message.text.strip()
    
    if not host or len(host) > 100:
        await message.answer(
            "❌ Хост должен быть от 1 до 100 символов",
            parse_mode="Markdown"
        )
        return
    
    data = await state.get_data()
    name = data.get('add_server_name')
    
    await state.set_state(AdminStates.add_server_port)
    await state.update_data(add_server_host=host)
    
    await message.answer(
        "🔌 *Добавление сервера*\n\n"
        f"Название: {name}\n"
        f"Хост: {host}\n\n"
        "Введите порт панели 3X-UI:",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_port, F.text)
async def process_add_server_port(message: Message, state: FSMContext):
    """Обработка ввода порта сервера."""
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    if not text.isdigit() or not (1 <= int(text) <= 65535):
        await message.answer(
            "❌ Порт должен быть числом от 1 до 65535",
            parse_mode="Markdown"
        )
        return
    
    port = int(text)
    data = await state.get_data()
    name = data.get('add_server_name')
    host = data.get('add_server_host')
    
    await state.set_state(AdminStates.add_server_path)
    await state.update_data(add_server_port=port)
    
    await message.answer(
        "🔑 *Добавление сервера*\n\n"
        f"Название: {name}\n"
        f"Хост: {host}\n"
        f"Порт: {port}\n\n"
        "Введите секретный путь API (например, /api):",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_path, F.text)
async def process_add_server_path(message: Message, state: FSMContext):
    """Обработка ввода пути API сервера."""
    if not is_admin(message.from_user.id):
        return
    
    path = message.text.strip()
    
    if not path or len(path) > 50:
        await message.answer(
            "❌ Путь должен быть от 1 до 50 символов",
            parse_mode="Markdown"
        )
        return
    
    data = await state.get_data()
    name = data.get('add_server_name')
    host = data.get('add_server_host')
    port = data.get('add_server_port')
    
    await state.set_state(AdminStates.add_server_login)
    await state.update_data(add_server_path=path)
    
    await message.answer(
        "👤 *Добавление сервера*\n\n"
        f"Название: {name}\n"
        f"Хост: {host}\n"
        f"Порт: {port}\n"
        f"Путь: {path}\n\n"
        "Введите логин для панели:",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_login, F.text)
async def process_add_server_login(message: Message, state: FSMContext):
    """Обработка ввода логина сервера."""
    if not is_admin(message.from_user.id):
        return
    
    login = message.text.strip()
    
    if not login or len(login) > 50:
        await message.answer(
            "❌ Логин должен быть от 1 до 50 символов",
            parse_mode="Markdown"
        )
        return
    
    data = await state.get_data()
    name = data.get('add_server_name')
    host = data.get('add_server_host')
    port = data.get('add_server_port')
    path = data.get('add_server_path')
    
    await state.set_state(AdminStates.add_server_password)
    await state.update_data(add_server_login=login)
    
    await message.answer(
        "🔒 *Добавление сервера*\n\n"
        f"Название: {name}\n"
        f"Хост: {host}\n"
        f"Порт: {port}\n"
        f"Путь: {path}\n"
        f"Логин: {login}\n\n"
        "Введите пароль для панели:",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_password, F.text)
async def process_add_server_password(message: Message, state: FSMContext):
    """Обработка ввода пароля сервера."""
    if not is_admin(message.from_user.id):
        return
    
    password = message.text.strip()
    
    if not password or len(password) > 100:
        await message.answer(
            "❌ Пароль должен быть от 1 до 100 символов",
            parse_mode="Markdown"
        )
        return
    
    data = await state.get_data()
    name = data.get('add_server_name')
    host = data.get('add_server_host')
    port = data.get('add_server_port')
    path = data.get('add_server_path')
    login = data.get('add_server_login')
    
    await state.set_state(AdminStates.add_server_protocol)
    await state.update_data(add_server_password=password)
    
    await message.answer(
        "🔗 *Добавление сервера*\n\n"
        f"Название: {name}\n"
        f"Хост: {host}\n"
        f"Порт: {port}\n"
        f"Путь: {path}\n"
        f"Логин: {login}\n"
        f"Пароль: {'*' * len(password)}\n\n"
        "Введите протокол подключения (http или https):",
        parse_mode="Markdown"
    )


@router.message(AdminStates.add_server_protocol, F.text)
async def process_add_server_protocol(message: Message, state: FSMContext):
    """Обработка ввода протокола сервера."""
    if not is_admin(message.from_user.id):
        return
    
    protocol = message.text.strip().lower()
    
    if protocol not in ['http', 'https']:
        await message.answer(
            "❌ Протокол должен быть 'http' или 'https'",
            parse_mode="Markdown"
        )
        return
    
    data = await state.get_data()
    name = data.get('add_server_name')
    host = data.get('add_server_host')
    port = data.get('add_server_port')
    path = data.get('add_server_path')
    login = data.get('add_server_login')
    password = data.get('add_server_password')
    
    # Создаём сервер
    server_id = await add_server(
        name=name,
        host=host,
        port=port,
        web_base_path=path,
        login=login,
        password=password,
        protocol=protocol
    )
    
    await message.answer(f"✅ Сервер добавлен! ID: {server_id}")
    
    # Проверяем подключение
    try:
        server = await get_server_by_id(server_id)
        client = get_client_from_server_data(server)
        stats = await client.get_stats()
        
        if stats.get('online'):
            await message.answer("🟢 Подключение к панели успешно!")
        else:
            await message.answer(f"⚠️ Подключение не удалось: {stats.get('error', 'Неизвестная ошибка')}")
    except VPNAPIError as e:
        await message.answer(f"⚠️ Ошибка подключения: {e}")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка проверки подключения: {e}")
    
    # Возвращаемся к просмотру сервера
    await state.set_state(AdminStates.server_view)
    await state.update_data(current_server_id=server_id)


# ============================================================================
# РЕДАКТИРОВАНИЕ СЕРВЕРА
# ============================================================================

@router.callback_query(F.data.startswith("admin_server_edit:"))
async def start_edit_server(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    server = await get_server_by_id(server_id)
    
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.edit_server_field)
    await state.update_data(current_server_id=server_id)
    
    await callback.message.edit_text(
        "✏️ *Редактирование сервера*\n\n"
        f"Сервер: {escape_md(server['name'])}\n\n"
        "Выберите поле для редактирования:",
        reply_markup=server_edit_field_kb(server_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_server_field:"))
async def select_edit_server_field(callback: CallbackQuery, state: FSMContext):
    """Выбор поля для редактирования."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            raise IndexError("Not enough parts")
        server_id = int(parts[1])
        field = parts[2]
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    
    server = await get_server_by_id(server_id)
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.edit_server_value)
    await state.update_data(edit_server_id=server_id, edit_server_field=field)
    
    # Формируем текст в зависимости от поля
    field_names = {
        'name': 'название',
        'host': 'хост',
        'port': 'порт',
        'web_base_path': 'путь API',
        'login': 'логин',
        'password': 'пароль',
        'protocol': 'протокол'
    }
    
    current_value = server.get(field, '')
    if field == 'password':
        current_value = '*' * len(current_value)
    
    await callback.message.edit_text(
        f"✏️ *Редактирование поля*\n\n"
        f"Сервер: {escape_md(server['name'])}\n"
        f"Поле: {field_names.get(field, field)}\n"
        f"Текущее значение: `{current_value}`\n\n"
        "Введите новое значение:",
        reply_markup=server_edit_kb(server_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(AdminStates.edit_server_value, F.text)
async def process_edit_server_value(message: Message, state: FSMContext):
    """Обработка ввода нового значения поля."""
    if not is_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    data = await state.get_data()
    server_id = data.get('edit_server_id')
    field = data.get('edit_server_field')
    
    if not server_id or not field:
        await message.answer("❌ Ошибка данных")
        return
    
    # Валидация значения в зависимости от поля
    if field == 'name' and (not text or len(text) > 50):
        await message.answer("❌ Название должно быть от 1 до 50 символов")
        return
    elif field == 'host' and (not text or len(text) > 100):
        await message.answer("❌ Хост должен быть от 1 до 100 символов")
        return
    elif field == 'port' and (not text.isdigit() or not (1 <= int(text) <= 65535)):
        await message.answer("❌ Порт должен быть числом от 1 до 65535")
        return
    elif field == 'web_base_path' and (not text or len(text) > 50):
        await message.answer("❌ Путь должен быть от 1 до 50 символов")
        return
    elif field == 'login' and (not text or len(text) > 50):
        await message.answer("❌ Логин должен быть от 1 до 50 символов")
        return
    elif field == 'password' and (not text or len(text) > 100):
        await message.answer("❌ Пароль должен быть от 1 до 100 символов")
        return
    elif field == 'protocol' and text.lower() not in ['http', 'https']:
        await message.answer("❌ Протокол должен быть 'http' или 'https'")
        return
    
    # Обновляем поле
    if field == 'port':
        value = int(text)
    elif field == 'protocol':
        value = text.lower()
    else:
        value = text
    
    success = await update_server_field(server_id, field, value)
    
    if success:
        await message.answer(f"✅ Поле '{field}' успешно обновлено!")
        
        # Проверяем подключение если изменились критичные поля
        if field in ['host', 'port', 'web_base_path', 'login', 'password', 'protocol']:
            try:
                server = await get_server_by_id(server_id)
                client = get_client_from_server_data(server)
                stats = await client.get_stats()
                
                if stats.get('online'):
                    await message.answer("🟢 Подключение к панели успешно!")
                else:
                    await message.answer(f"⚠️ Подключение не удалось: {stats.get('error', 'Неизвестная ошибка')}")
            except VPNAPIError as e:
                await message.answer(f"⚠️ Ошибка подключения: {e}")
            except Exception as e:
                await message.answer(f"⚠️ Ошибка проверки подключения: {e}")
        
        # Возвращаемся к просмотру сервера
        await state.set_state(AdminStates.server_view)
        await state.update_data(current_server_id=server_id)
    else:
        await message.answer("❌ Ошибка обновления поля")


# ============================================================================
# УДАЛЕНИЕ СЕРВЕРА
# ============================================================================

@router.callback_query(F.data.startswith("admin_server_delete:"))
async def request_server_delete(callback: CallbackQuery, state: FSMContext):
    """Запрос подтверждения удаления сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    server = await get_server_by_id(server_id)
    
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.delete_server_confirm)
    await state.update_data(delete_server_id=server_id)
    
    await callback.message.edit_text(
        f"⚠️ *Подтверждение удаления*\n\n"
        f"Вы уверены, что хотите удалить сервер `{escape_md(server['name'])}`?\n\n"
        "⚠️ *Внимание:* Это действие удалит все ключи, привязанные к этому серверу!",
        reply_markup=server_delete_confirm_kb(server_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_delete_server_confirm:"))
async def confirm_server_delete(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и удаление сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    
    success = await delete_server(server_id)
    
    if success:
        await callback.answer("✅ Сервер удалён!", show_alert=True)
        
        # Возвращаемся в меню серверов
        await state.set_state(AdminStates.servers_list)
        
        servers = await get_all_servers()
        active_count = sum(1 for s in servers if s['is_active'])
        total_count = len(servers)
        
        text = (
            "🖥️ *Серверы*\n\n"
            f"📊 *Статистика:*\n"
            f"🟢 Активных: *{active_count}*\n"
            f"🔴 Всего: *{total_count}*\n\n"
            "Выберите сервер для управления."
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=servers_list_kb(servers),
            parse_mode="Markdown"
        )
    else:
        await callback.answer("❌ Ошибка удаления сервера", show_alert=True)


# ============================================================================
# ПЕРЕКЛЮЧЕНИЕ АКТИВНОСТИ
# ============================================================================

@router.callback_query(F.data.startswith("admin_server_toggle_active:"))
async def request_server_toggle_active(callback: CallbackQuery, state: FSMContext):
    """Запрос подтверждения переключения активности сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    server = await get_server_by_id(server_id)
    
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    is_active = bool(server.get('is_active'))
    
    await state.set_state(AdminStates.toggle_server_active_confirm)
    await state.update_data(toggle_server_id=server_id)
    
    action = "деактивировать" if is_active else "активировать"
    
    await callback.message.edit_text(
        f"⚠️ *Подтверждение*\n\n"
        f"Вы уверены, что хотите {action} сервер `{escape_md(server['name'])}`?",
        reply_markup=server_active_confirm_kb(server_id, is_active),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_toggle_server_active_confirm:"))
async def confirm_server_toggle_active(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и переключение активности сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    try:
        server_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return
    new_status = await toggle_server_active(server_id)
    
    if new_status is None:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    if new_status:
        await callback.answer("✅ Сервер активирован!", show_alert=True)
    else:
        await callback.answer("✅ Сервер деактивирован!", show_alert=True)
    
    # Перезагружаем карточку
    server = await get_server_by_id(server_id)
    if server:
        await state.set_state(AdminStates.server_view)
        text, keyboard = await _format_server_card(server)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


# ============================================================================
# ОТМЕНЫ
# ============================================================================

@router.callback_query(F.data == "admin_server_cancel")
async def cancel_server_action(callback: CallbackQuery, state: FSMContext):
    """Отмена действия с сервером."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.servers_list)
    await callback.answer("❌ Действие отменено")
    
    # Возвращаемся в меню серверов
    servers = await get_all_servers()
    active_count = sum(1 for s in servers if s['is_active'])
    total_count = len(servers)
    
    text = (
        "🖥️ *Серверы*\n\n"
        f"📊 *Статистика:*\n"
        f"🟢 Активных: *{active_count}*\n"
        f"🔴 Всего: *{total_count}*\n\n"
        "Выберите сервер для управления."
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=servers_list_kb(servers),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "admin_server_back")
async def back_to_server_view(callback: CallbackQuery, state: FSMContext):
    """Возврат к просмотру сервера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.server_view)
    await callback.answer("⬅️ Назад")
    
    # Показываем карточку сервера
    data = await state.get_data()
    server_id = data.get('current_server_id')
    if server_id:
        server = await get_server_by_id(server_id)
        if server:
            text, keyboard = await _format_server_card(server)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")