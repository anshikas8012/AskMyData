
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "sales.db"

sample_data = [
    ("Laptop", "Electronics", 75000, 2),
    ("Phone", "Electronics", 30000, 3),
    ("Headphones", "Accessories", 2000, 5),
    ("Laptop", "Electronics", 82000, 2),
    ("Phone", "Electronics", 35000, 4),
    ("Keyboard", "Accessories", 1500, 6),
    ("Monitor", "Electronics", 18000, 2),
    ("Headphones", "Accessories", 2500, 4),
]

with sqlite3.connect(DB_PATH) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT NOT NULL,
            category TEXT NOT NULL,
            sales REAL NOT NULL,
            quantity INTEGER NOT NULL
        )
    """)

    existing_count = conn.execute(
        "SELECT COUNT(*) FROM sales"
    ).fetchone()[0]

    if existing_count == 0:
        conn.executemany("""
            INSERT INTO sales (product, category, sales, quantity)
            VALUES (?, ?, ?, ?)
        """, sample_data)

        print("Sample sales data added successfully!")
    else:
        print("Sales data already exists. No new records added.")

print(f"Database location: {DB_PATH}")