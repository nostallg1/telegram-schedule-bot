import logging
import os  # <-- ВАЖЛИВО: Додано цей імпорт
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Імпортуємо нашу функцію
from parser import fetch_schedule_data

# ----- БЕЗПЕЧНЕ ОТРИМАННЯ ТОКЕНА -----
# Цей код читає токен, який ми "сховали" у файлі .bashrc на PythonAnywhere
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

# Перевірка, чи токен знайдено (на випадок помилки)
if not TELEGRAM_TOKEN:
    # Цей print буде видно лише в логах на сервері
    print("ПОМИЛКА: Не вдалося знайти TELEGRAM_TOKEN у змінних оточення.")
# ------------------------------------


# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Обробники команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    await update.message.reply_text(f'Привіт, {user_name}! Надішли /rozklad, щоб отримати розклад для АВ-11. Для інформації напиши /info')


async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info(f"Користувач {chat_id} запросив розклад.")

    await update.message.reply_text('Шукаю розклад')

    try:
        # Викликаємо наш парсер!
        rozklad_text = fetch_schedule_data(group_name="АВ-11", semester="1", duration="1")

        # Надсилаємо результат
        await update.message.reply_text(rozklad_text)
        logger.info(f"Надіслано розклад для {chat_id}.")

    except Exception as e:
        logger.error(f"Помилка при отриманні розкладу: {e}")
        await update.message.reply_text(' Не можу отримати розклад. ')


# --- Нова функція для команди /info ---
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Надсилає інформаційне повідомлення."""
    info_text = (
        "Я бот, створений для парсингу розкладу.\n"
        "Зараз я вмію:\n"
        "/start - привітатися\n"
        "/rozklad - показати розклад для АВ-11\n"
        "/info - показати це повідомлення\n"
        "/support - підтримка автора\n"
    )
    await update.message.reply_text(info_text)

# --- Нова функція для команди /support (ВИПРАВЛЕНО) ---
# (Вона тепер знаходиться ЗОВНІ функції info)
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Надсилає текст підтримки."""
    await update.message.reply_text('підтримка 4441111131351441')


# --- Головна функція ---

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Реєструємо всі команди
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rozklad", get_rozklad))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("support", support)) # <-- Тепер це спрацює

    print("Бот запущений... (Не забудь увімкнути VPN)")
    application.run_polling()


if __name__ == '__main__':
    main()