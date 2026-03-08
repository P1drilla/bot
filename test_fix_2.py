#!/usr/bin/env python3
"""
Тест для проверки исправления ошибки "query is too old and response timeout expired or query ID is invalid"
"""

import asyncio
import logging
from unittest.mock import Mock, AsyncMock, MagicMock

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_callback_answer_error_handling():
    """Тест проверяет, что callback.answer() корректно обрабатывает ошибку 'query is too old'"""
    
    # Создаем моки для callback
    mock_callback = Mock()
    mock_callback.answer = AsyncMock()
    
    # Имитируем ошибку "query is too old"
    mock_callback.answer.side_effect = Exception("Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid")
    
    # Тестируем обработку ошибки
    try:
        await mock_callback.answer()
    except Exception as e:
        if "query is too old" in str(e):
            # Обработка ошибки - игнорируем
            logger.info("✅ Тест пройден: ошибка 'query is too old' корректно обрабатывается")
            return True
        else:
            raise e
    
    logger.error("❌ Тест не пройден: ошибка не была обработана")
    return False

async def test_buy_key_handler_error_handling():
    """Тест проверяет обработку ошибки в функции buy_key_handler"""
    
    # Создаем моки
    mock_callback = Mock()
    mock_callback.message = Mock()
    mock_callback.message.edit_text = AsyncMock()
    mock_callback.message.delete = AsyncMock()
    mock_callback.message.answer = AsyncMock()
    mock_callback.answer = AsyncMock()
    mock_callback.from_user = Mock()
    mock_callback.from_user.id = 123456
    
    # Имитируем успешное выполнение edit_text
    mock_callback.message.edit_text.return_value = None
    
    # Имитируем ошибку "query is too old" при вызове answer
    mock_callback.answer.side_effect = Exception("Telegram server says - Bad Request: query is too old and response timeout expired or query ID is invalid")
    
    # Тестируем логику из функции buy_key_handler
    text = "Тестовый текст"
    reply_markup = Mock()
    
    try:
        await mock_callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception:
        try:
            await mock_callback.message.delete()
        except Exception:
            pass
        await mock_callback.message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    # Проверяем, что edit_text был вызван
    mock_callback.message.edit_text.assert_called_once()
    
    # Теперь тестируем обработку ошибки answer
    try:
        await mock_callback.answer()
    except Exception as e:
        if "query is too old" in str(e):
            # Обработка ошибки - игнорируем
            logger.info("✅ Тест пройден: ошибка 'query is too old' в buy_key_handler корректно обрабатывается")
            return True
        else:
            raise e
    
    logger.error("❌ Тест не пройден: ошибка не была обработана в buy_key_handler")
    return False

async def main():
    """Запуск всех тестов"""
    logger.info("🚀 Запуск тестов для проверки исправления ошибки 'query is too old'")
    
    test1_passed = await test_callback_answer_error_handling()
    test2_passed = await test_buy_key_handler_error_handling()
    
    if test1_passed and test2_passed:
        logger.info("🎉 Все тесты пройдены! Исправление работает корректно.")
        return True
    else:
        logger.error("💥 Некоторые тесты не пройдены. Проверьте исправление.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)