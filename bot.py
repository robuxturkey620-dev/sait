"""
Telegram-бот: генератор ссылок на WhatsApp с готовым текстом для холодных
сообщений (кафе / салон красоты).

Как это работает:
1. Пользователь первый раз пишет боту -> бот спрашивает имя
   (оно будет подставляться в текст сообщения вместо "Михаил").
2. В любой момент пользователь отправляет номер телефона клиента
   (в любом формате: с +, пробелами, тире и т.д.).
3. Бот спрашивает тип заведения: Кафе / Салон красоты (кнопки).
4. Бот возвращает готовую ссылку wa.me с номером без лишних символов
   и текстом, в который подставлено имя пользователя.
5. Если поставить реакцию ❤️ (красное сердечко) на любое сообщение в
   чате с ботом — это сообщение удалится, чтобы не копился мусор.

Запуск:
    pip install -r requirements.txt
    export BOT_TOKEN="ваш_токен_от_BotFather"
    python bot.py
"""

import json
import logging
import os
import re
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_СВОЙ_ТОКЕН")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

# --------------------------------------------------------------------------- #
# Хранение имени пользователя (просто json-файл: {telegram_id: "Имя"})
# --------------------------------------------------------------------------- #


def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(data: dict) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_name(user_id: int) -> str | None:
    return _load_users().get(str(user_id))


def set_name(user_id: int, name: str) -> None:
    data = _load_users()
    data[str(user_id)] = name
    _save_users(data)


# --------------------------------------------------------------------------- #
# Шаблоны текста. {name} будет заменено на имя пользователя.
# --------------------------------------------------------------------------- #

TEMPLATES = {
    "salon": (
        "Добрый день! Меня зовут {name}. Мне очень нравится ваш салон и работы "
        "мастеров, но заметил, что у вас нет своего сайта. Сейчас клиенты "
        "выбирают бьюти-мастеров и смотрят прайс через интернет, поэтому сайт "
        "вам точно поднимет продажи и привлечет больше людей. Предлагаю "
        "сделать для вас стильный и удобный сайт, который решит главные "
        "задачи: Онлайн-запись 24/7: клиенты смогут сами записываться на "
        "услуги в любое время суток. Администратору не придется постоянно "
        "висеть на телефоне. Красивое портфолио и прайс: все ваши лучшие "
        "работы («до/после»), услуги и цены будут разложены по полочкам и в "
        "крутом дизайне. Знакомство с мастерами: можно добавить карточки "
        "мастеров с их опытом и отзывами, чтобы повысить доверие новых "
        "клиентов. Акции и сертификаты: баннеры со скидками и возможность "
        "купить подарочный сертификат прямо на сайте. Сделаю аккуратный и "
        "эстетичный дизайн под стиль вашего бренда. Если интересно, могу "
        "скинуть примеры работ и обсудить, каким можно сделать сайт для вас. "
        "Что скажете?"
    ),
    "cafe": (
        "Добрый день! Меня зовут {name}. Мне очень нравится ваше заведение, "
        "но заметил, что у вас нет своего сайта.\n"
        "Сейчас все ищут меню и бронируют столы через интернет, поэтому сайт "
        "вам точно поднимет выручку. Предлагаю сделать для вас стильный и "
        "быстрый сайт, который решит сразу несколько задач:\n"
        "Красивое онлайн-меню: гости увидят сочные фотки блюд и сразу "
        "захотят к вам прийти.\n"
        "Бронь столов онлайн: клиенты смогут сами занимать места на сайте, "
        "это разгрузит ваших администраторов.\n"
        "Акции и инфо: все скидки, отзывы и карта проезда будут в одном "
        "месте.\n"
        "Доставка/Самовывоз: если есть доставка, гости смогут заказывать "
        "напрямую, а вы не будете платить комиссию другим сервисам.\n"
        "Сделаю уникальный дизайн под стиль вашего кафе.\n"
        "Если интересно, могу скинуть примеры работ (портфолио) и прикинуть, "
        "каким можно сделать сайт для вас. Что скажете?"
    ),
}

LABELS = {"salon": "салон красоты", "cafe": "кафе"}

# Достаточно длинная последовательность цифр в сообщении = считаем номером телефона
PHONE_RE = re.compile(r"[\d+()\s\-]{9,}")


def normalize_phone(raw: str) -> str | None:
    """Достаёт только цифры и приводит к формату 7XXXXXXXXXX."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits


def build_link(phone: str, biz_type: str, name: str) -> str:
    text = TEMPLATES[biz_type].format(name=name)
    encoded = quote(text)
    return (
        f"https://api.whatsapp.com/send/?phone={phone}"
        f"&text={encoded}&type=phone_number&app_absent=0"
    )


# --------------------------------------------------------------------------- #
# Хендлеры
# --------------------------------------------------------------------------- #


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = get_name(update.effective_user.id)
    if name:
        await update.message.reply_text(
            f"Привет, {name}! Просто отправьте номер телефона клиента — "
            f"в любом формате."
        )
    else:
        context.user_data["awaiting_name"] = True
        await update.message.reply_text(
            "Привет! Какое ваше имя? Оно будет использоваться для отправки "
            "текста."
        )


async def change_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_name"] = True
    await update.message.reply_text("Хорошо, как вас теперь называть?")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 1) Ждём имя
    if context.user_data.get("awaiting_name"):
        set_name(user_id, text)
        context.user_data["awaiting_name"] = False
        pending_phone = context.user_data.get("phone")
        if pending_phone:
            await ask_type(update, context)
        else:
            await update.message.reply_text(
                f"Приятно познакомиться, {text}! Теперь отправьте номер "
                f"телефона клиента."
            )
        return

    # 2) Похоже на номер телефона?
    if PHONE_RE.fullmatch(text) or sum(c.isdigit() for c in text) >= 10:
        phone = normalize_phone(text)
        if not phone:
            await update.message.reply_text(
                "Не получилось распознать номер телефона. Отправьте, "
                "пожалуйста, ещё раз."
            )
            return

        context.user_data["phone"] = phone

        if not get_name(user_id):
            context.user_data["awaiting_name"] = True
            await update.message.reply_text(
                "Сначала: какое ваше имя? Оно будет использоваться для "
                "отправки текста."
            )
            return

        await ask_type(update, context)
        return

    # 3) Не похоже ни на что — подсказка
    await update.message.reply_text(
        "Отправьте номер телефона клиента (например, +7 701 204 50 64), "
        "и я подготовлю ссылку. Команда /name — изменить ваше имя."
    )


async def ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("☕ Кафе", callback_data="cafe"),
            InlineKeyboardButton("💇 Салон красоты", callback_data="salon"),
        ]
    ]
    await update.message.reply_text(
        "Какой тип заведения?", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если на сообщение поставили красное сердечко ❤️ — удаляем его,
    чтобы не накапливался мусор в чате."""
    reaction = update.message_reaction
    if not reaction:
        return

    new_emojis = [
        r.emoji for r in reaction.new_reaction if getattr(r, "emoji", None)
    ]
    if not any("❤" in e for e in new_emojis):
        return

    try:
        await context.bot.delete_message(
            chat_id=reaction.chat.id, message_id=reaction.message_id
        )
    except BadRequest as e:
        # Например, сообщению больше 48 часов, или его уже удалили
        logger.warning("Не удалось удалить сообщение %s: %s", reaction.message_id, e)


async def handle_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    biz_type = query.data
    phone = context.user_data.get("phone")
    name = get_name(query.from_user.id)

    if not phone:
        await query.edit_message_text(
            "Не вижу номера телефона — отправьте его ещё раз."
        )
        return
    if not name:
        await query.edit_message_text(
            "Не вижу вашего имени — напишите /name и укажите имя."
        )
        return

    link = build_link(phone, biz_type, name)
    label = LABELS[biz_type]

    # Длинная ссылка (кириллица в %XX-кодировке) легко превышает лимит
    # Telegram на текст сообщения (4096 символов), поэтому отдаём её как
    # кнопку, а не как текст — у поля url такого лимита нет.
    keyboard = [[InlineKeyboardButton("📲 Открыть в WhatsApp", url=link)]]
    await query.edit_message_text(
        f"АЛИХАН СЫН ШЛЮХИ! Ссылка для {label} (номер {phone}) ниже 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    # очищаем номер, чтобы случайно не переиспользовать его для другого клиента
    context.user_data.pop("phone", None)


def main() -> None:
    if BOT_TOKEN == "ВСТАВЬТЕ_СЮДА_СВОЙ_ТОКЕН":
        raise SystemExit(
            "Укажите токен бота в переменной окружения BOT_TOKEN "
            "(получить его можно у @BotFather)."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("name", change_name))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_type_choice))
    app.add_handler(MessageReactionHandler(handle_reaction))

    logger.info("Бот запущен")
    # allowed_updates=Update.ALL_TYPES обязателен, иначе Telegram не будет
    # присылать обновления о реакциях на сообщения.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
