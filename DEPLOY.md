## Развёртывание Yadreno VPN бота

### 1. Требования

- Ubuntu 22.04+ (рекомендуется)
- Python 3.10+
- `git`, `python3-pip`
- systemd (по умолчанию есть в Ubuntu)

### 2. Клонирование и установка зависимостей

```bash
git clone https://github.com/plushkinv/YadrenoVPN.git
cd YadrenoVPN

python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Настройка `config.py`

1. Скопируйте пример:

```bash
cp config.py.example config.py
```

2. Отредактируйте `config.py`:
   - `BOT_TOKEN` — токен бота от `@BotFather`
   - `ADMIN_IDS` — список Telegram ID администраторов
   - При необходимости настройте дополнительные параметры (лимиты, GitHub‑репозиторий и т.д.).

### 4. Первый запуск (проверка)

```bash
python3 main.py
```

- Убедитесь, что бот стартует без ошибок.
- При первом запуске будут применены все миграции к БД (`database/vpn_bot.db`).

Остановите бота (`Ctrl+C`), если он успешно запустился.

### 5. Настройка автозапуска через systemd

1. Скопируйте unit‑файл (из корня репозитория):

```bash
cp yadreno-vpn.service /etc/systemd/system/yadreno-vpn.service
```

2. Отредактируйте `/etc/systemd/system/yadreno-vpn.service`:

- `User=` — под каким пользователем запускать (например, `root` или отдельный пользователь).
- `WorkingDirectory=` — путь к каталогу проекта (например, `/root/YadrenoVPN`).
- `ExecStart=` — при необходимости укажите путь до нужного интерпретатора Python или виртуального окружения.

Пример для venv:

```ini
ExecStart=/root/YadrenoVPN/venv/bin/python main.py
WorkingDirectory=/root/YadrenoVPN
```

3. Примените изменения и включите сервис:

```bash
systemctl daemon-reload
systemctl enable yadreno-vpn
systemctl start yadreno-vpn
```

4. Проверка статуса:

```bash
systemctl status yadreno-vpn
journalctl -u yadreno-vpn -f
```

### 6. Обновление бота

```bash
cd /path/to/YadrenoVPN
git pull
pip install -r requirements.txt
systemctl restart yadreno-vpn
```

При необходимости миграции будут применены автоматически при следующем запуске бота.

