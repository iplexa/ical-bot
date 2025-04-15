import asyncio
import logging
import datetime
from typing import Dict, List, Optional, Union, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dateutil import tz
from sqlalchemy.orm import Session

# Подключаем настройки бота и вспомогательные функции для работы с календарями - это как инструкция для нашего бота
from config import BOT_TOKEN, CHECK_INTERVAL, NOTIFICATION_TIME, OWNER_ID
from calendar_utils import fetch_calendar, get_events, format_events_text
from models import User, Calendar, init_db, SessionLocal
from db_utils import get_or_create_user, update_user_subscription, set_user_admin, get_all_subscribed_users, get_calendar, create_or_update_calendar

# Настраиваем систему записи событий (логирование), чтобы видеть что происходит с ботом
logging.basicConfig(level=logging.INFO)

# Создаем главные объекты бота и его "мозга" (диспетчера), которые будут управлять всем
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Настраиваем постоянную фоновую задачу, которая будет проверять события в календаре
async def on_startup():
    # Запускаем задачу проверки событий
    task = asyncio.create_task(check_upcoming_events())
    # Добавляем обработку ошибок
    task.add_done_callback(lambda t: logging.error(f"Ошибка в задаче проверки событий: {t.exception()}") if t.exception() else None)

# Разделяем обработчики команд на группы для удобства - как отдельные отделы в компании
main_router = Router()
admin_router = Router()

# Говорим боту, что делать при запуске - как инструкция при первом включении устройства
dp.startup.register(on_startup)

# Подготавливаем базу данных - создаем "хранилище" для информации о пользователях и календарях
init_db()

# Создаем "состояния" для бота - как этапы в анкете, которые нужно последовательно заполнить
class CalendarStates(StatesGroup):
    waiting_for_calendar_url = State()

class AdminStates(StatesGroup):
    waiting_for_admin_id = State()

# Создаем кнопочное меню для бота - как пульт управления с разными функциями
def get_main_keyboard(user: User = None, has_calendar: bool = False) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    
    if has_calendar:
        # Кнопки для просмотра событий
        builder.button(text="События на сегодня", callback_data="events_1")
        builder.button(text="События на 3 дня", callback_data="events_3")
        builder.button(text="События на неделю", callback_data="events_7")
        
        # Кнопка подписки/отписки
        is_subscribed = user.is_subscribed if user else False
        sub_text = "Отключить уведомления" if is_subscribed else "Включить уведомления"
        sub_data = "unsubscribe" if is_subscribed else "subscribe"
        builder.button(text=sub_text, callback_data=sub_data)
        
        # Кнопки для администраторов и владельца
        if user and (user.is_admin or user.is_owner):
            builder.button(text="Изменить календарь", callback_data="change_calendar")
            
            # Кнопка для владельца (управление администраторами)
            if user.is_owner:
                builder.button(text="Управление администраторами", callback_data="manage_admins")
    else:
        # Кнопка для добавления календаря (только для админов и владельца)
        if user and (user.is_admin or user.is_owner):
            builder.button(text="Добавить календарь", callback_data="add_calendar")
        else:
            builder.button(text="Запросить доступ к календарю", callback_data="request_calendar")
    
    # Устанавливаем ширину ряда для клавиатуры
    builder.adjust(1)
    return builder

# Что делает бот, когда пользователь нажимает /start - первое знакомство
@main_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    # Получаем или создаем пользователя в базе данных
    db = SessionLocal()
    try:
        user = get_or_create_user(
            db, 
            user_id, 
            message.from_user.username, 
            message.from_user.first_name, 
            message.from_user.last_name
        )
        
        # Проверяем, есть ли календарь в базе данных
        calendar = get_calendar(db)
        has_calendar = calendar is not None
        
        text = "Привет! Я бот для работы с календарями в формате iCal.\n\n"
        
        if has_calendar:
            text += "Календарь уже добавлен. Выберите действие:"
        else:
            if user.is_admin or user.is_owner:
                text += "Для начала работы добавьте ссылку на iCal календарь."
            else:
                text += "Ожидайте, когда администратор добавит календарь."
        
        await message.answer(
            text,
            reply_markup=get_main_keyboard(user, has_calendar).as_markup()
        )
    finally:
        db.close()

# Как бот обрабатывает запрос на добавление нового календаря - шаг за шагом
@main_router.callback_query(F.data.in_(["add_calendar", "change_calendar"]))
async def process_add_calendar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем права доступа
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        if not user.is_admin and not user.is_owner:
            await callback.message.edit_text(
                "У вас нет прав для изменения календаря.",
                reply_markup=get_main_keyboard(user, get_calendar(db) is not None).as_markup()
            )
            return
        
        text = "Пожалуйста, отправьте ссылку на iCal календарь."
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="cancel")
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup()
        )
        
        await state.set_state(CalendarStates.waiting_for_calendar_url)
    finally:
        db.close()

# Что происходит, когда пользователь отменяет текущее действие - кнопка "Назад"
@main_router.callback_query(F.data == "cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    
    user_id = callback.from_user.id
    
    # Получаем данные пользователя из БД
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        calendar = get_calendar(db)
        
        text = "Операция отменена. Выберите действие:"
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(user, calendar is not None).as_markup()
        )
    finally:
        db.close()

# Как бот проверяет и сохраняет ссылку на календарь - важный этап настройки
@main_router.message(StateFilter(CalendarStates.waiting_for_calendar_url))
async def process_calendar_url(message: Message, state: FSMContext):
    url = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем URL
    if not url.startswith(("http://", "https://")):
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="cancel")
        
        await message.answer(
            "Пожалуйста, отправьте корректную ссылку на календарь, начинающуюся с http:// или https://",
            reply_markup=builder.as_markup()
        )
        return
    
    # Пробуем загрузить календарь
    calendar = await fetch_calendar(url)
    if not calendar:
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="cancel")
        
        await message.answer(
            "Не удалось загрузить календарь по указанной ссылке. Пожалуйста, проверьте ссылку и попробуйте снова.",
            reply_markup=builder.as_markup()
        )
        return
    
    # Сохраняем URL календаря в базу данных
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, message.from_user.username,
                                message.from_user.first_name, message.from_user.last_name)
        
        # Создаем или обновляем календарь
        create_or_update_calendar(db, url, user_id)
        
        await state.clear()
        
        # Отправляем сообщение с подтверждением
        sent_message = await message.answer(
            "Календарь успешно добавлен! Выберите действие:",
            reply_markup=get_main_keyboard(user, True).as_markup()
        )
        
        # Удаляем сообщение с URL для безопасности
        await message.delete()
    finally:
        db.close()

# Показываем события из календаря - главная функция бота
@main_router.callback_query(F.data.startswith("events_"))
async def process_show_events(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Получаем данные из базы данных
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        # Проверяем, есть ли календарь
        calendar_obj = get_calendar(db)
        if not calendar_obj:
            await callback.message.edit_text(
                "Сначала добавьте календарь.",
                reply_markup=get_main_keyboard(user, False).as_markup()
            )
            return
        
        # Определяем период
        days = int(callback.data.split("_")[1])
        start_date = datetime.datetime.now(tz.tzlocal())
        end_date = start_date + datetime.timedelta(days=days)
        
        # Загружаем календарь
        calendar = await fetch_calendar(calendar_obj.url)
        if not calendar:
            await callback.message.edit_text(
                "Не удалось загрузить календарь. Пожалуйста, проверьте ссылку и попробуйте снова.",
                reply_markup=get_main_keyboard(user, True).as_markup()
            )
            return
    finally:
        db.close()
    
    # Получаем события
    events = get_events(calendar, start_date, end_date)
    
    # Формируем текст с событиями
    period_text = "сегодня" if days == 1 else f"на {days} {'дня' if days == 3 else 'дней'}"
    text = f"События {period_text}:\n\n"
    text += format_events_text(events)
    
    # Добавляем кнопку возврата
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="back_to_main")
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            # Если сообщение не изменилось, игнорируем ошибку
            pass
        elif "query is too old" in str(e).lower() or "response timeout expired" in str(e).lower():
            # Игнорируем устаревшие callback-запросы
            pass
        else:
            raise

# Возвращаем пользователя в основное меню - как кнопка "Домой" в приложении
@main_router.callback_query(F.data == "back_to_main")
async def process_back_to_main(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Получаем данные из базы данных
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        calendar = get_calendar(db)
        has_calendar = calendar is not None
        
        text = "Выберите действие:"
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(user, has_calendar).as_markup()
        )
    finally:
        db.close()

# Включаем и выключаем уведомления - как подписка на рассылку
@main_router.callback_query(F.data == "subscribe")
async def process_subscribe(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Обновляем статус подписки в базе данных
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        # Проверяем, есть ли календарь
        calendar = get_calendar(db)
        if not calendar:
            await callback.message.edit_text(
                "Сначала добавьте календарь.",
                reply_markup=get_main_keyboard(user, False).as_markup()
            )
            return
        
        # Обновляем статус подписки
        update_user_subscription(db, user_id, True)
        user.is_subscribed = True  # Обновляем локальный объект пользователя
        
        await callback.message.edit_text(
            "Уведомления о событиях включены! Вы будете получать сообщения о начале мероприятий.",
            reply_markup=get_main_keyboard(user, True).as_markup()
        )
    finally:
        db.close()

@main_router.callback_query(F.data == "unsubscribe")
async def process_unsubscribe(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Обновляем статус подписки в базе данных
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        # Обновляем статус подписки
        update_user_subscription(db, user_id, False)
        user.is_subscribed = False  # Обновляем локальный объект пользователя
        
        await callback.message.edit_text(
            "Уведомления о событиях отключены.",
            reply_markup=get_main_keyboard(user, True).as_markup()
        )
    finally:
        db.close()

# Специальные функции для владельца бота - как панель администратора
@admin_router.callback_query(F.data == "manage_admins")
async def process_manage_admins(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь владельцем
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        if not user.is_owner:
            await callback.message.edit_text(
                "У вас нет прав для управления администраторами.",
                reply_markup=get_main_keyboard(user, get_calendar(db) is not None).as_markup()
            )
            return
        
        # Создаем клавиатуру для управления администраторами
        builder = InlineKeyboardBuilder()
        builder.button(text="Добавить администратора", callback_data="add_admin")
        builder.button(text="Удалить администратора", callback_data="remove_admin")
        builder.button(text="Назад", callback_data="back_to_main")
        builder.adjust(1)
        
        await callback.message.edit_text(
            "Управление администраторами:",
            reply_markup=builder.as_markup()
        )
    finally:
        db.close()

# Обработчик для добавления администратора
@admin_router.callback_query(F.data == "add_admin")
async def process_add_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь владельцем
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        if not user.is_owner:
            await callback.message.edit_text(
                "У вас нет прав для управления администраторами.",
                reply_markup=get_main_keyboard(user, get_calendar(db) is not None).as_markup()
            )
            return
        
        # Запрашиваем ID нового администратора
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="cancel")
        
        await callback.message.edit_text(
            "Пожалуйста, отправьте ID пользователя, которого хотите сделать администратором.",
            reply_markup=builder.as_markup()
        )
        
        # Устанавливаем состояние ожидания ID администратора
        await state.set_state(AdminStates.waiting_for_admin_id)
    finally:
        db.close()

# Обработчик для получения ID нового администратора
@admin_router.message(StateFilter(AdminStates.waiting_for_admin_id))
async def process_admin_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь владельцем
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, message.from_user.username,
                                message.from_user.first_name, message.from_user.last_name)
        
        if not user.is_owner:
            await message.answer(
                "У вас нет прав для управления администраторами.",
                reply_markup=get_main_keyboard(user, get_calendar(db) is not None).as_markup()
            )
            await state.clear()
            return
        
        # Проверяем корректность введенного ID
        try:
            admin_id = int(message.text.strip())
        except ValueError:
            builder = InlineKeyboardBuilder()
            builder.button(text="Отмена", callback_data="cancel")
            
            await message.answer(
                "Пожалуйста, введите корректный ID пользователя (целое число).",
                reply_markup=builder.as_markup()
            )
            return
        
        # Проверяем, существует ли пользователь с таким ID
        admin_user = get_or_create_user(db, admin_id)
        if not admin_user:
            # Если пользователя нет в базе, создаем его
            admin_user = create_user(db, admin_id)
        
        # Назначаем пользователя администратором
        set_user_admin(db, admin_id, True)
        
        await state.clear()
        
        # Отправляем сообщение об успешном назначении
        builder = InlineKeyboardBuilder()
        builder.button(text="Назад к управлению", callback_data="manage_admins")
        
        await message.answer(
            f"Пользователь с ID {admin_id} успешно назначен администратором.",
            reply_markup=builder.as_markup()
        )
    finally:
        db.close()

# Обработчик для удаления администратора
@admin_router.callback_query(F.data == "remove_admin")
async def process_remove_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь владельцем
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        if not user.is_owner:
            await callback.message.edit_text(
                "У вас нет прав для управления администраторами.",
                reply_markup=get_main_keyboard(user, get_calendar(db) is not None).as_markup()
            )
            return
        
        # Запрашиваем ID администратора для удаления
        builder = InlineKeyboardBuilder()
        builder.button(text="Отмена", callback_data="cancel")
        
        await callback.message.edit_text(
            "Пожалуйста, отправьте ID пользователя, у которого хотите убрать права администратора.",
            reply_markup=builder.as_markup()
        )
        
        # Устанавливаем состояние ожидания ID администратора
        await state.set_state(AdminStates.waiting_for_admin_id)
        
        # Сохраняем информацию о том, что это удаление администратора
        await state.update_data(action="remove_admin")
    finally:
        db.close()

# Обработчик для запроса доступа к календарю
@main_router.callback_query(F.data == "request_calendar")
async def process_request_calendar(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Получаем данные пользователя
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        # Отправляем сообщение владельцу бота
        owner_id = OWNER_ID
        if owner_id:
            username = callback.from_user.username or "без имени пользователя"
            full_name = f"{callback.from_user.first_name or ''} {callback.from_user.last_name or ''}".strip() or "без имени"
            
            builder = InlineKeyboardBuilder()
            builder.button(text="Сделать администратором", callback_data=f"make_admin_{user_id}")
            
            await bot.send_message(
                owner_id,
                f"Пользователь @{username} ({full_name}, ID: {user_id}) запрашивает доступ к календарю.",
                reply_markup=builder.as_markup()
            )
            
            # Отправляем сообщение пользователю
            builder = InlineKeyboardBuilder()
            builder.button(text="Назад", callback_data="back_to_main")
            
            await callback.message.edit_text(
                "Запрос на доступ к календарю отправлен владельцу бота. Ожидайте ответа.",
                reply_markup=builder.as_markup()
            )
        else:
            builder = InlineKeyboardBuilder()
            builder.button(text="Назад", callback_data="back_to_main")
            
            await callback.message.edit_text(
                "Не удалось отправить запрос. Пожалуйста, свяжитесь с администратором бота напрямую.",
                reply_markup=builder.as_markup()
            )
    finally:
        db.close()

# Обработчик для назначения администратора из запроса
@admin_router.callback_query(F.data.startswith("make_admin_"))
async def process_make_admin_from_request(callback: CallbackQuery):
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь владельцем
    db = SessionLocal()
    try:
        user = get_or_create_user(db, user_id, callback.from_user.username,
                                callback.from_user.first_name, callback.from_user.last_name)
        
        if not user.is_owner:
            await callback.message.edit_text(
                "У вас нет прав для назначения администраторов."
            )
            return
        
        # Получаем ID пользователя для назначения администратором
        admin_id = int(callback.data.split("_")[2])
        
        # Назначаем пользователя администратором
        admin_user = get_or_create_user(db, admin_id)
        set_user_admin(db, admin_id, True)
        
        # Отправляем сообщение владельцу
        await callback.message.edit_text(
            f"Пользователь с ID {admin_id} успешно назначен администратором."
        )
        
        # Отправляем сообщение новому администратору
        await bot.send_message(
            admin_id,
            "Вам предоставлены права администратора. Теперь вы можете управлять календарем.",
            reply_markup=get_main_keyboard(admin_user, get_calendar(db) is not None).as_markup()
        )
    finally:
        db.close()

# Глобальный словарь для отслеживания отправленных уведомлений
notified_events = {}

# Функция для проверки предстоящих событий и отправки уведомлений
async def check_upcoming_events():
    while True:
        now = datetime.datetime.now(tz.tzlocal())
        
        # Получаем всех подписанных пользователей и календарь из базы данных
        db = SessionLocal()
        try:
            # Получаем календарь
            calendar_obj = get_calendar(db)
            if not calendar_obj:
                logging.warning("Календарь не найден в базе данных")
                notified_events.clear()
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            
            # Загружаем календарь
            calendar = await fetch_calendar(calendar_obj.url)
            if not calendar:
                logging.error(f"Не удалось загрузить календарь по URL: {calendar_obj.url}")
                notified_events.clear()
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            
            # Получаем всех подписанных пользователей
            subscribed_users = get_all_subscribed_users(db)
            
            # Получаем события на ближайший час
            end_time = now + datetime.timedelta(hours=1)
            events = get_events(calendar, now, end_time)
            
            # Отправляем уведомления подписанным пользователям
            for user in subscribed_users:
                user_id = user.user_id
                
                if user_id not in notified_events:
                    notified_events[user_id] = set()
                
                for event in events:
                    event_start = event['start']
                    time_diff = (event_start - now).total_seconds() / 60
                    
                    event_id = f"{event['summary']}_{event_start.isoformat()}"
                    if 0 <= time_diff <= NOTIFICATION_TIME and event_id not in notified_events[user_id]:
                        text = f"🔔 Скоро начнется событие!\n\n"
                        text += f"🕒 {event_start.strftime('%d.%m.%Y %H:%M')}\n"
                        text += f"📌 {event['summary']}\n"
                        
                        if event['location'] != 'Без места':
                            text += f"📍 {event['location']}\n"
                        
                        if event['description'] != 'Без описания':
                            text += f"ℹ️ {event['description']}\n"
                        
                        try:
                            await bot.send_message(user_id, text)
                            notified_events[user_id].add(event_id)
                        except Exception as e:
                            logging.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
                            await asyncio.sleep(1)
            
            # Очищаем старые уведомления (старше 24 часов)
            for user_id in notified_events:
                notified_events[user_id] = {event_id for event_id in notified_events[user_id] 
                                          if not event_id.split('_')[1].startswith((now - datetime.timedelta(days=1)).isoformat()[:10])}
        
        except Exception as e:
            logging.error(f"Ошибка при проверке событий: {e}", exc_info=True)
        finally:
            db.close()
        await asyncio.sleep(CHECK_INTERVAL)

# Регистрируем роутеры в диспетчере
dp.include_router(main_router)
dp.include_router(admin_router)

# Запуск бота
async def main():
    # Запускаем задачу проверки событий
    asyncio.create_task(check_upcoming_events())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())