import sqlite3
import random
import re
import logging
import asyncio

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- КОНФИГУРАЦИЯ ---
# ВАЖНО: Вставьте сюда ваш токен от BotFather
BOT_TOKEN = ""
# ВАЖНО: Установите надежный пароль для административных команд
ADMIN_PASSWORD = "п" # <-- ЗАМЕНИТЕ НА СВОЙ ПАРОЛЬ

# --- НАСТРОЙКА ЛОГГИРОВАНИЯ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- УПРАВЛЕНИЕ БАЗОЙ ДАННЫХ ---

def init_db():
    """Инициализирует базу данных и создает таблицы, если они не существуют."""
    with sqlite3.connect('bot_database.db') as conn:
        cursor = conn.cursor()
        # Таблица для слов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS words (
                word TEXT PRIMARY KEY
            )
        ''')
        # Таблица для пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                last_message TEXT,
                last_message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def add_words_to_db(text: str):
    """Очищает текст и добавляет слова в базу данных."""
    cleaned_text = re.sub(r'[^а-яА-Яa-zA-Z\s]', '', text).lower()
    words = {word for word in cleaned_text.split() if len(word) > 2}

    if not words:
        return

    with sqlite3.connect('bot_database.db') as conn:
        cursor = conn.cursor()
        for word in words:
            cursor.execute("INSERT OR IGNORE INTO words (word) VALUES (?)", (word,))
        conn.commit()

def get_random_words(seed_words: list = None) -> list:
    """
    Возвращает список случайных слов.
    Если переданы seed_words, пытается включить некоторые из них в ответ.
    """
    with sqlite3.connect('bot_database.db') as conn:
        cursor = conn.cursor()
        # Получаем общее количество слов для дальнейших проверок
        cursor.execute("SELECT COUNT(*) FROM words")
        total_words = cursor.fetchone()[0]

        # Если слов слишком мало, выходим
        if total_words < 5:
            return []

        reply_words = []
        num_random_words = random.randint(3, 7)

        # Добавляем одно или два "похожих" слова из сообщения пользователя
        if seed_words:
            random.shuffle(seed_words)
            for i in range(random.randint(1, 2)):
                if seed_words:
                    reply_words.append(seed_words.pop())

        # Добавляем остальные случайные слова из всей базы
        words_to_fetch = num_random_words - len(reply_words)
        if words_to_fetch > 0:
            cursor.execute("SELECT word FROM words ORDER BY RANDOM() LIMIT ?", (words_to_fetch,))
            random_db_words = [row[0] for row in cursor.fetchall()]
            reply_words.extend(random_db_words)

        random.shuffle(reply_words)
        return reply_words

def add_user_to_db(user_id: int, username: str, last_message: str = None):
    """Добавляет или обновляет пользователя в базе данных."""
    with sqlite3.connect('bot_database.db') as conn:
        cursor = conn.cursor()
        if last_message:
            cursor.execute(
                """INSERT INTO users (user_id, username, last_message) 
                   VALUES (?, ?, ?) 
                   ON CONFLICT(user_id) 
                   DO UPDATE SET username=excluded.username, last_message=excluded.last_message, last_message_time=CURRENT_TIMESTAMP""",
                (user_id, username, last_message)
            )
        else:
            cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                (user_id, username)
            )
        conn.commit()

def get_all_users() -> list:
    """Возвращает список всех пользователей из базы данных с их последними сообщениями."""
    with sqlite3.connect('bot_database.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, last_message FROM users ORDER BY last_message_time DESC")
        return cursor.fetchall()

# --- ОБРАБОТЧИКИ КОМАНД ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    add_user_to_db(user.id, user.username)
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я бот, который учится на твоих сообщениях. "
        "Пиши мне что-нибудь, и я буду запоминать слова и отвечать случайными комбинациями. 🧠\n\n"
        "Попробуй что-нибудь написать!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения от пользователя."""
    user = update.effective_user
    user_text = update.message.text

    if not user_text:
        return

    # Добавляем пользователя и слова в БД
    add_user_to_db(user.id, user.username, user_text)
    add_words_to_db(user_text)

    # Генерируем "похожие" слова для ответа
    user_words = [word for word in re.sub(r'[^а-яА-Яa-zA-Z\s]', '', user_text).lower().split() if len(word) > 2]
    reply_words = get_random_words(seed_words=user_words)

    if len(reply_words) < 3:
        await update.message.reply_text("Пока у меня мало слов... Напиши ещё что-нибудь! 😅")
    else:
        reply = ' '.join(reply_words).capitalize() + '.'
        await update.message.reply_text(reply)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /status. Показывает статистику по боту.
    Требует пароль: /status [пароль]
    """
    try:
        password = context.args[0]
        if password != ADMIN_PASSWORD:
            await update.message.reply_text("⛔ Неверный пароль.")
            return
    except (IndexError, TypeError):
        await update.message.reply_text("⚠️ Неверный формат. Используйте: /status [пароль]")
        return

    users = get_all_users()
    user_count = len(users)
    
    message = f"📊 <b>Статус бота</b>\n\n"
    message += f"👥 <b>Всего пользователей:</b> {user_count}\n\n"
    message += "<b>Последние сообщения пользователей:</b>\n\n"

    if not users:
        message += "Пользователей пока нет."
        await update.message.reply_text(message, parse_mode='HTML')
        return

    # Формируем список пользователей с их последними сообщениями
    user_messages = []
    for user_id, username, last_message in users:
        username_display = f"@{username}" if username else f"ID:{user_id}"
        last_msg_display = last_message if last_message else "нет сообщений"
        # Экранируем HTML-спецсимволы
        last_msg_display = last_msg_display.replace('<', '&lt;').replace('>', '&gt;')
        # Обрезаем длинные сообщения
        truncated_msg = (last_msg_display[:50] + '...') if len(last_msg_display) > 50 else last_msg_display
        user_messages.append(f"{username_display} - {truncated_msg}")

    # Отправляем основную информацию
    await update.message.reply_text(message, parse_mode='HTML')
    
    # Отправляем список пользователей с сообщениями частями
    chunk_size = 10  # по 10 пользователей в сообщении
    for i in range(0, len(user_messages), chunk_size):
        chunk = user_messages[i:i + chunk_size]
        await update.message.reply_text("\n".join(chunk), parse_mode='HTML')

async def say(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /say. Отправляет сообщение всем пользователям.
    Требует пароль: /say [пароль] [сообщение]
    """
    try:
        password = context.args[0]
        if password != ADMIN_PASSWORD:
            await update.message.reply_text("⛔ Неверный пароль.")
            return

        message_to_send = " ".join(context.args[1:])
        if not message_to_send:
            raise IndexError

    except (IndexError, TypeError):
        await update.message.reply_text("⚠️ Неверный формат. Используйте: /say [пароль] [сообщение]")
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("Бот еще никто не использовал, отправлять некому.")
        return

    await update.message.reply_text(f"⏳ Начинаю рассылку. Всего пользователей: {len(users)}. Ожидайте...")
    
    success_count = 0
    failed_count = 0
    
    for user_id, _, _ in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=message_to_send)
            success_count += 1
            await asyncio.sleep(0.1) # Небольшая задержка, чтобы не попасть под лимиты Telegram
        except Forbidden:
            logging.warning(f"Пользователь {user_id} заблокировал бота.")
            failed_count += 1
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            failed_count += 1

    await update.message.reply_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"👍 Отправлено успешно: {success_count}\n"
        f"👎 Не удалось отправить: {failed_count}",
        parse_mode='Markdown'
    )

# --- ЗАПУСК БОТА ---

def main():
    """Основная функция для запуска бота."""
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("say", say))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Бот запущен ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
