from sqlalchemy.orm import Session
from models import User, Calendar, init_db
from typing import Optional, List
from config import OWNER_ID


def get_user(db: Session, user_id: int) -> Optional[User]:
    """Получение пользователя по его Telegram ID"""
    return db.query(User).filter(User.user_id == user_id).first()


def create_user(db: Session, user_id: int, username: Optional[str] = None,
               first_name: Optional[str] = None, last_name: Optional[str] = None) -> User:
    """Создание нового пользователя"""
    # Проверяем, является ли пользователь владельцем
    is_owner = user_id == OWNER_ID
    
    # Создаем объект пользователя
    db_user = User(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        is_owner=is_owner,
        is_admin=is_owner,  # Владелец автоматически становится админом
        is_subscribed=False
    )
    
    # Добавляем пользователя в базу данных
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user


def get_or_create_user(db: Session, user_id: int, username: Optional[str] = None,
                      first_name: Optional[str] = None, last_name: Optional[str] = None) -> User:
    """Получение существующего пользователя или создание нового"""
    user = get_user(db, user_id)
    if not user:
        user = create_user(db, user_id, username, first_name, last_name)
    return user


def update_user_subscription(db: Session, user_id: int, is_subscribed: bool) -> Optional[User]:
    """Обновление статуса подписки пользователя"""
    user = get_user(db, user_id)
    if user:
        user.is_subscribed = is_subscribed
        db.commit()
        db.refresh(user)
    return user


def set_user_admin(db: Session, user_id: int, is_admin: bool) -> Optional[User]:
    """Установка или снятие статуса администратора для пользователя"""
    user = get_user(db, user_id)
    if user:
        user.is_admin = is_admin
        db.commit()
        db.refresh(user)
    return user


def get_all_subscribed_users(db: Session) -> List[User]:
    """Получение всех пользователей с активной подпиской"""
    return db.query(User).filter(User.is_subscribed == True).all()


def get_calendar(db: Session) -> Optional[Calendar]:
    """Получение текущего календаря"""
    return db.query(Calendar).first()


def create_or_update_calendar(db: Session, url: str, updated_by: int) -> Calendar:
    """Создание или обновление календаря"""
    calendar = get_calendar(db)
    
    if calendar:
        calendar.url = url
        calendar.updated_by = updated_by
    else:
        calendar = Calendar(url=url, updated_by=updated_by)
        db.add(calendar)
    
    db.commit()
    db.refresh(calendar)
    
    return calendar