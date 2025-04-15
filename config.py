import os
from dotenv import load_dotenv

# Этот файл загружает переменные окружения из файла .env, чтобы использовать их в программе.

load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не задан токен бота. Установите переменную окружения BOT_TOKEN или создайте файл .env")

# Настройки для проверки событий
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # Интервал проверки событий в секундах (по умолчанию 5 минут)
NOTIFICATION_TIME = int(os.getenv("NOTIFICATION_TIME", 15))  # За сколько минут до события отправлять уведомление

# Настройки базы данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/telegram_bot")

# ID владельца бота (может назначать администраторов)
OWNER_ID = int(os.getenv("OWNER_ID", 0))  # ID владельца бота в Telegram