import os
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hbold
from sqlalchemy import select, delete
from app.database import async_session, Category, SubCategory, Product

router = Router()

class AdminStates(StatesGroup):
    ADD_CATEGORY = State()
    DELETE_CATEGORY = State()
    ADD_SUBCATEGORY = State()
    SELECT_CATEGORY_FOR_SUB = State()
    DELETE_SUBCATEGORY = State()
    CONFIRM_DELETE = State()

def is_admin(user_id: int) -> bool:
    return user_id == int(os.getenv("ADMIN_ID", "0"))

# Utility function to delete messages safely
async def delete_message_safe(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

# Utility function to clear chat history
async def clear_chat_history(bot: Bot, chat_id: int, limit: int = 10):
    try:
        # In aiogram, you need to get messages first then delete them
        messages = await bot.get_chat_administrators(chat_id)  # This is just a placeholder
        # Actual implementation would need to track messages or use a different approach
        for msg in messages:
            await delete_message_safe(bot, chat_id, msg.message_id)
    except Exception:
        pass

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
    await bot.send_message(chat_id, hbold("📋 Categories:") if categories else "No categories available", reply_markup=kb)

# Start command handler
@router.message(Command("start"))
async def start(message: Message, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, message.chat.id)
    await state.clear()
    await show_categories(bot, message.chat.id)

# Callback handler for selecting a category
@router.callback_query(F.data.startswith("cat_"))
async def select_category(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
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
    await bot.send_message(call.message.chat.id, hbold(f"📋 Subcategories:") if subcategories else "No subcategories available", reply_markup=kb)

# Callback handler to go back to categories
@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
    await state.clear()
    await show_categories(bot, call.message.chat.id)

# Callback handler to add a category
@router.callback_query(F.data == "add_category")
async def add_category_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
    await bot.send_message(call.message.chat.id, "Enter new category name:")
    await state.set_state(AdminStates.ADD_CATEGORY)

# Message handler to finish adding a category
@router.message(StateFilter(AdminStates.ADD_CATEGORY))
async def add_category_finish(message: Message, state: FSMContext, bot: Bot):
    async with async_session() as session:
        existing = await session.execute(
            select(Category).where(Category.name == message.text)
        )
        if existing.scalar():
            await message.answer("❌ Category already exists!")
            return
        new_category = Category(name=message.text)
        session.add(new_category)
        await session.commit()
        await message.answer(f"✅ Category {hbold(message.text)} added successfully!")
    await state.clear()
    await show_categories(bot, message.chat.id)

# Callback handler to delete a category
@router.callback_query(F.data == "delete_category")
async def delete_category_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {cat.name}", callback_data=f"delcat_{cat.id}")]
        for cat in categories
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Back", callback_data="back_to_categories")
    ])
    await bot.send_message(call.message.chat.id, "Select category to delete:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_CATEGORY)

# Callback handler to confirm category deletion
@router.callback_query(StateFilter(AdminStates.DELETE_CATEGORY), F.data.startswith("delcat_"))
async def delete_category(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[1])
    async with async_session() as session:
        await session.execute(delete(Category).where(Category.id == category_id))
        await session.commit()
    await call.answer("Category deleted")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

# Callback handler to add a subcategory
@router.callback_query(F.data.startswith("add_subcategory_"))
async def add_subcategory_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
    category_id = int(call.data.split("_")[-1])
    await state.update_data(category_id=category_id)
    await bot.send_message(call.message.chat.id, "Enter new subcategory name:")
    await state.set_state(AdminStates.ADD_SUBCATEGORY)

# Message handler to finish adding a subcategory
@router.message(StateFilter(AdminStates.ADD_SUBCATEGORY))
async def add_subcategory_finish(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category_id = data.get('category_id')
    async with async_session() as session:
        existing = await session.execute(
            select(SubCategory).where(
                (SubCategory.name == message.text) &
                (SubCategory.category_id == category_id)
            )
        )
        if existing.scalar():
            await message.answer("❌ Subcategory already exists in this category!")
            return
        new_sub = SubCategory(name=message.text, category_id=category_id)
        session.add(new_sub)
        await session.commit()
        await message.answer(f"✅ Subcategory {hbold(message.text)} added successfully!")
    await state.clear()
    # Show subcategories for that category again
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
    await bot.send_message(message.chat.id, hbold(f"📋 Subcategories:") if subcategories else "No subcategories available", reply_markup=kb)

# Callback handler to delete a subcategory
@router.callback_query(F.data.startswith("delete_subcategory_"))
async def delete_subcategory_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_chat_history(bot, call.message.chat.id)
    category_id = int(call.data.split("_")[-1])
    subcategories = await get_subcategories(category_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {sub.name}", callback_data=f"delsub_{sub.id}_{category_id}")]
        for sub in subcategories
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Back", callback_data=f"cat_{category_id}")
    ])
    await bot.send_message(call.message.chat.id, "Select subcategory to delete:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_SUBCATEGORY)

# Callback handler to confirm subcategory deletion
@router.callback_query(StateFilter(AdminStates.DELETE_SUBCATEGORY), F.data.startswith("delsub_"))
async def delete_subcategory(call: CallbackQuery, state: FSMContext, bot: Bot):
    parts = call.data.split("_")
    sub_id = int(parts[1])
    category_id = int(parts[2])
    async with async_session() as session:
        await session.execute(delete(SubCategory).where(SubCategory.id == sub_id))
        await session.commit()
    await call.answer("Subcategory deleted")
    await state.clear()
    # Show subcategories for that category again
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
    await bot.send_message(call.message.chat.id, hbold(f"📋 Subcategories:") if subcategories else "No subcategories available", reply_markup=kb)