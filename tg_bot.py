import os
import logging
import re
from io import BytesIO

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Filters, Updater, CallbackContext,
    CallbackQueryHandler, CommandHandler, MessageHandler,
    ConversationHandler
)
from telegram.error import BadRequest


_database = None


START, HANDLE_MENU, HANDLE_CART, WAITING_EMAIL = range(4)


def init_strapi_session(api_url, token):
    """Инициализирует сессию для работы с Strapi API."""
    session = requests.Session()
    session.headers.update({
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    return session


def get_or_create_cart(session, api_url, telegram_id):
    """Возвращает существующую корзину или создает новую."""
    try:
        response = session.get(
            f"{api_url}/api/carts",
            params={"filters[telegram_id][$eq]": str(telegram_id)}
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('data') and data['data']:
            return data['data'][0]
        
        cart_data = {"data": {"telegram_id": str(telegram_id)}}
        response = session.post(f"{api_url}/api/carts", json=cart_data)
        response.raise_for_status()
        return response.json().get('data', {})
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка работы с корзиной: {e}")
        return None


def get_cart_items(session, api_url, cart_documentId):
    """Возвращает элементы корзины с деталями товаров."""
    params = {
        "filters[cart][documentId][$eq]": cart_documentId,
        "populate": "product"
    }
    try:
        response = session.get(f"{api_url}/api/cart-products", params=params)
        response.raise_for_status()
        return response.json().get('data', [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка получения корзины: {e}")
        return []


def add_to_cart(session, api_url, cart_documentId, product_documentId, quantity=1.0):
    """Добавляет товар в корзину."""
    item_data = {
        "data": {
            "cart": cart_documentId,
            "product": product_documentId,
            "quantity": float(quantity)
        }
    }
    try:
        response = session.post(f"{api_url}/api/cart-products", json=item_data)
        response.raise_for_status()
        return response.json()['data']
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка добавления в корзину: {e}")
        return None


def remove_from_cart(session, api_url, document_id, telegram_id):
    """Удаляет товар из корзины."""
    try:
        response = session.delete(f"{api_url}/api/cart-products/{document_id}")
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка удаления из корзины: {e}")
        return False


# def clear_cart(session, api_url, cart_documentId, telegram_id):
#     """Очищает корзину."""
#     items = get_cart_items(session, api_url, cart_documentId)
#     for item in items:
#         remove_from_cart(session, api_url, item['documentId'], telegram_id)


def fetch_products(session, api_url):
    """Возвращает список товаров из CMS."""
    try:
        response = session.get(f"{api_url}/api/products", params={"populate": "*"})
        response.raise_for_status()
        return response.json().get('data', [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка получения товаров: {e}")
        return []


def build_main_menu(session, api_url):
    """Формирует клавиатуру главного меню."""
    products = fetch_products(session, api_url)
    if not products:
        return None

    keyboard = []
    for product in products:
        title = product.get('name', 'Без названия')[:30]
        callback_data = f"product_{product['documentId']}"
        keyboard.append([InlineKeyboardButton(title, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🛒 Корзина", callback_data="cart")])
    return InlineKeyboardMarkup(keyboard)


def get_product_details(session, api_url, document_id):
    """Возвращает детали товара по его ID."""
    try:
        params = {"filters[documentId][$eq]": document_id, "populate": "*"}
        response = session.get(f"{api_url}/api/products", params=params)
        response.raise_for_status()
        data = response.json()
        return data['data'][0] if data.get('data') else None
    except (requests.exceptions.RequestException, IndexError) as e:
        logging.error(f"Ошибка получения товара: {e}")
        return None


def safe_edit_message(query, context, text, reply_markup=None, parse_mode=None):
    """Безопасно редактирует сообщение или отправляет новое."""
    try:
        query.edit_message_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "message to edit not found" in str(e).lower():
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )


def show_cart(context, chat_id, message_id=None):
    """Отображает содержимое корзины."""
    session = context.bot_data['strapi_session']
    api_url = context.bot_data['api_url']
    
    cart = get_or_create_cart(session, api_url, chat_id)
    if not cart:
        context.bot.send_message(chat_id, "Ошибка загрузки корзины")
        return
        
    items = get_cart_items(session, api_url, cart.get('documentId', ''))
    
    if not items:
        text = "🛒 Ваша корзина пуста"
        keyboard = [[InlineKeyboardButton("🔙 Назад к товарам", callback_data="back_to_menu")]]
    else:
        grouped_items = {}
        for item in items:
            product = item.get('product', {}) or {}
            pid = str(product.get('documentId', ''))
            
            if pid not in grouped_items:
                grouped_items[pid] = {
                    'name': product.get('name', 'Без названия'),
                    'price': product.get('price', 0),
                    'total_quantity': 0,
                    'total_price': 0,
                }
            
            quantity = item.get('quantity', 0)
            grouped_items[pid]['total_quantity'] += quantity
            grouped_items[pid]['total_price'] += quantity * grouped_items[pid]['price']

        text = "🛒 Ваша корзина:\n\n"
        total = 0
        keyboard = []
        
        for pid, group in grouped_items.items():
            total += group['total_price']
            text += f"▪️ {group['name']}\n   {group['total_quantity']} кг × {group['price']} ₽ = {group['total_price']:.2f} ₽\n"
            keyboard.append([
                InlineKeyboardButton(f"❌ Удалить {group['name']}", callback_data=f"remove_{item['documentId']}")
            ])
        
        text += f"\n💵 Итого: {total:.2f} ₽"
        keyboard.append([InlineKeyboardButton("💳 Оплатить", callback_data="checkout")])
        keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if message_id:
        try:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception:
            context.bot.send_message(chat_id, text, reply_markup=reply_markup)
    else:
        context.bot.send_message(chat_id, text, reply_markup=reply_markup)


def start(update: Update, context: CallbackContext):
    """Обработчик команды /start."""
    session = context.bot_data['strapi_session']
    api_url = context.bot_data['api_url']
    
    reply_markup = build_main_menu(session, api_url)
    if not reply_markup:
        context.bot.send_message(update.effective_chat.id, "Товары временно недоступны")
        return HANDLE_MENU
    
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Выберите товар:",
        reply_markup=reply_markup
    )
    return HANDLE_MENU


def handle_menu(update: Update, context: CallbackContext):
    """Обрабатывает взаимодействия в главном меню."""
    query = update.callback_query
    query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id
    
    session = context.bot_data['strapi_session']
    api_url = context.bot_data['api_url']
    
    if callback_data.startswith("product_"):
        document_id = callback_data.split("_", 1)[1]
        product = get_product_details(session, api_url, document_id)
        
        if not product:
            context.bot.send_message(chat_id, "Товар не найден")
            return HANDLE_MENU

        title = product.get('name', 'Без названия')
        price = product.get('price', 0)
        description = product.get('description', 'Описание отсутствует')
        caption = f"<b>{title}</b>\n\n💵 Цена: {price} руб.\n\n{description}"
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить в корзину", callback_data=f"add_{document_id}")],
            [InlineKeyboardButton("🔙 Назад к товарам", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        image_url = None
        image_data = product.get('image')
        if isinstance(image_data, list) and image_data:
            image_url = f"{api_url}{image_data[0]['url']}"
        elif isinstance(image_data, dict) and image_data.get('url'):
            image_url = f"{api_url}{image_data['url']}"

        try:
            context.bot.delete_message(chat_id, query.message.message_id)
        except Exception:
            pass

        if image_url:
            try:
                image_bytes = BytesIO(requests.get(image_url).content)
                context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_bytes,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
        else:
            context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
    
    elif callback_data.startswith("add_"):
        product_id = callback_data.split("_", 1)[1]
        cart = get_or_create_cart(session, api_url, chat_id)
        if cart and cart.get('documentId'):
            add_to_cart(session, api_url, cart['documentId'], product_id)
            query.answer("✅ Товар добавлен в корзину!")
        else:
            query.answer("❌ Ошибка добавления")
    
    elif callback_data == "cart":
        show_cart(context, chat_id)
        return HANDLE_CART
    
    elif callback_data.startswith("remove_"):
        item_id = callback_data.split("_", 1)[1]
        if remove_from_cart(session, api_url, item_id, str(chat_id)):
            query.answer("✅ Товар удален из корзины")
        else:
            query.answer("❌ Ошибка удаления")
        show_cart(context, chat_id, query.message.message_id)
    
    elif callback_data == "checkout":
        cart = get_or_create_cart(session, api_url, chat_id)
        if cart and cart.get('documentId'):
            remove_from_cart(session, api_url, cart['documentId'], str(chat_id))
            context.bot.send_message(
                chat_id=chat_id,
                text="✅ Заказ оформлен! Спасибо за покупку!\nСкоро с вами свяжется менеджер."
            )
            return start(update, context)
    
    elif callback_data == "back_to_menu":
        reply_markup = build_main_menu(session, api_url)
        if not reply_markup:
            context.bot.send_message(chat_id, "Товары временно недоступны")
            return HANDLE_MENU
        
        try:
            context.bot.delete_message(chat_id, query.message.message_id)
        except Exception:
            pass
            
        context.bot.send_message(
            chat_id=chat_id,
            text="Выберите товар:",
            reply_markup=reply_markup
        )
    
    return HANDLE_MENU


def handle_cart(update: Update, context: CallbackContext):
    """Обрабатывает взаимодействия в корзине."""
    query = update.callback_query
    query.answer()
    callback_data = query.data
    chat_id = query.message.chat_id
    
    session = context.bot_data['strapi_session']
    api_url = context.bot_data['api_url']
    
    if callback_data.startswith("remove_"):
        item_id = callback_data.split("_", 1)[1]
        if remove_from_cart(session, api_url, item_id, str(chat_id)):
            query.answer("✅ Товар удален из корзины")
        else:
            query.answer("❌ Ошибка удаления")
        show_cart(context, chat_id, query.message.message_id)
        return HANDLE_CART
    
    elif callback_data == "checkout":
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_email")]]
        safe_edit_message(
            query,
            context,
            "📧 Введите ваш email для оформления заказа:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_EMAIL
    
    elif callback_data == "back_to_menu":
        reply_markup = build_main_menu(session, api_url)
        if not reply_markup:
            context.bot.send_message(chat_id, "Товары временно недоступны")
            return HANDLE_MENU
        
        try:
            context.bot.delete_message(chat_id, query.message.message_id)
        except Exception:
            pass
            
        context.bot.send_message(
            chat_id=chat_id,
            text="Выберите товар:",
            reply_markup=reply_markup
        )
        return HANDLE_MENU
    
    return HANDLE_CART


def save_client_to_cms(session, api_url, email, telegram_id, name=None):
    """Сохраняет клиента в CMS."""
    try:
        response = session.get(
            f"{api_url}/api/clients",
            params={"filters[telegram_id][$eq]": str(telegram_id)}
        )
        response.raise_for_status()
        existing_clients = response.json().get('data', [])
        
        client_data = {"email": email, "telegram_id": str(telegram_id)}
        if name:
            client_data["Name"] = name
        
        if existing_clients:
            client_id = existing_clients[0]['id']
            response = session.put(
                f"{api_url}/api/clients/{client_id}",
                json={"data": client_data}
            )
        else:
            response = session.post(
                f"{api_url}/api/clients",
                json={"data": client_data}
            )
        
        response.raise_for_status()
        return response.json().get('data', {})
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка сохранения клиента: {e}")
        return None


def handle_email(update, context):
    """Обрабатывает ввод email."""
    if update.message:
        email = update.message.text.strip()
        chat_id = update.message.chat_id
        
        if not re.match(r'[\w\.-]+@[\w\.-]+\.\w+', email):
            update.message.reply_text('⚠️ Введите корректный email')
            return WAITING_EMAIL
        
        session = context.bot_data['strapi_session']
        api_url = context.bot_data['api_url']
        user = update.message.from_user
        name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
        
        if save_client_to_cms(session, api_url, email, chat_id, name):
            cart = get_or_create_cart(session, api_url, chat_id)
            if cart and cart.get('documentId'):
                remove_from_cart(session, api_url, cart['documentId'], str(chat_id))
            
            update.message.reply_text(
                '✅ Спасибо за заказ!\n'
                f'Ваш email ({email}) сохранен.\n'
                'Менеджер свяжется с вами для оформления оплаты.'
            )
        else:
            update.message.reply_text(
                '⚠️ Не удалось сохранить ваши данные.\n'
                'Попробуйте позже или свяжитесь с нами.'
            )
        
        return start(update, context)
    
    elif update.callback_query:
        query = update.callback_query
        query.answer()
        if query.data == "cancel_email":
            context.bot.send_message(query.message.chat_id, "❌ Ввод email отменен.")
            return start(update, context)
    
    return WAITING_EMAIL


def error_handler(update, context):
    """Обрабатывает ошибки в боте."""
    logging.error(f'Ошибка в боте: {context.error}')
    if update and update.effective_chat:
        context.bot.send_message(update.effective_chat.id, "⚠️ Произошла ошибка. Попробуйте позже.")
    return start(update, context)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    load_dotenv()
    TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
    STRAPI_URL = os.environ['STRAPI_URL']
    STRAPI_TOKEN = os.environ['STRAPI_TOKEN']
    
    if not TELEGRAM_TOKEN or not STRAPI_TOKEN:
        logging.error("Не заданы обязательные переменные окружения!")
        exit(1)
    
    updater = Updater(token=TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    strapi_session = init_strapi_session(api_url=STRAPI_URL, token=STRAPI_TOKEN)
    dispatcher.bot_data['strapi_session'] = strapi_session
    dispatcher.bot_data['api_url'] = STRAPI_URL

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            HANDLE_MENU: [CallbackQueryHandler(handle_menu)],
            HANDLE_CART: [CallbackQueryHandler(handle_cart)],
            WAITING_EMAIL: [
                MessageHandler(Filters.text & ~Filters.command, handle_email),
                CallbackQueryHandler(handle_email)
            ],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    dispatcher.add_handler(conv_handler)
    dispatcher.add_error_handler(error_handler)
    
    updater.start_polling()
    logging.info("Бот запущен")
    updater.idle()