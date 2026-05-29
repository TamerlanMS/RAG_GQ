from sqlalchemy import Column, Integer, String
from src.db.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, index=True, nullable=True)  # из JSON "id"
    brend = Column(String, nullable=True)
    articul = Column(String, nullable=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    quantity = Column(String, nullable=True)   # храним как строку
    price = Column(String, nullable=False)     # храним как пришло (строкой)
    comment = Column(String, nullable=True)
