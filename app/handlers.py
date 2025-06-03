from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from app.database import get_categories, get_subcategories, get_products
import os
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.database import create_category, get_categories

class AdminStates(StatesGroup):
    ADD_CATEGORY = State()

router = Router()

@router.message(Command("start"))
async def start(message: Message):
    if message.from_user.id == int(os.getenv("ADMIN_ID")):
        await message.answer("🛠 Admin mode", reply_markup=admin_kb())
    else:
        await show_categories(message)

async def show_categories(message: Message):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")] 
        for cat in categories
    ])
    await message.answer("Categories:", reply_markup=kb)

@router.callback_query(F.data.startswith("cat_"))
async def show_subcategories(call: CallbackQuery):
    category_id = int(call.data.split("_")[1])
    subcategories = await get_subcategories(category_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub.name, callback_data=f"sub_{sub.id}")] 
        for sub in subcategories
    ])
    await call.message.edit_text("Subcategories:", reply_markup=kb)

@router.callback_query(F.data.startswith("sub_"))
async def show_products(call: CallbackQuery):
    subcategory_id = int(call.data.split("_")[1])
    products = await get_products(subcategory_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p.name} - ${p.price}", callback_data=f"prod_{p.id}")] 
        for p in products
    ])
    await call.message.edit_text("Products:", reply_markup=kb)

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Category", callback_data="add_category")],
        [InlineKeyboardButton(text="👀 View as User", callback_data="user_view")]
    ])


@router.callback_query(F.data == "add_category")
async def add_category_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Enter the new category name:")
    await state.set_state(AdminStates.ADD_CATEGORY)
    await call.answer()

@router.message(AdminStates.ADD_CATEGORY)
async def add_category_finish(message: Message, state: FSMContext):
    try:
        await create_category(message.text)
        await message.answer(f"✅ Category '{message.text}' added successfully!")
        await show_categories(message)  # Show updated list
    except Exception as e:
        await message.answer(f"❌ Error: {str(e)}")
    finally:
        await state.clear()

@router.callback_query(F.data == "user_view")
async def user_view(call: CallbackQuery):
    await call.message.delete()
    await show_categories(call.message)