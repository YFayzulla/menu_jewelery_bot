import os
import asyncio
import urllib.parse
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hbold
from sqlalchemy import select, delete
from app.database import async_session, Category, SubCategory, Product
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

router = Router()

class AdminStates(StatesGroup):
    ADD_CATEGORY = State()
    DELETE_CATEGORY = State()
    ADD_SUBCATEGORY = State()
    DELETE_SUBCATEGORY = State()
    ADD_PRODUCT = State()
    DELETE_PRODUCT = State()

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
                print(f"Deleting user message: {self.last_user_message.message_id}")  # Debug log
                await bot.delete_message(chat_id, self.last_user_message.message_id)
                self.last_user_message = None
        except Exception as e:
            print(f"Error deleting user message: {e}")
        try:
            if self.last_bot_message and self.last_bot_message.chat.id == chat_id:
                print(f"Deleting bot message: {self.last_bot_message.message_id}")  # Debug log
                await bot.delete_message(chat_id, self.last_bot_message.message_id)
                self.last_bot_message = None
        except Exception as e:
            print(f"Error deleting bot message: {e}")

    async def send_bot_message(self, bot: Bot, chat_id: int, text: str, reply_markup=None, delete_previous=True):
        if delete_previous:
            await self.cleanup(bot, chat_id)
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
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

async def get_products(subcategory_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Product)
            .where(Product.sub_category_id == subcategory_id)
            .order_by(Product.name)
        )
        return result.scalars().all()

async def show_categories(bot: Bot, chat_id: int):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")] for cat in categories
    ])
    if is_admin(chat_id):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Kategoriya qo'shish", callback_data="add_category"),
            InlineKeyboardButton(text="🗑️ Kategoriyani o'chirish", callback_data="delete_category")
        ])
    await chat_cleaner.send_bot_message(bot, chat_id, hbold("📋 Kategoriyalar:") if categories else "Kategoriyalar mavjud emas", reply_markup=kb)

@router.message(Command("start"))
async def start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    menu_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Menyu")]],
        resize_keyboard=True,
        persistent=True
    )
    if is_admin(message.from_user.id):
        await bot.send_message(
            message.chat.id,
            "👋 Salom admin, men sizga yordam berish uchun shu yerdaman.",
            reply_markup=menu_kb,
            parse_mode="HTML"
        )
        await show_categories(bot, message.chat.id)
    else:
        await bot.send_message(
            message.chat.id,
            "🙋‍♂️ Salom! Quyidagi menyu tugmasini bosing:",
            reply_markup=menu_kb,
            parse_mode="HTML"
        )

@router.message(F.text == "📋 Menyu")
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
            InlineKeyboardButton(text="➕ Subkategoriya qo'shish", callback_data=f"add_subcategory_{category_id}"),
            InlineKeyboardButton(text="🗑️ Subkategoriyani o'chirish", callback_data=f"delete_subcategory_{category_id}"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_categories")
        ])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, hbold("📋 Subkategoriyalar:") if subcategories else "Subkategoriyalar mavjud emas", reply_markup=kb)

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data == "add_category")
async def add_category_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Yangi kategoriya nomini kiriting:", delete_previous=True)
    await state.set_state(AdminStates.ADD_CATEGORY)

@router.message(StateFilter(AdminStates.ADD_CATEGORY))
async def add_category_finish(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    if not message.text:
        await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Iltimos, haqiqiy kategoriya nomini kiriting!", delete_previous=False)
        return
    async with async_session() as session:
        existing = await session.execute(select(Category).where(Category.name == message.text))
        if existing.scalar():
            await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Kategoriya allaqachon mavjud!", delete_previous=False)
            return
        new_category = Category(name=message.text)
        session.add(new_category)
        await session.commit()
        await chat_cleaner.send_bot_message(bot, message.chat.id, f"✅ Kategoriya {hbold(message.text)} muvaffaqiyatli qo'shildi!", delete_previous=False)
    await state.clear()
    await asyncio.sleep(2)
    await show_categories(bot, message.chat.id)

@router.callback_query(F.data == "delete_category")
async def delete_category_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    categories = await get_categories()
    if not categories:
        await call.answer("O'chirish uchun kategoriyalar mavjud emas!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {cat.name}", callback_data=f"delcat_{cat.id}")] for cat in categories
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_categories")])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "O'chirish uchun kategoriyani tanlang:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_CATEGORY)

@router.callback_query(StateFilter(AdminStates.DELETE_CATEGORY), F.data.startswith("delcat_"))
async def delete_category_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[1])
    await state.update_data(category_id=category_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="confirm_delete_category")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_delete_category")]
    ])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Ushbu kategoriya va uning barcha subkategoriyalarini o'chirishga ishonchingiz komilmi?", reply_markup=kb)

@router.callback_query(F.data == "confirm_delete_category")
async def delete_category_execute(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category_id = data.get('category_id')
    async with async_session() as session:
        category = await session.get(Category, category_id)
        if not category:
            await call.answer("Kategoriya topilmadi!")
            await state.clear()
            return
        await session.execute(delete(SubCategory).where(SubCategory.category_id == category_id))
        await session.execute(delete(Category).where(Category.id == category_id))
        await session.commit()
    await call.answer(f"Kategoriya '{category.name}' muvaffaqiyatli o'chirildi!")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data == "cancel_delete_category")
async def delete_category_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("O'chirish bekor qilindi")
    await state.clear()
    await show_categories(bot, call.message.chat.id)

@router.callback_query(F.data.startswith("add_subcategory_"))
async def add_subcategory_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    category_id = int(call.data.split("_")[2])
    await state.update_data(category_id=category_id)
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Yangi subkategoriya nomini kiriting:", delete_previous=True)
    await state.set_state(AdminStates.ADD_SUBCATEGORY)

@router.message(StateFilter(AdminStates.ADD_SUBCATEGORY))
async def add_subcategory_finish(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    if not message.text:
        await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Iltimos, haqiqiy subkategoriya nomini kiriting!", delete_previous=False)
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
            await chat_cleaner.send_bot_message(bot, message.chat.id, "❌ Subkategoriya allaqachon mavjud!", delete_previous=False)
            return
        new_sub = SubCategory(name=message.text, category_id=category_id)
        session.add(new_sub)
        await session.commit()
        await chat_cleaner.send_bot_message(bot, message.chat.id, f"✅ Subkategoriya {hbold(message.text)} muvaffaqiyatli qo'shildi!", delete_previous=False)
    await state.clear()
    await asyncio.sleep(2)
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
        await call.answer("O'chirish uchun subkategoriyalar mavjud emas!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {sub.name}", callback_data=f"delsub_{sub.id}")] for sub in subcategories
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category_id}")])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "O'chirish uchun subkategoriyani tanlang:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_SUBCATEGORY)

@router.callback_query(StateFilter(AdminStates.DELETE_SUBCATEGORY), F.data.startswith("delsub_"))
async def delete_subcategory_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    subcategory_id = int(call.data.split("_")[1])
    async with async_session() as session:
        subcategory = await session.get(SubCategory, subcategory_id)
        if not subcategory:
            await call.answer("Subkategoriya topilmadi!")
            return
        await session.execute(delete(SubCategory).where(SubCategory.id == subcategory_id))
        await session.commit()
        await call.answer(f"✅ Subkategoriya '{subcategory.name}' muvaffaqiyatli o'chirildi!")
    data = await state.get_data()
    category_id = data.get("category_id")
    await state.clear()
    fake_call = CallbackQuery(
        id="0",
        from_user=call.from_user,
        chat_instance="0",
        message=call.message,
        data=f"cat_{category_id}"
    )
    await select_category(fake_call, state, bot)

@router.callback_query(F.data.startswith("sub_"))
async def select_subcategory(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    subcategory_id = int(call.data.split("_")[1])
    products = await get_products(subcategory_id)
    async with async_session() as session:
        subcategory = await session.get(SubCategory, subcategory_id)
        category = await session.get(Category, subcategory.category_id)
    if is_admin(call.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{product.name} - ${product.price}", callback_data=f"product_{product.id}")]
            for product in products
        ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Mahsulot qo'shish", callback_data=f"add_product_{subcategory_id}"),
            InlineKeyboardButton(text="🗑️ Mahsulotni o'chirish", callback_data=f"delete_product_{subcategory_id}"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category.id}")
        ])
        title = f"📋 {category.name} > {subcategory.name}\n\n"
        title += "Mavjud mahsulotlar:" if products else "Hozircha mahsulotlar mavjud emas"
        await chat_cleaner.send_bot_message(bot, call.message.chat.id, hbold(title), reply_markup=kb)
    else:
        if not products:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category.id}")]
            ])
            title = f"📋 {category.name} > {subcategory.name}\n\nHozircha mahsulotlar mavjud emas"
            await chat_cleaner.send_bot_message(bot, call.message.chat.id, hbold(title), reply_markup=kb)
        else:
            if not products:
                await call.answer("Mahsulotlar mavjud emas!")
                return
            await state.update_data(
                products=[p.id for p in products],
                current_index=0,
                category_id=category.id,
                subcategory_id=subcategory_id,
                parse_mode="HTML"
            )
            await show_product(call, state, bot, products[0], 0, len(products))

async def show_product(call: CallbackQuery, state: FSMContext, bot: Bot, product, current_index: int, total_products: int):
    async with async_session() as session:
        subcategory = await session.get(SubCategory, product.sub_category_id)
        category = await session.get(Category, subcategory.category_id)
    title = f"📋 {category.name} > {subcategory.name}\n\n"
    title += f"Mahsulot {current_index + 1}/{total_products}\n"
    title += f"Nomi: {hbold(product.name)}\n"
    title += f"Narxi: {hbold(product.price)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    if current_index > 0:
        row.append(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="prev_product"))
    if current_index < total_products - 1:
        row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data="next_product"))
    if row:
        kb.inline_keyboard.append(row)
    if not is_admin(call.from_user.id):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="🛒 Buyurtma berish", callback_data=f"order_{product.id}"),
            InlineKeyboardButton(text="🔙 Kategoriyalarga qaytish", callback_data=f"cat_{category.id}")
        ])
    else:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="🔙 Kategoriyalarga qaytish", callback_data=f"cat_{category.id}")
        ])

    if product.photo:
        await bot.send_photo(
            call.message.chat.id,
            product.photo,
            caption=title,
            reply_markup=kb,
            parse_mode="HTML"
        )

    else:
        await chat_cleaner.send_bot_message(
            bot,
            call.message.chat.id,
            title,
            reply_markup=kb,
            parse_mode="HTML"
        )

@router.callback_query(F.data.in_(["prev_product", "next_product"]))
async def navigate_products(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    product_ids = data.get("products", [])
    current_index = data.get("current_index", 0)
    total_products = len(product_ids)
    if not product_ids:
        await call.answer("Mahsulotlar mavjud emas!")
        return
    print(f"Navigating: product_ids={product_ids}, current_index={current_index}")
    if call.data == "prev_product":
        new_index = max(0, current_index - 1)
    else:
        new_index = min(total_products - 1, current_index + 1)
    await state.update_data(current_index=new_index)
    async with async_session() as session:
        product = await session.get(Product, product_ids[new_index])
        if not product:
            await call.answer("Mahsulot topilmadi!")
            return
    await show_product(call, state, bot, product, new_index, total_products)

@router.callback_query(F.data.startswith("order_"))
async def order_product_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    if is_admin(call.from_user.id):
        await call.answer("Admin sifatida buyurtma berish mumkin emas!")
        return

    product_id = int(call.data.split("_")[1])
    admin_username = os.getenv("ADMIN_USERNAME")  # .env faylda: ADMIN_USERNAME=admin_username (without @)

    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            await call.answer("Mahsulot topilmadi!")
            return
        subcategory = await session.get(SubCategory, product.sub_category_id)
        category = await session.get(Category, subcategory.category_id)

        # if product.photo:
        #     await bot.send_photo(
        #         call.message.chat.id,
        #         product.photo,
        #         caption=title,
        #         reply_markup=kb,
        #         parse_mode="HTML"
        # )
        
    # Formatlangan xabar (foydalanuvchi va admin uchun)
    message = (

        f"🛒 Buyurtma\n\n"
        f"📦 Mahsulot: {product.name}\n"
        f"💵 Narxi: {product.price}$\n"
        f"📂 Kategoriya: {category.name}\n"
        # f"📁 Subkategoriya: {subcategory.name}\n"
        f"👤 Foydalanuvchi: {call.from_user.full_name}"
    )

    # Admin bilan yozish uchun URL (xabar to'g'ri kodlanadi)
    if admin_username:
        encoded_message = urllib.parse.quote(message)  # To'g'ri URL kodlash
        url = f"https://t.me/{admin_username}?text={encoded_message}"
    else:
        await call.answer("Admin username topilmadi!", show_alert=True)
        return

    # Tugma orqali foydalanuvchini admin bilan yozishga yo‘naltiramiz
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Admin bilan yozish", url=url)],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category.id}")]
    ])

    # Foydalanuvchiga xabar va rasm yuborish (agar rasm bo'lsa)
    if product.photo:
        await bot.send_photo(
            call.message.chat.id,
            product.photo,
            caption=f"{message}\n\n✅ Quyidagi tugmani bosing va admin bilan bevosita muloqot qiling:",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await chat_cleaner.send_bot_message(
            bot,
            call.message.chat.id,
            f"{message}\n\n✅ Quyidagi tugmani bosing va admin bilan bevosita muloqot qiling:",
            reply_markup=kb
        )

    await state.clear()

@router.callback_query(F.data.startswith("product_"))
async def select_product(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    product_id = int(call.data.split("_")[1])
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            await call.answer("Mahsulot topilmadi!")
            return
        subcategory = await session.get(SubCategory, product.sub_category_id)
        category = await session.get(Category, subcategory.category_id)
    title = f"📋 {category.name} > {subcategory.name}\n\n"
    title += f"Nomi: {hbold(product.name)}\n"
    title += f"Narxi: {hbold(product.price)}$"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if is_admin(call.from_user.id):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Mahsulot qo'shish", callback_data=f"add_product_{subcategory.id}"),
            InlineKeyboardButton(text="🗑️ Mahsulotni o'chirish", callback_data=f"delete_product_{subcategory.id}"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category.id}")
        ])
    else:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="🛒 Buyurtma berish", callback_data=f"order_{product.id}"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"cat_{category.id}")
        ])
    if product.photo:
        await bot.send_photo(
            call.message.chat.id,
            product.photo,
            caption=title,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await chat_cleaner.send_bot_message(
            bot,
            call.message.chat.id,
            title,
            reply_markup=kb,
            parse_mode="HTML"
        )

class AddProductState(StatesGroup):
    WAITING_FOR_NAME = State()
    WAITING_FOR_PRICE = State()
    WAITING_FOR_PHOTO = State()

@router.callback_query(F.data.startswith("add_product_"))
async def add_product_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    subcategory_id = int(call.data.split("_")[2])
    await state.update_data(subcategory_id=subcategory_id)
    await chat_cleaner.send_bot_message(
        bot,
        call.message.chat.id,
        "Yangi mahsulot qo'shamiz!\n\nAvval mahsulot nomini yuboring:",
        delete_previous=True
    )
    await state.set_state(AddProductState.WAITING_FOR_NAME)

@router.message(AddProductState.WAITING_FOR_NAME)
async def process_product_name(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    if not message.text or len(message.text) > 100:
        await chat_cleaner.send_bot_message(
            bot,
            message.chat.id,
            "❌ Iltimos, haqiqiy mahsulot nomini kiriting (maks 100 belgi)",
            delete_previous=False
        )
        return
    await state.update_data(product_name=message.text)
    await chat_cleaner.send_bot_message(
        bot,
        message.chat.id,
        "Ajoyib! Endi mahsulot narxini yuboring (faqat raqamlar, valyuta belgisi kiritmang):",
        delete_previous=False
    )
    await state.set_state(AddProductState.WAITING_FOR_PRICE)

@router.message(AddProductState.WAITING_FOR_PRICE)
async def process_product_price(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    try:
        price = float(message.text)
        if price <= 0:
            raise ValueError("Narx musbat bo'lishi kerak")
    except ValueError:
        await chat_cleaner.send_bot_message(
            bot,
            message.chat.id,
            "❌ Iltimos, haqiqiy musbat raqamni narx sifatida kiriting",
            delete_previous=False
        )
        return
    await state.update_data(product_price=price)
    await chat_cleaner.send_bot_message(
        bot,
        message.chat.id,
        "Zo'r! Endi mahsulot rasmini yuborishingiz mumkin (yoki rasm bo'lmasa /skip ni yuboring):",
        delete_previous=False
    )
    await state.set_state(AddProductState.WAITING_FOR_PHOTO)

@router.message(AddProductState.WAITING_FOR_PHOTO, F.photo)
async def process_product_photo_with_photo(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    photo_id = message.photo[-1].file_id
    await state.update_data(product_photo=photo_id)
    await finish_product_creation(message, state, bot)

@router.message(AddProductState.WAITING_FOR_PHOTO, Command("skip"))
async def process_product_photo_without_photo(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    await state.update_data(product_photo=None)
    await finish_product_creation(message, state, bot)

@router.message(AddProductState.WAITING_FOR_PHOTO)
async def process_product_photo_invalid(message: Message, state: FSMContext, bot: Bot):
    await chat_cleaner.track_user_message(message)
    await chat_cleaner.send_bot_message(
        bot,
        message.chat.id,
        "Iltimos, rasm yuboring yoki /skip ni yuborib, rasmsiz davom eting",
        delete_previous=False
    )

async def finish_product_creation(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    subcategory_id = data.get("subcategory_id")
    name = data.get("product_name")
    price = data.get("product_price")
    photo = data.get("product_photo")
    async with async_session() as session:
        product = Product(
            name=name,
            price=price,
            photo=photo,
            sub_category_id=subcategory_id
        )
        session.add(product)
        await session.commit()
    success_message = f"""
    ✅ Mahsulot muvaffaqiyatli qo'shildi!

    Nomi: {hbold(name)}
    Narxi: {hbold(price)}$
    """
    if photo:
        await bot.send_photo(
            message.chat.id,
            photo,
            caption=success_message,
            parse_mode="HTML"
        )
    else:
        await chat_cleaner.send_bot_message(
            bot,
            message.chat.id,
            success_message,
            delete_previous=False,
            parse_mode="HTML"
        )
    await state.clear()
    await asyncio.sleep(2)
    fake_call = CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="0",
        message=message,
        data=f"sub_{subcategory_id}"
    )
    await select_subcategory(fake_call, state, bot)

@router.callback_query(F.data.startswith("delete_product_"))
async def delete_product_menu(call: CallbackQuery, state: FSMContext, bot: Bot):
    subcategory_id = int(call.data.split("_")[2])
    await state.update_data(subcategory_id=subcategory_id)
    products = await get_products(subcategory_id)
    if not products:
        await call.answer("O'chirish uchun mahsulotlar mavjud emas!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {product.name} - ${product.price}", callback_data=f"delprod_{product.id}")]
        for product in products
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"sub_{subcategory_id}")])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "O'chirish uchun mahsulotni tanlang:", reply_markup=kb)
    await state.set_state(AdminStates.DELETE_PRODUCT)

@router.callback_query(StateFilter(AdminStates.DELETE_PRODUCT), F.data.startswith("delprod_"))
async def delete_product_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    product_id = int(call.data.split("_")[1])
    await state.update_data(product_id=product_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data="confirm_delete_product")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_delete_product")]
    ])
    await chat_cleaner.send_bot_message(bot, call.message.chat.id, "Ushbu mahsulotni o'chirishga ishonchingiz komilmi?", reply_markup=kb)

@router.callback_query(F.data == "confirm_delete_product")
async def delete_product_execute(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    product_id = data.get("product_id")
    subcategory_id = data.get("subcategory_id")
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            await call.answer("Mahsulot topilmadi!")
            await state.clear()
            return
        await session.execute(delete(Product).where(Product.id == product_id))
        await session.commit()
    await call.answer(f"✅ Mahsulot '{product.name}' muvaffaqiyatli o'chirildi!")
    await state.clear()
    fake_call = CallbackQuery(
        id="0",
        from_user=call.from_user,
        chat_instance="0",
        message=call.message,
        data=f"sub_{subcategory_id}"
    )
    await select_subcategory(fake_call, state, bot)

@router.callback_query(F.data == "cancel_delete_product")
async def delete_product_cancel(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    subcategory_id = data.get("subcategory_id")
    await call.answer("O'chirish bekor qilindi")
    await state.clear()
    fake_call = CallbackQuery(
        id="0",
        from_user=call.from_user,
        chat_instance="0",
        message=call.message,
        data=f"sub_{subcategory_id}"
    )
    await select_subcategory(fake_call, state, bot)