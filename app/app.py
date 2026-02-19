from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from aiogram.types import Update, BotCommand
from contextlib import asynccontextmanager

from app.models.models import Session, SessionLocal
from app.handlers.handlers import check_order_timeouts, notify_upcoming_orders
from app.handlers.handlers import router
from app.loader import bot, dp, logger
from app.config import *

app = FastAPI()

async def set_my_commands():
    commands = [
        BotCommand(command="/start", description="Начать диалог"),
        BotCommand(command="/new", description="Сделать новый заказ"),
        BotCommand(command="/cancel", description="Отмена"),
    ]
    await bot.set_my_commands(commands)

@asynccontextmanager
async def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

async def on_startup():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_order_timeouts, 'interval', minutes=1)
    scheduler.add_job(notify_upcoming_orders, 'interval', minutes=1)
    scheduler.start()
    
    await bot.set_webhook(WEBHOOK_URL)
    await set_my_commands()
    logger.info("Webhook set and bot ready.")

async def on_shutdown():
    await bot.session.close()
    logger.info("Bot session closed.")

@app.post(WEBHOOK_PATH)
async def process_update(request: Request):
    update = Update(**await request.json())
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}

app.add_event_handler("startup", on_startup)
app.add_event_handler("shutdown", on_shutdown)
dp.include_router(router=router)