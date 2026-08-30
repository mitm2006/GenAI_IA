"""
Synthetic data generator — populates the star schema with realistic data.

Generates:
  - 1,095 date rows (2023-01-01 → 2025-12-31)
  - 60 regions (Indian cities across 4 regions)
  - 500 customers across 4 segments
  - 120 products across 6 categories
  - 50,000+ fact_sales transactions with seasonal trends

Works with both PostgreSQL and SQLite.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import text, inspect
from loguru import logger

from app.database.connection import get_rw_engine
from app.database.models import Base
from app.config import settings

fake = Faker("en_IN")  # Indian locale for realistic names/addresses
Faker.seed(42)
random.seed(42)

# ─── Product Catalog ──────────────────────────────────────────
PRODUCT_CATALOG = {
    "Technology": {
        "Laptops": [
            ("Dell Inspiron 15", "Dell", 35000, 52999),
            ("HP Pavilion x360", "HP", 38000, 58999),
            ("Lenovo IdeaPad Slim 3", "Lenovo", 28000, 42999),
            ("ASUS VivoBook 15", "ASUS", 30000, 46999),
            ("Acer Aspire 5", "Acer", 26000, 39999),
        ],
        "Phones": [
            ("Samsung Galaxy S24", "Samsung", 42000, 74999),
            ("iPhone 15", "Apple", 55000, 79999),
            ("OnePlus 12", "OnePlus", 35000, 64999),
            ("Google Pixel 8", "Google", 32000, 52999),
            ("Xiaomi 14", "Xiaomi", 22000, 39999),
        ],
        "Accessories": [
            ("Logitech MX Master 3S", "Logitech", 3500, 8999),
            ("Sony WH-1000XM5", "Sony", 12000, 29999),
            ("Samsung T7 SSD 1TB", "Samsung", 4500, 9999),
            ("Apple AirPods Pro", "Apple", 12000, 24999),
            ("Boat Airdopes 141", "Boat", 500, 1299),
        ],
    },
    "Furniture": {
        "Chairs": [
            ("ErgoFlex Office Chair", "UrbanLadder", 8000, 18999),
            ("IKEA Markus Chair", "IKEA", 12000, 24999),
            ("Nilkamal Executive Chair", "Nilkamal", 4000, 8999),
            ("GreenSoul Monster Chair", "GreenSoul", 10000, 22999),
        ],
        "Desks": [
            ("Standing Desk Pro", "FlexiSpot", 15000, 32999),
            ("L-Shaped Gaming Desk", "Featherlite", 12000, 26999),
            ("Classic Writing Desk", "Godrej", 6000, 14999),
            ("Compact Study Table", "Amazon Basics", 3000, 7999),
        ],
        "Storage": [
            ("Modular Bookshelf", "UrbanLadder", 5000, 12999),
            ("Filing Cabinet 3-Drawer", "Godrej", 4000, 9999),
            ("Wall Mounted Shelf Set", "IKEA", 2000, 5999),
        ],
    },
    "Office Supplies": {
        "Paper": [
            ("JK Copier A4 Paper 500 Sheets", "JK", 150, 350),
            ("Post-it Super Sticky Notes", "3M", 120, 299),
            ("Classmate Spiral Notebook", "ITC", 60, 150),
        ],
        "Writing": [
            ("Parker Jotter Pen Set", "Parker", 400, 999),
            ("Cello Butterflow Pens (10)", "Cello", 50, 120),
            ("Staedtler Pencil Set", "Staedtler", 80, 199),
        ],
        "Organizers": [
            ("Desk Organizer Premium", "Solo", 300, 799),
            ("Magazine File Holder (5)", "Amazon Basics", 250, 599),
            ("Label Maker P-Touch", "Brother", 1500, 3499),
        ],
    },
    "Appliances": {
        "Kitchen": [
            ("Instant Pot Duo 7-in-1", "Instant Pot", 4000, 8999),
            ("Philips Air Fryer HD9200", "Philips", 5500, 9999),
            ("Bajaj Mixer Grinder 750W", "Bajaj", 2000, 4299),
            ("Kent RO Water Purifier", "Kent", 8000, 18999),
        ],
        "Home": [
            ("Dyson V12 Vacuum", "Dyson", 20000, 42999),
            ("LG Inverter AC 1.5 Ton", "LG", 28000, 45999),
            ("Samsung Washing Machine 7kg", "Samsung", 15000, 28999),
        ],
    },
    "Clothing": {
        "Men": [
            ("Peter England Formal Shirt", "Peter England", 400, 1299),
            ("Levis 511 Slim Fit Jeans", "Levis", 1200, 3299),
            ("Nike Air Max Shoes", "Nike", 3000, 8999),
            ("US Polo T-Shirt", "US Polo", 350, 999),
        ],
        "Women": [
            ("Global Desi Kurti", "Global Desi", 600, 1799),
            ("Biba Cotton Palazzo", "Biba", 500, 1299),
            ("Fastrack Analog Watch", "Fastrack", 800, 2499),
            ("Lavie Handbag", "Lavie", 1000, 2999),
        ],
    },
    "Sports": {
        "Fitness": [
            ("Powermax Treadmill", "Powermax", 18000, 35999),
            ("Cockatoo Dumbbell Set 20kg", "Cockatoo", 2000, 4999),
            ("Yoga Mat Premium 6mm", "Boldfit", 300, 899),
        ],
        "Outdoor": [
            ("Yonex Badminton Racket", "Yonex", 1500, 3999),
            ("Nivia Football Storm", "Nivia", 400, 999),
            ("Cosco Cricket Bat Kashmir", "Cosco", 800, 2499),
        ],
    },
}

# ─── Indian Regions ───────────────────────────────────────────
REGIONS = {
    "North": {
        "India": {
            "Delhi": ["New Delhi", "Noida", "Gurgaon", "Faridabad"],
            "Uttar Pradesh": ["Lucknow", "Kanpur", "Agra", "Varanasi"],
            "Punjab": ["Chandigarh", "Ludhiana", "Amritsar"],
            "Rajasthan": ["Jaipur", "Udaipur", "Jodhpur"],
        }
    },
    "South": {
        "India": {
            "Karnataka": ["Bangalore", "Mysore", "Mangalore"],
            "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai"],
            "Kerala": ["Kochi", "Thiruvananthapuram"],
            "Telangana": ["Hyderabad", "Warangal"],
        }
    },
    "East": {
        "India": {
            "West Bengal": ["Kolkata", "Howrah", "Durgapur"],
            "Odisha": ["Bhubaneswar", "Cuttack"],
            "Bihar": ["Patna", "Gaya"],
            "Assam": ["Guwahati"],
        }
    },
    "West": {
        "India": {
            "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Thane"],
            "Gujarat": ["Ahmedabad", "Surat", "Vadodara"],
            "Goa": ["Panaji"],
        }
    },
}

SEGMENTS = ["Consumer", "Corporate", "Home Office", "Small Business"]
LOYALTY_TIERS = ["Bronze", "Silver", "Gold", "Platinum"]
SHIP_MODES = ["Standard", "Express", "Same Day", "Economy"]


def _generate_dates():
    """Generate 3 years of date dimension rows (2023–2025)."""
    rows = []
    start = date(2023, 1, 1)
    end = date(2025, 12, 31)
    current = start
    while current <= end:
        fiscal_q = ((current.month - 1 + 3) // 3 - 1) % 4 + 1
        rows.append({
            "full_date": current,
            "day_of_month": current.day,
            "day_of_week": current.weekday(),
            "day_name": current.strftime("%A"),
            "week_of_year": int(current.strftime("%W")),
            "month": current.month,
            "month_name": current.strftime("%B"),
            "quarter": (current.month - 1) // 3 + 1,
            "year": current.year,
            "is_weekend": current.weekday() >= 5,
            "fiscal_quarter": fiscal_q,
        })
        current += timedelta(days=1)
    return rows


def _generate_regions():
    """Generate region dimension from predefined Indian regions."""
    rows = []
    for region_name, countries in REGIONS.items():
        for country, states in countries.items():
            for state, cities in states.items():
                for city in cities:
                    rows.append({
                        "region_name": region_name,
                        "country": country,
                        "state": state,
                        "city": city,
                        "postal_code": str(fake.postcode()),
                    })
    return rows


def _generate_customers(region_count: int):
    """Generate 500 realistic customer records."""
    rows = []
    used_emails = set()
    for _ in range(500):
        first = fake.first_name()
        last = fake.last_name()
        base_email = f"{first.lower()}.{last.lower()}@{fake.free_email_domain()}"
        email = base_email
        counter = 1
        while email in used_emails:
            email = f"{first.lower()}.{last.lower()}{counter}@{fake.free_email_domain()}"
            counter += 1
        used_emails.add(email)

        segment = random.choice(SEGMENTS)
        tier = random.choices(LOYALTY_TIERS, weights=[50, 30, 15, 5], k=1)[0]
        join_date = fake.date_between(
            start_date=date(2020, 1, 1), end_date=date(2024, 12, 31)
        )
        rows.append({
            "first_name": first,
            "last_name": last,
            "email": email,
            "segment": segment,
            "loyalty_tier": tier,
            "join_date": join_date,
            "region_id": random.randint(1, region_count),
        })
    return rows


def _generate_products():
    """Flatten the product catalog into product dimension rows."""
    rows = []
    for category, sub_cats in PRODUCT_CATALOG.items():
        for sub_category, products in sub_cats.items():
            for name, brand, cost, price in products:
                rows.append({
                    "product_name": name,
                    "category": category,
                    "sub_category": sub_category,
                    "brand": brand,
                    "unit_cost": float(cost),
                    "unit_price": float(price),
                })
    return rows


def _seasonal_multiplier(month: int) -> float:
    """Simulate seasonal sales patterns."""
    seasonal = {
        1: 0.7, 2: 0.65, 3: 0.85, 4: 0.9,
        5: 0.95, 6: 0.9, 7: 1.1, 8: 1.15,
        9: 1.0, 10: 1.4, 11: 1.5, 12: 1.3,
    }
    return seasonal.get(month, 1.0)


def _generate_sales(
    date_rows: list, customer_count: int, product_count: int, region_count: int
):
    """Generate 50,000+ fact_sales rows with realistic patterns."""
    rows = []
    order_counter = 10000
    date_lookup = {r["full_date"]: idx + 1 for idx, r in enumerate(date_rows)}
    target_sales = 55000
    sales_per_day = target_sales / len(date_rows)

    for idx, dr in enumerate(date_rows):
        full_date = dr["full_date"]
        month = dr["month"]
        is_weekend = dr["is_weekend"]

        multiplier = _seasonal_multiplier(month)
        if is_weekend:
            multiplier *= 1.15
        day_sales = max(1, int(sales_per_day * multiplier + random.gauss(0, 3)))

        for _ in range(day_sales):
            order_counter += 1
            customer_id = random.randint(1, customer_count)
            product_id = random.randint(1, product_count)
            region_id = random.randint(1, region_count)
            date_id = date_lookup[full_date]

            quantity = random.choices(
                [1, 2, 3, 4, 5, 6, 8, 10],
                weights=[40, 25, 15, 8, 5, 3, 2, 2], k=1
            )[0]

            discount = random.choices(
                [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
                weights=[50, 15, 12, 8, 7, 5, 3], k=1
            )[0]

            ship_mode = random.choices(SHIP_MODES, weights=[50, 25, 10, 15], k=1)[0]

            unit_price = float(random.randint(100, 80000))
            unit_cost = unit_price * 0.55 + random.randint(0, 500)
            total = round(unit_price * quantity * (1 - discount), 2)
            cost = round(unit_cost * quantity, 2)
            profit = round(total - cost, 2)

            rows.append({
                "order_number": f"ORD-{order_counter}",
                "customer_id": customer_id,
                "product_id": product_id,
                "date_id": date_id,
                "region_id": region_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount": discount,
                "total_amount": total,
                "cost": cost,
                "profit": profit,
                "ship_mode": ship_mode,
            })

    return rows


def _create_tables_sqlite(engine):
    """Create tables using SQLAlchemy ORM models (works for both SQLite and PG)."""
    Base.metadata.create_all(engine)
    logger.info("📋 Created tables via ORM models")


def seed_database():
    """
    Populate the entire star schema with synthetic data.
    Idempotent — checks if data already exists and skips seeding if so.
    """
    engine = get_rw_engine()

    # Create tables via ORM (SQLite) or assume they exist (PG with DDL)
    is_sqlite = str(engine.url).startswith("sqlite")
    if is_sqlite:
        _create_tables_sqlite(engine)

    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT COUNT(*) FROM dim_date"))
            count = result.scalar()
            if count and count > 0:
                logger.info(f"Database already seeded ({count} dates found). Skipping.")
                return
        except Exception:
            # Table might not exist yet for PG without DDL
            if is_sqlite:
                _create_tables_sqlite(engine)
            else:
                raise

    logger.info("🌱 Seeding database with synthetic data...")

    # 1. Dates
    date_rows = _generate_dates()
    logger.info(f"  📅 Inserting {len(date_rows)} date records...")
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO dim_date
                (full_date, day_of_month, day_of_week, day_name,
                 week_of_year, month, month_name, quarter, year,
                 is_weekend, fiscal_quarter)
                VALUES
                (:full_date, :day_of_month, :day_of_week, :day_name,
                 :week_of_year, :month, :month_name, :quarter, :year,
                 :is_weekend, :fiscal_quarter)
            """),
            date_rows,
        )
        conn.commit()

    # 2. Regions
    region_rows = _generate_regions()
    logger.info(f"  🌍 Inserting {len(region_rows)} region records...")
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO dim_region (region_name, country, state, city, postal_code)
                VALUES (:region_name, :country, :state, :city, :postal_code)
            """),
            region_rows,
        )
        conn.commit()

    # 3. Customers
    customer_rows = _generate_customers(len(region_rows))
    logger.info(f"  👥 Inserting {len(customer_rows)} customer records...")
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO dim_customer
                (first_name, last_name, email, segment, loyalty_tier, join_date, region_id)
                VALUES
                (:first_name, :last_name, :email, :segment, :loyalty_tier, :join_date, :region_id)
            """),
            customer_rows,
        )
        conn.commit()

    # 4. Products
    product_rows = _generate_products()
    logger.info(f"  📦 Inserting {len(product_rows)} product records...")
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO dim_product
                (product_name, category, sub_category, brand, unit_cost, unit_price)
                VALUES
                (:product_name, :category, :sub_category, :brand, :unit_cost, :unit_price)
            """),
            product_rows,
        )
        conn.commit()

    # 5. Sales
    sales_rows = _generate_sales(
        date_rows, len(customer_rows), len(product_rows), len(region_rows)
    )
    logger.info(f"  💰 Inserting {len(sales_rows)} sales records (this may take a moment)...")

    batch_size = 5000
    with engine.connect() as conn:
        for i in range(0, len(sales_rows), batch_size):
            batch = sales_rows[i : i + batch_size]
            conn.execute(
                text("""
                    INSERT INTO fact_sales
                    (order_number, customer_id, product_id, date_id, region_id,
                     quantity, unit_price, discount, total_amount, cost, profit, ship_mode)
                    VALUES
                    (:order_number, :customer_id, :product_id, :date_id, :region_id,
                     :quantity, :unit_price, :discount, :total_amount, :cost, :profit, :ship_mode)
                """),
                batch,
            )
            conn.commit()
            logger.info(f"    Batch {i // batch_size + 1}: {min(i + batch_size, len(sales_rows))}/{len(sales_rows)}")

    logger.success(f"✅ Seeding complete! {len(sales_rows)} sales records created.")


if __name__ == "__main__":
    seed_database()
