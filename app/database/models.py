"""SQLAlchemy ORM models mirroring the star schema."""

from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, Date,
    SmallInteger, ForeignKey, CheckConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ─── Dimension: Date ─────────────────────────────────────────
class DimDate(Base):
    __tablename__ = "dim_date"

    date_id = Column(Integer, primary_key=True, autoincrement=True)
    full_date = Column(Date, nullable=False, unique=True)
    day_of_month = Column(SmallInteger, nullable=False)
    day_of_week = Column(SmallInteger, nullable=False)
    day_name = Column(String(10), nullable=False)
    week_of_year = Column(SmallInteger, nullable=False)
    month = Column(SmallInteger, nullable=False)
    month_name = Column(String(10), nullable=False)
    quarter = Column(SmallInteger, nullable=False)
    year = Column(SmallInteger, nullable=False)
    is_weekend = Column(Boolean, nullable=False, default=False)
    fiscal_quarter = Column(SmallInteger, nullable=False)

    sales = relationship("FactSales", back_populates="date")


# ─── Dimension: Region ───────────────────────────────────────
class DimRegion(Base):
    __tablename__ = "dim_region"

    region_id = Column(Integer, primary_key=True, autoincrement=True)
    region_name = Column(String(50), nullable=False)
    country = Column(String(60), nullable=False)
    state = Column(String(60), nullable=False)
    city = Column(String(80), nullable=False)
    postal_code = Column(String(15), nullable=False)

    customers = relationship("DimCustomer", back_populates="region")
    sales = relationship("FactSales", back_populates="region")


# ─── Dimension: Customer ─────────────────────────────────────
class DimCustomer(Base):
    __tablename__ = "dim_customer"

    customer_id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(120), nullable=False, unique=True)
    segment = Column(String(30), nullable=False)
    loyalty_tier = Column(String(20), nullable=False, default="Bronze")
    join_date = Column(Date, nullable=False)
    region_id = Column(Integer, ForeignKey("dim_region.region_id"), nullable=False)

    region = relationship("DimRegion", back_populates="customers")
    sales = relationship("FactSales", back_populates="customer")

    __table_args__ = (
        CheckConstraint(
            "segment IN ('Consumer', 'Corporate', 'Home Office', 'Small Business')",
            name="chk_customer_segment",
        ),
        CheckConstraint(
            "loyalty_tier IN ('Bronze', 'Silver', 'Gold', 'Platinum')",
            name="chk_customer_loyalty",
        ),
    )


# ─── Dimension: Product ──────────────────────────────────────
class DimProduct(Base):
    __tablename__ = "dim_product"

    product_id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(150), nullable=False)
    category = Column(String(50), nullable=False)
    sub_category = Column(String(50), nullable=False)
    brand = Column(String(60), nullable=False)
    unit_cost = Column(Numeric(10, 2), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)

    sales = relationship("FactSales", back_populates="product")

    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="chk_product_cost"),
        CheckConstraint("unit_price >= 0", name="chk_product_price"),
    )


# ─── Fact: Sales ─────────────────────────────────────────────
class FactSales(Base):
    __tablename__ = "fact_sales"

    sale_id = Column(Integer, primary_key=True, autoincrement=True)
    order_number = Column(String(20), nullable=False)
    customer_id = Column(Integer, ForeignKey("dim_customer.customer_id"), nullable=False)
    product_id = Column(Integer, ForeignKey("dim_product.product_id"), nullable=False)
    date_id = Column(Integer, ForeignKey("dim_date.date_id"), nullable=False)
    region_id = Column(Integer, ForeignKey("dim_region.region_id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    discount = Column(Numeric(5, 2), nullable=False, default=0.00)
    total_amount = Column(Numeric(12, 2), nullable=False)
    cost = Column(Numeric(12, 2), nullable=False)
    profit = Column(Numeric(12, 2), nullable=False)
    ship_mode = Column(String(30), nullable=False)

    customer = relationship("DimCustomer", back_populates="sales")
    product = relationship("DimProduct", back_populates="sales")
    date = relationship("DimDate", back_populates="sales")
    region = relationship("DimRegion", back_populates="sales")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_sales_quantity"),
        CheckConstraint("unit_price >= 0", name="chk_sales_price"),
        CheckConstraint(
            "discount >= 0 AND discount <= 1", name="chk_sales_discount"
        ),
        CheckConstraint(
            "ship_mode IN ('Standard', 'Express', 'Same Day', 'Economy')",
            name="chk_sales_shipmode",
        ),
    )
