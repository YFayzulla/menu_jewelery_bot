import os
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hbold
from sqlalchemy import select, delete
from app.database import async_session, Category, SubCategory

router = Router()

class AdminStates(StatesGroup):
    ADD_CATEGORY = State()
    DELETE_CATEGORY = State()
    ADD_SUBCATEGORY = State()
    DELETE_SUBCATEGORY = State()

class ChatCleaner:
    def __init__(self):
        self.last_user_message = None
        self.last_bot_message = None
    
    async def track_user_message(self, message: Message):
        """Track the last user message to delete later"""
        self.last_user_message = message
    
    async def cleanup(self, bot: Bot):
        """Delete both user and bot messages"""
        try:
            if self.last_user_message:
                await bot.delete_message(
                    self.last_user_message.chat.id,
                    self.last_user_message.message_id
                )
                self.last_user_message = None
        except Exception:
            pass
        
        try:
            if self.last_bot_message:
                await bot.delete_message(
                    self.last_bot_message.chat.id,
                    self.last_bot_message.message_id
                )
                self.last_bot_message = None
        except Exception:
            pass
    
    async def send_bot_message(self, bot: Bot, chat_id: int, text: str, 
                             reply_markup=None, delete_previous=True):
        """Send bot message with automatic cleanup"""
        if delete_previous:
            await self.cleanup(bot)
        
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        self.last_bot_message = msg
        return msg

chat_cleaner = ChatCleaner()

# Fetch categories from the database
async def get_categories():
    async with async_session() as session:
        result = await session.execute(select(Category))
        return result.scalars().all()

# Fetch subcategories for a given category
async def get_subcategories(category_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(SubCategory).where(SubCategory.category_id == category_id)
        )
        return result.scalars().all()

# Show categories with inline keyboard
async def show_categories(bot: Bot, chat_id: int):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")]
        for cat in categories
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="➕ Create Category", callback_data="add_category"),
        InlineKeyboardButton(text="🗑️ Delete Category", callback_data="delete_category")
    ])
    await chat_cleaner.send_bot_message(
        bot, chat_id,
        hbold("📋 Categories:") if categories else "No categories available",
        reply_markup=kb
    )

# Start command handler
@router.message(Command("start"))
async def start(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    await state.clear()
    await show_categories(bot, message.chat.id)

# Callback handler for selecting a category
@router.callback_query(F.data.startswith("cat_"))
async def select_category(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    category_id = int(call.data.split("_")[1])
    subcategories = await get_subcategories(category_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub.name, callback_data=f"sub_{sub.id}")]
        for sub in subcategories
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="➕ Create Subcategory", callback_data=f"add_subcategory_{category_id}"),
        InlineKeyboardButton(text="🗑️ Delete Subcategory", callback_data=f"delete_subcategory_{category_id}"),
        InlineKeyboardButton(text="🔙 Back", callback_data="back_to_categories")
    ])
    
    await chat_cleaner.send_bot_message(
        bot, call.message.chat.id,
        hbold(f"📋 Subcategories:") if subcategories else "No subcategories available",
        reply_markup=kb
    )

# Callback handler to go back to categories
@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await show_categories(bot, call.message.chat.id)

# Callback handler to add a category
@router.callback_query(F.data == "add_category")
async def add_category_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await chat_cleaner.send_bot_message(
        bot, call.message.chat.id,
        "Enter new category name:",
        delete_previous=True
    )
    await state.set_state(AdminStates.ADD_CATEGORY)

# Message handler to finish adding a category
@router.message(StateFilter(AdminStates.ADD_CATEGORY))
async def add_category_finish(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    
    async with async_session() as session:
        existing = await session.execute(
            select(Category).where(Category.name == message.text)
        )
        if existing.scalar():
            await chat_cleaner.send_bot_message(
                bot, message.chat.id,
                "❌ Category already exists!",
                delete_previous=False
            )
            return
        
        new_category = Category(name=message.text)
        session.add(new_category)
        await session.commit()
        
        await chat_cleaner.send_bot_message(
            bot, message.chat.id,
            f"✅ Category {hbold(message.text)} added successfully!",
            delete_previous=False
        )
    
    await state.clear()
    await asyncio.sleep(2)  # Show success message for 2 seconds
    await show_categories(bot, message.chat.id)

# Callback handler to delete a category
@router.callback_query(F.data == "delete_category")
async def delete_category_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {cat.name}", callback_data=f"delcat_{cat.id}")]
        for cat in categories
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Back", callback_data="back_to_categories")
    ])
    
    await chat_cleaner.send_bot_message(
        bot, call.message.chat.id,
        "Select category to delete:",
        reply_markup=kb
    )
    await state.set_state(AdminStates.DELETE_CATEGORY)

# Callback handler to confirm category deletion
@router.callback_query(StateFilter(AdminStates.DELETE_CATEGORY), F.data.startswith("delcat_"))
async def delete_category_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[1])
    
    # Store category_id in state for later use
    await state.update_data(category_id=category_id)
    
    # Ask for confirmation
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, delete", callback_data="confirm_delete_category")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_delete_category")]
    ])
    
    await chat_cleaner.send_bot_message(
        bot, call.message.chat.id,
        "Are you sure you want to delete this category?",
        reply_markup=kb
    )

@router.callback_query(F.data == "confirm_delete_category")
async def delete_category_execute(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category_id = data.get('category_id')
    
    async with async_session() as session:
        await session.execute(delete(Category).where(Category.id == category_id))
        await session.commit()
    
    await call.answer("Category deleted successfully!")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data == "cancel_delete_category")
async def delete_category_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Deletion cancelled")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

# Similar pattern for subcategory handlers...
# [Rest of your subcategory handlers follow the same improved pattern]