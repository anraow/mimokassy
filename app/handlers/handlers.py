from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram import F, Router

from app.models.models import SessionLocal
from app.models.models import User, Store, Category, Staff, Order
from app.loader import bot, logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from typing import Union
import re

router = Router(name = __name__)
MSK = timezone(timedelta(hours=3))

class OrderState(StatesGroup):
    SELECT_STORE = State()
    SELECT_ITEMS = State()
    CART = State()
    TIME_WINDOW = State()
    CUSTOM_TIME_INPUT = State()
    CONFIRM_ORDER = State()
    PAYMENT = State()
    PAYMENT_METHOD = State()

class StaffState(StatesGroup):
    INCOMING_ORDER = State()
    ISSUE_ORDER = State() 

async def check_order_timeouts():
    try:
        with SessionLocal() as session:
            threshold = datetime.now() - timedelta(minutes=15)
            
            expired_orders = session.query(Order).filter(
                Order.status == 'CREATED',
                Order.created_at < threshold
            ).all()
            
            for order in expired_orders:
                order.status = 'CANCELLED'
                session.commit()
                
                builder = InlineKeyboardBuilder()
                builder.add(
                    InlineKeyboardButton(
                        text='Повторить заказ',
                        style='primary',
                        callback_data=f'retry_order:{order.id}'
                    ),
                    InlineKeyboardButton(
                        text='Отмена',
                        style='danger',
                        callback_data='cancel'
                    )
                )
                builder.adjust(2)
                
                try:
                    await bot.send_message(
                        chat_id=order.client_id,
                        text='Время ожидания истекло. Заказ не был принят.', 
                        reply_markup=builder.as_markup()
                    )
                    
                except Exception as e:
                    logger.error(f'Failed to notify user {order.client_id}: {e}')
    except Exception as e:
        logger.error(f'Error in timeout loop: {e}')

@router.callback_query(F.data.startswith('retry_order:'))
async def retry_order_handler(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(':')[1])
    
    try:
        with SessionLocal() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            
            if not order:
                await c.answer("Заказ не найден.")
                return

            order.status = 'CREATED'
            order.created_at = datetime.now(MSK)
            session.commit()
            
            store_id = order.store_id

        await c.message.edit_text(
            text=f"Заказ №{order_id} отправлен повторно.",
            parse_mode='HTML'
        )
        
        await notify_staff_new_order(order_id, store_id)
        await c.answer("Заказ обновлен")

    except Exception as e:
        logger.error(f"Error retrying order {order_id}: {e}")
        await c.answer("Ошибка при обновлении заказа.", show_alert=True)
        
@router.message(CommandStart())
async def start_command(m: Message, state: FSMContext):
    try:
        await state.set_state(OrderState.SELECT_STORE)

        telegram_id = m.from_user.id
        username = m.from_user.username
        first_name = m.from_user.first_name
        
        with SessionLocal() as session:
            existing_user = session.query(User).filter(User.telegram_id == telegram_id).first()
            
            if existing_user:
                logger.info('User already exists.')
            else:
                new_user = User(telegram_id=telegram_id, username=username, first_name=first_name)
                session.add(new_user)
                session.commit()
                logger.info(f'New user added: {new_user.id}') 
        
        builder = InlineKeyboardBuilder()
        builder.button(text='Выбрать заведение', callback_data='choose_store')
        builder.adjust(1)
        
        await m.answer(
            text=f'Привет, {first_name}!\n\nЗдесь ты можешь сделать заказ онлайн, а затем прийти в заведение и забрать его <b>без очереди</b>.\n\nДля начала нажми кнопку "Выбрать заведение".', 
            parse_mode='HTML', 
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f'Error during start command: {e}')
        await m.answer('Возникла ошибка. Попробуйте еще раз.')

@router.message(Command('new'))
@router.callback_query(OrderState.SELECT_STORE, F.data == 'choose_store')
async def choose_store(event: Union[Message, CallbackQuery], state: FSMContext):
    is_callback = isinstance(event, CallbackQuery)
    msg_obj = event.message if is_callback else event
    
    msg_text = 'Заведения: '
    builder = InlineKeyboardBuilder()
    
    try:
        with SessionLocal() as session:
            stores = session.query(Store).all()

            if not stores:
                if is_callback:
                    await event.answer('Заведения недоступны.', show_alert=True)
                else:
                    await event.answer('Заведения недоступны.')
                return 
            
            active_store_ids = {
                s.store_id for s in session.query(Staff.store_id)
                .filter(Staff.status == 'active').all()
            }
            
            for i, store in enumerate(stores, start=1):
                msg_text += f'\n\n<b>{i}. {store.name}</b>\n{store.address} ({store.working_hours})'

                status_tag = " (🟢 открыто)" if store.id in active_store_ids else ""
                builder.button(
                    text=f'{store.name}{status_tag}', 
                    callback_data=f'store:{store.id}'
                )

            builder.adjust(1)
            await state.set_state(OrderState.SELECT_ITEMS)

            if is_callback:
                await bot.edit_message_text(
                    text=msg_text,
                    chat_id=msg_obj.chat.id,
                    message_id=msg_obj.message_id,
                    parse_mode='HTML',
                    reply_markup=builder.as_markup()
                )
            else:
                await msg_obj.answer(text=msg_text, parse_mode='HTML', reply_markup=builder.as_markup())
                        
    except Exception as e:
        logger.error(f'Error listing stores: {e}')
        error_text = 'Ошибка загрузки заведений. Попробуйте еще раз.'
        if is_callback:
            await bot.edit_message_text(text=error_text, chat_id=msg_obj.chat.id, message_id=msg_obj.message_id)
        else:
            await msg_obj.answer(error_text)

@router.callback_query(OrderState.SELECT_ITEMS, lambda c: c.data.startswith('store:'))
async def choose_items(c: CallbackQuery, state: FSMContext):
    store_id = c.data.split(':')[1]
    await state.update_data(current_store_id=store_id)
    
    await render_menu(c, state, store_id)

@router.callback_query(lambda c: c.data.startswith('add:'))
async def add_to_cart(c: CallbackQuery, state: FSMContext):
    item_id = c.data.split(':')[1]

    data = await state.get_data()
    cart = data.get('cart', {})
    cart[item_id] = cart.get(item_id, 0) + 1
    await state.update_data(cart=cart)

    store_id = data.get('current_store_id')
    if store_id:
        await render_menu(c, state, store_id)
        
    item_name = "Товар"
    try:
        with SessionLocal() as session:
            item = session.query(Category).filter(Category.id == item_id).first()
            if item:
                item_name = item.name
            
            await c.answer(text=f'{item_name} — добавлен в корзину.')
            
    except Exception as e:
        logger.error(f'Error adding item: {e}')
        await c.answer(text='Ошибка. Попробуйте еще раз.')

@router.callback_query(F.data =='view_cart')
async def view_cart(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cart = data.get('cart', {})

    if not cart:
        await c.answer(text='Ваша корзина пуста.', show_alert=True)
    
        store_id = data.get('current_store_id')
        if store_id and "Меню:" not in (c.message.text or ""):
            await render_menu(c, state, store_id)
        return

    msg = '<b>Ваша корзина:</b>'
    builder = InlineKeyboardBuilder()
    total_summary = 0
    
    try:
        with SessionLocal() as session:
            for i, (item_id, quantity) in enumerate(cart.items(), start=1):
                item = session.query(Category).filter(Category.id == item_id).first()
                
                if item:
                    item_price = item.price * quantity
                    total_summary += item_price
                    
                    msg += f'\n\n{i}. {item.name} (x{quantity}) — {item_price} руб.'

        msg += f'\n\n<b>Итого: {total_summary} руб.</b>'
        
        builder.row(InlineKeyboardButton(text='Оформить заказ', style='success', callback_data='create_order'))
        builder.row(InlineKeyboardButton(text='Убрать товары', style='danger', callback_data='edit_cart'))
        builder.row(InlineKeyboardButton(text='Меню', style='primary', callback_data='back_to_menu'))
        
        await bot.edit_message_text(
            text=msg,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id, 
            reply_markup=builder.as_markup(),
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f'Failed viewing cart: {e}')
        await bot.edit_message_text(
            text='Ошибка загрузки корзины. Попробуйте еще раз.',
            chat_id=c.message.chat.id,
            message_id=c.message.message_id
        )

@router.callback_query(F.data == 'edit_cart')
async def edit_cart_mode(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cart = data.get('cart', {})

    msg = '<b>Режим редактирования</b>\nНажмите на товар, чтобы уменьшить количество или удалить его:'
    builder = InlineKeyboardBuilder()

    with SessionLocal() as session:
        for item_id, quantity in cart.items():
            item = session.query(Category).filter(Category.id == item_id).first()
            if item:
                builder.add(InlineKeyboardButton(
                    text=f'❌ {item.name} ({quantity} шт.)',
                    style='danger',
                    callback_data=f'remove:{item_id}'
                ))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text='Вернуться в корзину', style='primary', callback_data='view_cart'))

    await bot.edit_message_text(
        text=msg,
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        reply_markup=builder.as_markup(),
        parse_mode='HTML'
    )

@router.callback_query(lambda c: c.data.startswith('remove:'))
async def remove_from_cart(c: CallbackQuery, state: FSMContext):
    item_id = c.data.split(':')[1]
    data = await state.get_data()
    cart = data.get('cart', {})

    if item_id in cart:
        if cart[item_id] > 1:
            cart[item_id] -= 1
        else:
            del cart[item_id]
    
    await state.update_data(cart=cart)
    
    if not cart:
        await view_cart(c, state)
    else:
        await edit_cart_mode(c, state)

@router.callback_query(F.data == 'create_order')
async def choose_pickup_time(c: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.TIME_WINDOW)
    builder = InlineKeyboardBuilder()
    
    try:
        builder.add(InlineKeyboardButton(text='Ближайшее время', callback_data='set_time:asap'))
        builder.row(
            InlineKeyboardButton(text='30 мин', callback_data='set_time:30'),
            InlineKeyboardButton(text='45 мин', callback_data='set_time:45'),
            InlineKeyboardButton(text='через час', callback_data='set_time:60')
        )
        builder.add(InlineKeyboardButton(text='Другое время', style='primary',  callback_data='set_custom_time'))
        builder.add(InlineKeyboardButton(text='Отменить заказ', style='danger', callback_data='cancel'))
        builder.adjust(1, 3, 1, 1)
        msg = 'Выберите время готовности заказа: '
        
        await bot.edit_message_text(
            text=msg,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id, 
            reply_markup=builder.as_markup(),
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f'Failed choose time: {e}')
        await bot.edit_message_text(
            text='Ошибка выбора времени. Попробуйте еще раз.',
            chat_id=c.message.chat.id,
            message_id=c.message.message_id
        )

@router.callback_query(lambda c: c.data.startswith('set_time:'))
async def set_time(c: CallbackQuery, state: FSMContext):
    timing_map = {
        'asap': (15, 'ASAP'),
        '30': (30, '30'),
        '45': (45, '45'),
        '60': (60, '60')
    }
    
    key = c.data.split(':')[1]
    minutes_offset, option = timing_map[key]
    target_time = datetime.now(MSK) + timedelta(minutes=minutes_offset)
    
    await state.update_data(
        pickup_option=option,
        target_ready_at=target_time
    )

    await c.answer()
    
    await state.set_state(OrderState.PAYMENT)
    await show_payment_methods(c, state)

@router.callback_query(F.data == 'set_custom_time')
async def set_custom_time(c: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.CUSTOM_TIME_INPUT)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text='Отменить заказ', style='danger', callback_data='cancel'))
    
    await c.message.edit_text(
        text="Введите время в формате ЧЧ:ММ (например, 15:30):",
        reply_markup=builder.as_markup()
    )
    await c.answer()

@router.message(OrderState.CUSTOM_TIME_INPUT)
async def process_custom_time(m: Message, state: FSMContext):
    time_match = re.match(r'^([01]?[0-9]|2[0-3]):([0-5][0-9])$', m.text)
    if not time_match:
        await m.answer("Ошибка. Используйте формат ЧЧ:ММ (например, 14:00)")
        return

    hours, minutes = map(int, time_match.groups())
    now = datetime.now(MSK)
    target_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    
    if target_time < now:
        target_time += timedelta(days=1)

    await state.update_data(
        pickup_option='CUSTOM',
        target_ready_at=target_time
    )
    await m.answer(f"Время {m.text} принято.")
    
    await state.set_state(OrderState.PAYMENT)
    await show_payment_methods(m, state)

@router.callback_query(OrderState.PAYMENT)
async def show_payment_methods(event: Union[CallbackQuery, Message], state: FSMContext):
    await state.set_state(OrderState.PAYMENT_METHOD)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Картой онлайн", callback_data="pay:card"),
        InlineKeyboardButton(text="📱 СБП", callback_data="pay:sbp")
    )
    builder.row(InlineKeyboardButton(text="Отменить заказ", style='danger', callback_data="cancel"))
    
    text = "<b>Оплата заказа</b>\n\nВыберите способ оплаты для завершения оформления:"
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='HTML')
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode='HTML')

@router.callback_query(OrderState.PAYMENT_METHOD, F.data.startswith('pay:'))
async def process_payment_prototype(c: CallbackQuery, state: FSMContext):
    method = c.data.split(':')[1].upper()
    await c.message.edit_text(f"🔄 Установка соединения с {method}...")
    
    import asyncio
    await asyncio.sleep(1)
    
    await c.message.edit_text(f"✅ Оплата через {method} прошла успешно!")
    
    await finalize_order_creation(c, state)

async def finalize_order_creation(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cart = data.get('cart', {})
    store_id = data.get('current_store_id')
    pickup_option = data.get('pickup_option')
    target_ready_at = data.get('target_ready_at')
    
    try:
        with SessionLocal() as session:
            total_sum = 0
            for item_id, quantity in cart.items():
                item = session.query(Category).filter(Category.id == int(item_id)).first()
                if item:
                    total_sum += item.price * quantity
            
            new_order = Order(
                client_id=c.from_user.id, 
                store_id=int(store_id),
                items=cart,
                total_price=total_sum,
                pickup_option=pickup_option,
                target_ready_at=target_ready_at,
                payment_status='PAID',
                status='CREATED',
                created_at=datetime.now(MSK)
            )
            
            session.add(new_order)
            session.commit()
            order_id = new_order.id
            target_store_id = new_order.store_id

        await notify_staff_new_order(order_id, target_store_id)
        
        await c.message.answer(
            text=f'<b>Заказ №{order_id} успешно создан!</b>. Мы сообщим, когда он будет готов.\n',
            parse_mode='HTML'
        )
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error finalizing order: {e}")
        await c.answer("Ошибка при сохранении заказа", show_alert=True)

@router.callback_query(F.data=='cancel')
@router.message(Command('cancel'))
async def handle_cancel(event: Union[Message, CallbackQuery], state: FSMContext):
    msg = event if isinstance(event, Message) else event.message
    
    await state.clear()
    
    if isinstance(event, CallbackQuery):
        await event.answer()
        await msg.edit_text('Отменено успешно')
    else:
        await msg.answer('Отменено успешно')

@router.callback_query(F.data == 'back_to_menu')
async def back_to_menu(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    store_id = data.get('current_store_id', '')
    
    if store_id:
        await render_menu(c, state, store_id)
    
async def render_menu(c: CallbackQuery, state: FSMContext, store_id: str):
    data = await state.get_data()
    cart = data.get('cart', {})
    total_items = sum(cart.values())

    msg = 'Меню: '
    builder = InlineKeyboardBuilder()
    cart_btn_text = f'Корзина ({total_items})' if total_items > 0 else 'Корзина'
    
    try:
        with SessionLocal() as session:
            items = session.query(Category).filter(Category.store_id==store_id).all()

            if not items:
                await c.answer('Пусто.', show_alert=True)
                return 
            
            for i, item in enumerate(items, start=1):
                msg += f'\n\n<b>{i}. {item.name}</b> — {item.price} руб.'
                builder.add(InlineKeyboardButton(text=item.name, style='success', callback_data=f'add:{item.id}'))
            
            builder.adjust(3)
            builder.row(InlineKeyboardButton(text=cart_btn_text, style='primary', callback_data='view_cart'))
            builder.row(InlineKeyboardButton(text='Отменить заказ', style='danger', callback_data='cancel'))
            
            await bot.edit_message_text(
                text=msg,
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                reply_markup=builder.as_markup(),
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f'Error listing items: {e}')
        await bot.edit_message_text(
            text='Ошибка загрузки меню. Попробуйте еще раз.',
            chat_id=c.message.chat.id,
            message_id=c.message.message_id
        )

@router.message(Command('start_session'))
async def start_worker_session(m: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    
    try:
        await state.set_state(StaffState.INCOMING_ORDER)
        telegram_id = m.from_user.id
        
        with SessionLocal() as session:
            existing_worker = session.query(Staff).filter(Staff.user_id == telegram_id).first()
            if existing_worker:
                builder.add(
                    InlineKeyboardButton(text='Да', style='success', callback_data=f'start_session:{telegram_id}'),
                    InlineKeyboardButton(text='Отмена', style='danger', callback_data='cancel')
                )

                builder.adjust(2)
                await m.answer(
                    text='Хотите начать смену, чтобы получать заказы?', 
                    reply_markup=builder.as_markup()
                )
            else:
                await m.answer('Доступ запрещен. Вы не являетесь сотрудником.')
                
    except Exception as e:
        logger.error(f'Error starting worker session: {e}')
        await m.answer('Ошибка. Попробуйте позже.')

@router.message(Command('close_session'))
async def close_worker_session(m: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    
    try:
        telegram_id = m.from_user.id
        
        with SessionLocal() as session:
            existing_worker = session.query(Staff).filter(Staff.user_id == telegram_id).first()
            if existing_worker:
                builder.add(
                    InlineKeyboardButton(text='Да', style='success', callback_data=f'stop_session:{telegram_id}'),
                    InlineKeyboardButton(text='Отмена', style='danger', callback_data='cancel')
                )
                builder.adjust(2)
                
                await m.answer(
                    text='Хотите завершить смену? Вы перестанете получать заказы.', 
                    reply_markup=builder.as_markup()
                )
            else:
                await m.answer('Ошибка. Вы не сотрудник.')
                
    except Exception as e:
        logger.error(f'Error closing worker session cmd: {e}')
        await m.answer('Ошибка. Попробуйте позже.')

@router.callback_query(lambda c: c.data.startswith('stop_session:'))
async def process_stop_session(c: CallbackQuery, state: FSMContext):
    try:
        with SessionLocal() as session:
            worker = session.query(Staff).filter(Staff.user_id == c.from_user.id).first()
            if worker:
                worker.status = 'inactive'
                session.commit()
        
        await state.clear()
        await c.message.edit_text("Смена завершена.")
        await c.answer("Смена окончена")
    except Exception as e:
        logger.error(f'Error stopping session: {e}')
        await c.answer('Ошибка при закрытии смены.', show_alert=True)

@router.callback_query(StaffState.INCOMING_ORDER, lambda c: c.data.startswith('start_session:'))
async def waiting_for_orders(c: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    
    try:
        with SessionLocal() as session:
            worker = session.query(Staff).filter(Staff.user_id == c.from_user.id).first()
            
            if worker:
                worker.status = 'active'
                session.commit()
                
            pending_orders = session.query(Order).filter(Order.status == 'CREATED').all()
            
            if not pending_orders:
                builder.row(InlineKeyboardButton(text='Закончить смену', style='danger', callback_data='stop_session:'))
                
                await c.message.edit_text(
                    text='<b>Заказов пока нет.</b>\n',
                    parse_mode='HTML',
                    reply_markup=builder.as_markup()
                )
                await c.answer()
                return

            msg_text = '<b>Список доступных заказов:</b>'
            for order in pending_orders:
                time_str = order.created_at.strftime("%H:%M") if order.created_at else "N/A"
                builder.add(InlineKeyboardButton(
                    text=f'📦 Заказ #{order.id} [{time_str}]',
                    style='success',
                    callback_data=f'accept_order:{order.id}'
                ))
        
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text='Закончить смену', style='danger', callback_data='stop_session:'))

        await c.message.edit_text(
            text=msg_text,
            reply_markup=builder.as_markup(),
            parse_mode='HTML'
        )
        await c.answer()

    except Exception as e:
        logger.error(f'Error in waiting_for_orders: {e}')
        await c.answer('Ошибка при получении списка заказов.', show_alert=True)
    
@router.callback_query(lambda c: c.data.startswith('accept_order:'))
async def accept_order(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(':')[1])
    items_text = ''
    
    try:
        with SessionLocal() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            items = order.items
            await state.set_state(StaffState.ISSUE_ORDER)
            
            if not order:
                await c.answer("Заказ не найден.", show_alert=True)
                return

            if order.status != 'CREATED':
                await c.answer("Этот заказ уже обрабатывается другим сотрудником.", show_alert=True)
                return

            order.status = 'ACCEPTED'
            order.staff_id = c.from_user.id
            session.commit()
            builder = InlineKeyboardBuilder()
            builder.button(text='Заказ готов', style='primary', callback_data=f'issue_order:{order.id}')
            
            for i, (item_id, quantity) in enumerate(order.items.items(), start=1):
                item = session.query(Category).filter(Category.id == int(item_id)).first()
                
                if item:
                    items_text += f"\n{i}. {item.name} <b>(x{quantity})</b>"
                else:
                    items_text += f"\n{i}. ID {item_id} <b>(x{quantity})</b>"
                    
            await c.message.edit_text(
                text=f"<b>Вы приняли заказ #{order_id}!</b>\nПожалуйста, приступите к выполнению.\n\n<b>Состав заказа:</b>{items_text}",
                parse_mode='HTML',
                reply_markup=builder.as_markup()
            )

            try:
                client_id = order.client_id 
                await bot.send_message(
                    chat_id=client_id,
                    text="<b>Ваш заказ принят!</b> Он будет готов в течение 5-15 минут.",
                    parse_mode='HTML'
                )
            except Exception as notify_error:
                logger.error(f"Failed to notify client {order.user_id}: {notify_error}")

            await c.answer("Заказ принят")

    except Exception as e:
        logger.error(f"Error accepting order: {e}")
        await c.answer("Ошибка при принятии заказа.", show_alert=True)
      
@router.callback_query(StaffState.ISSUE_ORDER, lambda c: c.data.startswith('issue_order:'))
async def issue_order(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(':')[1])
    
    try:
        with SessionLocal() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            
            if not order:
                await c.answer("Заказ не найден.", show_alert=True)
                return

            order.status = 'COMPLETED'
            session.commit()

            builder = InlineKeyboardBuilder()
            builder.button(text='К списку заказов', style='primary', callback_data=f'start_session:{c.from_user.id}')
            
            await c.message.answer(
                text=f"<b>Заказ #{order_id} выполнен!</b>\n\n<i>Выдайте его клиенту, уточнив номер заказа при необходимости.</i>\n\nВернуться к списку заказов можно, нажав кнопку выше.",
                parse_mode='HTML',
            )
            
            await c.message.edit_text(
                text='Хотите приступить к следующим заказам?', 
                parse_mode='HTML',
                reply_markup=builder.as_markup()
            )

            try:
                await bot.send_message(
                    chat_id=order.client_id,
                    text=f"✅ <b>Ваш заказ готов.</b> Номер заказа #{order_id}.",
                    parse_mode='HTML'
                )
                
            except Exception as notify_error:
                logger.error(f"Не удалось уведомить клиента {order.user_id}: {notify_error}")

            await state.set_state(StaffState.INCOMING_ORDER)
            await c.answer("Заказ выдан")

    except Exception as e:
        logger.error(f"Ошибка при выдаче заказа: {e}")
        await c.answer("Ошибка базы данных.", show_alert=True)
        

async def notify_staff_new_order(order_id: int, store_id: int):
    try:
        with SessionLocal() as session:
            active_staff = session.query(Staff).filter(
                Staff.store_id == store_id, 
                Staff.status == 'active'
            ).all()

            for staff in active_staff:
                builder = InlineKeyboardBuilder()
                builder.add(InlineKeyboardButton(
                    text="Принять заказ", 
                    style='success', 
                    callback_data=f"accept_order:{order_id}"
                ))
                
                try:
                    await bot.send_message(
                        chat_id=staff.user_id,
                        text=f"🔔 <b>Новый заказ #{order_id}!</b>",
                        reply_markup=builder.as_markup(),
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Could not notify staff {staff.user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"Database error in notify_staff: {e}")