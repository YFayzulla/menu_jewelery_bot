import os
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hbold
from sqlalchemy import select, delete
from app.database import async_session, Category, SubCategory
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


router = Router()

class AdminStates(StatesGroup):
    ADD_CATEGORY = State()
    DELETE_CATEGORY = State()
    ADD_SUBCATEGORY = State()
    DELETE_SUBCATEGORY = State()

def is_admin(user_id: int) -> bool:
    return user_id == int(os.getenv("ADMIN_ID", "0"))

class ChatCleaner:
    def __init__(self):
        self.last_user_message = None
        self.last_bot_message = None

    async def track_user_message(self, message: Message):
        self.last_user_message = message

    async def cleanup(self, bot: Bot, chat_id: int):
        try:
            if self.last_user_message and self.last_user_message.chat.id == chat_id:
                await bot.delete_message(chat_id, self.last_user_message.message_id)
                self.last_user_message = None
        except Exception:
            pass
        try:
            if self.last_bot_message and self.last_bot_message.chat.id == chat_id:
                await bot.delete_message(chat_id, self.last_bot_message.message_id)
                self.last_bot_message = None
        except Exception:
            pass

    async def send_bot_message(self, bot: Bot, chat_id: int, text: str, reply_markup=None, delete_previous=True):
        if delete_previous:
            await self.cleanup(bot, chat_id)
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        self.last_bot_message = msg
        return msg

chat_cleaner = ChatCleaner()

async def get_categories():
    async with async_session() as session:
        result = await session.execute(select(Category))
        return result.scalars().all()

async def get_subcategories(category_id: int):
    async with async_session() as session:
        result = await session.execute(select(SubCategory).where(SubCategory.category_id == category_id))
        return result.scalars().all()

async def show_categories(bot: Bot, chat_id: int):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")] for cat in categories
    ])
    if is_admin(chat_id):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Create Category", callback_data="add_category"),
            InlineKeyboardButton(text="🗑️ Delete Category", callback_data="delete_category")
        ])
    await chat_cleaner.send_bot_message(bot, chat_id, hbold("📋 Categories:") if categories else "No categories available", reply_markup=kb)

@router.message(Command("start"))
async def start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    
    # Create persistent menu button
    menu_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Menu")]],
        resize_keyboard=True,
        persistent=True
    )
    
    if is_admin(message.from_user.id):
        await bot.send_message(
            message.chat.id,
            "👋 Hi admin, I am here to assist you.",
            reply_markup=menu_kb
        )
        await show_categories(bot, message.chat.id)
    else:
        await bot.send_message(
            message.chat.id,
            "🙋‍♂️ Hello! Tap the menu button below:",
            reply_markup=menu_kb
        )

# Handle the menu button tap
@router.message(F.text == "📋 Menu")
async def menu_button(message: Message, bot: Bot):
    await menu_command(message, bot)
            

@router.message(Command("menu"))
async def menu_command(message: Message, bot: Bot):
    await show_categories(bot, message.chat.id)

@router.callback_query(F.data.startswith("cat_"))
async def select_category(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    category_id = int(call.data.split("_")[1])
    subcategories = await get_subcategories(category_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub.name, callback_data=f"sub_{sub.id}")] for sub in subcategories
    ])
    if is_admin(call.from_user.id):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Create Subcategory", callback_data=f"add_subcategory_{category_id}"),
            InlineKeyboardButton(text="🗑️ Delete Subcategory", callback_data=f"delete_subcategory_{category_id}"),
            InlineKeyboardButton(text="🔙 Back", callback_data="back_to_categories")
        ])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, hbold(f"📋 Subcategories:") if subcategories else "No subcategories available", reply_markup=kb)

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data == "add_category")
async def add_category_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Enter new category name:", delete_previous=True)
    await state.set_state(AdminStates.ADD_CATEGORY)

@router.message(StateFilter(AdminStates.ADD_CATEGORY))
async def add_category_finish(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    if not message.text:
        await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Please enter a valid category name!", delete_previous=False)
        return
        
    async with async_session() as session:
        existing = await session.execute(select(Category).where(Category.name == message.text))
        if existing.scalar():
            await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Category already exists!", delete_previous=False)
            return
        new_category = Category(name=message.text)
        session.add(new_category)
        await session.commit()
        await chat_cleaner.send_bot_message(bot, message.chat.id, f"✅ Category {hbold(message.text)} added successfully!", delete_previous=False)
    await state.clear()
    await asyncio.sleep(2)
    await show_categories(bot, message.chat.id)

@router.callback_query(F.data == "delete_category")
async def delete_category_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    categories = await get_categories()
    if not categories:
        await call.answer("No categories to delete!")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {cat.name}", callback_data=f"delcat_{cat.id}")] for cat in categories
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="back_to_categories")])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Select category to delete:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_CATEGORY)

@router.callback_query(StateFilter(AdminStates.DELETE_CATEGORY), F.data.startswith("delcat_"))
async def delete_category_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[1])
    await state.update_data(category_id=category_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, delete", callback_data="confirm_delete_category")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_delete_category")]
    ])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Are you sure you want to delete this category and all its subcategories?", reply_markup=kb)

@router.callback_query(F.data == "confirm_delete_category")
async def delete_category_execute(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category_id = data.get('category_id')
    async with async_session() as session:
        # Get category name for confirmation message
        category = await session.get(Category, category_id)
        if not category:
            await call.answer("Category not found!")
            await state.clear()
            return
            
        await session.execute(delete(SubCategory).where(SubCategory.category_id == category_id))
        await session.execute(delete(Category).where(Category.id == category_id))
        await session.commit()
    await call.answer(f"Category '{category.name}' deleted successfully!")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data == "cancel_delete_category")
async def delete_category_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Deletion cancelled")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data.startswith("add_subcategory_"))
async def add_subcategory_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[2])
    await state.update_data(category_id=category_id)
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Enter new subcategory name:", delete_previous=True)
    await state.set_state(AdminStates.ADD_SUBCATEGORY)

@router.message(StateFilter(AdminStates.ADD_SUBCATEGORY))
async def add_subcategory_finish(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    if not message.text:
        await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Please enter a valid subcategory name!", delete_previous=False)
        return
        
    data = await state.get_data()
    category_id = data.get("category_id")
    async with async_session() as session:
        existing = await session.execute(
            select(SubCategory).where(
                SubCategory.name == message.text,
                SubCategory.category_id == category_id
            )
        )
        if existing.scalar():
            await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Subcategory already exists!", delete_previous=False)
            return
        new_sub = SubCategory(name=message.text, category_id=category_id)
        session.add(new_sub)
        await session.commit()
        await chat_cleaner.send_bot_message(bot, message.chat.id, f"✅ Subcategory {hbold(message.text)} added successfully!", delete_previous=False)
    await state.clear()
    await asyncio.sleep(2)
    
    # Create a fake CallbackQuery to reuse select_category
    from aiogram.types import CallbackQuery
    fake_call = CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="0",
        message=message,
        data=f"cat_{category_id}"
    )
    await select_category(fake_call, state, bot)

@router.callback_query(F.data.startswith("delete_subcategory_"))
async def delete_subcategory_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[2])
    await state.update_data(category_id=category_id)
    subcategories = await get_subcategories(category_id)
    
    if not subcategories:
        await call.answer("No subcategories to delete!")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {sub.name}", callback_data=f"delsub_{sub.id}")] for sub in subcategories
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"cat_{category_id}")])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Select subcategory to delete:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_SUBCATEGORY)
    
@router.callback_query(StateFilter(AdminStates.DELETE_SUBCATEGORY), F.data.startswith("delsub_"))
async def delete_subcategory_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    subcategory_id = int(call.data.split("_")[1])
    async with async_session() as session:
        # Get subcategory name for confirmation
        subcategory = await session.get(SubCategory, subcategory_id)
        if not subcategory:
            await call.answer("Subcategory not found!")
            return
            
        await session.execute(delete(SubCategory).where(SubCategory.id == subcategory_id))
        await session.commit()
        await call.answer(f"✅ Subcategory '{subcategory.name}' deleted successfully!")

    data = await state.get_data()
    category_id = data.get("category_id")
    await state.clear()

    # Create a fake CallbackQuery to reuse select_category
    fake_call = CallbackQuery(
        id="0",
        from_user=call.from_user,
        chat_instance="0",
        message=call.message,
        data=f"cat_{category_id}"
    )
    await select_category(fake_call, state, bot)