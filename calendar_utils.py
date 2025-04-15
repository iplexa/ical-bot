import logging
import datetime
from typing import Dict, List, Optional

import icalendar
import recurring_ical_events
import aiohttp
from dateutil import tz

# Эта функция загружает календарь в формате iCal из указанного URL и возвращает его.
async def fetch_calendar(url: str) -> Optional[icalendar.Calendar]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    ical_data = await response.text()
                    return icalendar.Calendar.from_ical(ical_data)
                else:
                    logging.error(f"Ошибка при загрузке календаря: {response.status}")
                    return None
    except Exception as e:
        logging.error(f"Ошибка при загрузке календаря: {e}")
        return None

# Эта функция извлекает события из календаря за указанный период времени.
def get_events(calendar: icalendar.Calendar, start_date: datetime.datetime, end_date: datetime.datetime) -> List[Dict]:
    if not calendar:
        return []
    
    # Получаем события с учетом повторяющихся событий
    events = recurring_ical_events.of(calendar).between(start_date, end_date)
    
    formatted_events = []
    for event in events:
        start = event.get('dtstart').dt
        # Преобразуем дату в datetime, если это date
        if isinstance(start, datetime.date) and not isinstance(start, datetime.datetime):
            start = datetime.datetime.combine(start, datetime.time.min)
        
        # Преобразуем в локальное время, если есть информация о временной зоне
        if isinstance(start, datetime.datetime) and start.tzinfo is None:
            start = start.replace(tzinfo=tz.tzutc())
            start = start.astimezone(tz.tzlocal())
        
        summary = str(event.get('summary', 'Без названия'))
        description = str(event.get('description', 'Без описания'))
        location = str(event.get('location', 'Без места'))
        
        formatted_events.append({
            'start': start,
            'summary': summary,
            'description': description,
            'location': location
        })
    
    # Сортируем события по времени начала
    return sorted(formatted_events, key=lambda x: x['start'])

# Эта функция форматирует список событий в текст для отображения пользователю.
def format_events_text(events: List[Dict]) -> str:
    if not events:
        return "Нет предстоящих событий на выбранный период."
    
    text = "📅 Предстоящие события:\n\n"
    for event in events:
        start_time = event['start'].strftime("%d.%m.%Y %H:%M")
        text += f"🕒 {start_time}\n"
        text += f"📌 {event['summary']}\n"
        
        if event['location'] != 'Без места':
            text += f"📍 {event['location']}\n"
        
        if event['description'] != 'Без описания':
            # Ограничиваем длину описания
            description = event['description']
            if len(description) > 100:
                description = description[:97] + "..."
            text += f"ℹ️ {description}\n"
        
        text += "\n"
    
    return text