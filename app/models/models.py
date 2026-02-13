from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, Time, ForeignKey, func, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from config import *

engine = create_engine(DATABASE_URL)
base = declarative_base()

class User(base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=False)
    first_name = Column(String)
    
class Store(base):
    __tablename__ = 'stores'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    address = Column(String(255), nullable=False)
    opening_time = Column(Time, nullable=False)
    closing_time = Column(Time, nullable=False)

    @property
    def working_hours(self) -> str:
        open_str = self.opening_time.strftime('%H:%M') if self.opening_time else "--:--"
        close_str = self.closing_time.strftime('%H:%M') if self.closing_time else "--:--"
        return f"{open_str} - {close_str}"

class Order(base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False)
    store_id = Column(Integer, nullable=False)
    items = Column(JSONB, nullable=False)
    total_price = Column(Numeric)
    # CREATED; IN_PROGRESS; READY; COMPLETED; CANCELLED;
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)

class Category(base):
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    price = Column(Numeric)
    store_id = Column(Integer)

class Staff(base):
    __tablename__ = 'staff'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    store_id = Column(Integer, nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, nullable=False, default='inactive')

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)