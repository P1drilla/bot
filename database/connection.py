"""
Модуль подключения к базе данных SQLite (асинхронный).

Предоставляет асинхронный контекстный менеджер для безопасной работы с БД.
"""
import aiosqlite
from pathlib import Path

# Путь к файлу базы данных
DB_PATH = Path(__file__).parent / "vpn_bot.db"


async def get_connection() -> aiosqlite.Connection:
    """
    Создаёт новое асинхронное соединение с БД.
    
    Returns:
        aiosqlite.Connection: Соединение с БД
    """
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row  # Доступ к полям по имени
    await conn.execute("PRAGMA foreign_keys = ON")  # Включаем FK
    await conn.commit()
    return conn


async def get_db():
    """
    Асинхронный контекстный менеджер для работы с БД.
    
    Автоматически делает commit при успехе и rollback при ошибке.
    
    Пример:
        async with get_db() as conn:
            cursor = await conn.execute("SELECT * FROM users")
            users = await cursor.fetchall()
    
    Yields:
        aiosqlite.Connection: Соединение с БД
    """
    conn = await get_connection()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def init_db():
    """
    Инициализирует БД (создаёт файл если его нет).
    Вызывается при первом запуске.
    """
    if not DB_PATH.exists():
        conn = await aiosqlite.connect(DB_PATH)
        await conn.close()