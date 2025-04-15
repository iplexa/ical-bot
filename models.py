# // Этот файл содержит определения моделей для базы данных, такие как пользователь и календарь.
# // Подключаем необходимые библиотеки для работы с базой данных и переменными окружения.
# // Создаем движок SQLAlchemy для подключения к базе данных.
# // Создаем базовый класс для всех моделей базы данных.
# // Создаем сессию для взаимодействия с базой данных.
# // Модель пользователя, которая хранит информацию о пользователе Telegram.
# // Модель календаря, которая хранит информацию о календаре, используемом ботом.
# // Функция для получения сессии базы данных, которая используется для выполнения операций с базой данных.
# // Функция для инициализации базы данных, которая создает все таблицы, если они еще не существуют.
from sqlalchemy import Column, Integer, String, Boolean, create_engine, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Получение строки подключения к базе данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/telegram_bot")

# Создание движка SQLAlchemy
engine = create_engine(DATABASE_URL)

# Создание базового класса для моделей
Base = declarative_base()

# Создание сессии
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_owner = Column(Boolean, default=False)
    is_subscribed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class Calendar(Base):
    """Модель календаря (общий для всех пользователей)"""
    __tablename__ = "calendars"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    updated_by = Column(Integer, nullable=True)  # user_id пользователя, который обновил календарь


# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Функция для инициализации базы данных
def init_db():
    Base.metadata.create_all(bind=engine)