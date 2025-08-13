# 🐟 Telegram-бот магазина рыбы

Бот для интернет-магазина рыбы с интеграцией **Strapi CMS**.

## 📌 Возможности

- Просмотр каталога рыбы с фотографиями и описаниями
- Добавление товаров в корзину с выбором количества (в кг)
- Управление корзиной (просмотр, удаление товаров)
- Оформление заказа с подтверждением по email
- История заказов в Strapi


## ⚙️ Установка

### Требования

1. Установленный `Python 3.10`
2. Настроенный `Strapi CMS v5`
3. Токен Telegram-бота от [BotFather](https://telegram.me/BotFather)

### Настройка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/Romigo24/fish_store.git
```
2. Создайте и активируйте виртуальное окружение:

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```
3. Установите зависимости:

```bash
pip install -r requirements.txt
```
4. Создайте файл `.env`:

```env
TELEGRAM_TOKEN=ваш_токен_бота
STRAPI_URL=https://ваш-strapi-сервер.com
STRAPI_TOKEN=ваш_api_ключ_strapi
```
5. Настройте коллекции в Strapi (см. раздел "Конфигурация Strapi")


6. Запустите бота:
```bash
python tg_bot.py
```


## 🚀 Быстрый старт Strapi

1. Установите Strapi:
```bash
npx create-strapi-app@latest fish --quickstart
````
После установки перейдите в папку проекта и запустите:

```bash
cd "путь к репозиторию fish"
npm run develop
````
Создайте администратора:

- Откройте http://localhost:1337/admin

- Заполните форму регистрации

Создайте коллекции (Settings → Content-Type Builder):

- Товары (Product)

- Корзины (Cart)

- Товары в корзине (CartProduct)

Настройте права доступа (Settings → Users & Permissions Plugin):

- Для роли "Public" разрешите доступ к необходимым API

Получите API-токен:

- Settings → API Tokens → Create new token

- Выберите тип "Full Access" (для тестов) или настройте права вручную

## Конфигурация Strapi
Убедитесь, что в Strapi существуют следующие коллекции:

### Коллекция `Product`
```json
{
  "collectionName": "products",
  "attributes": {
    "name": {"type": "string", "required": true},
    "description": {"type": "text"},
    "price": {"type": "decimal", "required": true},
    "image": {"type": "media"},
    "cart_products": {"type": "relation", "relation": "oneToMany", "target": "api::cart-product.cart-product"}
  }
}
```
### Коллекция `Cart`
```json
{
  "collectionName": "carts",
  "attributes": {
    "telegram_id": {"type": "string"},
    "cart_products": {"type": "relation", "relation": "oneToMany", "target": "api::cart-product.cart-product"}
  }
}
```
### Коллекция `CartProduct`
```json
{
  "collectionName": "cart-products",
  "attributes": {
    "quantity": {"type": "float"},
    "product": {"type": "relation", "relation": "manyToOne", "target": "api::product.product"},
    "cart": {"type": "relation", "relation": "manyToOne", "target": "api::cart.cart"}
  }
}
```


Можно создать и настроить все коллекции вручную через административную панель Strapi http://localhost:1337/admin.
