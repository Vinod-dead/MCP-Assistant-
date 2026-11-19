"""Deterministic sample business database so the assistant has something real to query."""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

_CUSTOMERS = [
    ("Asha Textiles", "Bengaluru", "SMB"), ("Kaveri Foods", "Mysuru", "SMB"), ("Nimbus Logistics", "Hyderabad", "Enterprise"),
    ("Orchid Pharma Retail", "Chennai", "Mid-market"), ("Brahma Builders", "Pune", "Mid-market"),
    ("Saffron Stays", "Goa", "SMB"), ("Vega Auto Parts", "Coimbatore", "Mid-market"), ("Lotus Learning", "Mumbai", "SMB"),
    ("Indigo Agritech", "Nagpur", "Enterprise"), ("Maple Mobility", "Gurugram", "Enterprise"),
    ("Tulsi Wellness", "Kochi", "SMB"), ("Zenith Print Works", "Ahmedabad", "SMB"),
]
_TICKETS = [
    "Invoice PDF not downloading", "Wrong GSTIN on invoice", "Request for credit note", "Payment not reflecting",
    "Need duplicate invoice", "Change billing address", "Refund request", "API key rotation help",
]


def ensure_demo_data(data_dir: Path) -> Path:
    db_path = data_dir / "business.db"
    if db_path.exists():
        return db_path
    data_dir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT, segment TEXT, gstin TEXT);
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), invoice_no TEXT UNIQUE,
            issue_date TEXT, due_date TEXT, amount REAL, gst_amount REAL, status TEXT CHECK (status IN ('paid','pending','overdue'))
        );
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), subject TEXT,
            priority TEXT, status TEXT, opened_on TEXT
        );
        """
    )
    for i, (name, city, seg) in enumerate(_CUSTOMERS, start=1):
        gstin = f"{rnd.choice([29, 27, 33, 36, 24])}{''.join(rnd.choices('ABCDEFGHJKLMNPRSTUVWXYZ', k=5))}{rnd.randint(1000, 9999)}{rnd.choice('ABCDEFGH')}1Z{rnd.randint(1, 9)}"
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?)", (i, name, city, seg, gstin))
    today = date(2026, 11, 17)
    for n in range(1, 61):
        cust = rnd.randint(1, len(_CUSTOMERS))
        issued = today - timedelta(days=rnd.randint(1, 150))
        due = issued + timedelta(days=30)
        amount = round(rnd.uniform(8_000, 450_000), 2)
        roll = rnd.random()
        status = "paid" if roll < 0.55 else ("pending" if due >= today else "overdue")
        if status == "pending" and due < today:
            status = "overdue"
        con.execute(
            "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?)",
            (n, cust, f"INV-2026-{n:04d}", issued.isoformat(), due.isoformat(), amount, round(amount * 0.18, 2), status),
        )
    for n in range(1, 16):
        con.execute(
            "INSERT INTO tickets VALUES (?,?,?,?,?,?)",
            (n, rnd.randint(1, len(_CUSTOMERS)), rnd.choice(_TICKETS), rnd.choice(["low", "medium", "high"]),
             rnd.choice(["open", "open", "closed"]), (today - timedelta(days=rnd.randint(0, 40))).isoformat()),
        )
    con.commit()
    con.close()
    return db_path
