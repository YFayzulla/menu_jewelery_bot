from sqlalchemy import Column, Integer, String, Float, ForeignKey, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import relationship, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///db.sqlite3")
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

# Models
class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    subcategories = relationship("SubCategory", back_populates="category", cascade="all, delete")

class SubCategory(Base):
    __tablename__ = 'sub_categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    category = relationship("Category", back_populates="subcategories")
    products = relationship("Product", back_populates="sub_category", cascade="all, delete")

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    photo = Column(String)
    sub_category_id = Column(Integer, ForeignKey('sub_categories.id'), nullable=False)
    sub_category = relationship("SubCategory", back_populates="products")

# Helper functions
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
        result = await session.execute(select(Product).where(Product.sub_category_id == subcategory_id))
        return result.scalars().all()
    
async def create_category(name: str):
    if not name or len(name) > 50:
        raise ValueError("Category name must be 1-50 characters")
        
    existing = await get_category_by_name(name)
    if existing:
        raise ValueError("Category already exists")
    
    async with async_session() as session:
        category = Category(name=name)
        session.add(category)
        await session.commit()
        return category

async def get_category_by_name(name: str):
    async with async_session() as session:
        result = await session.execute(select(Category).where(Category.name == name))
        return result.scalar_one_or_none()