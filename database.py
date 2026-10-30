import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")

INIT_SQL = """
CREATE TABLE IF NOT EXISTS brands (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    brand_id INTEGER REFERENCES brands(id),
    input_channel TEXT,
    date DATE,
    invoice_no TEXT,
    vendor TEXT,
    total NUMERIC(12,2),
    tax NUMERIC(12,2),
    currency TEXT DEFAULT 'HKD',
    category TEXT,
    sub_category TEXT,
    confidence TEXT,
    prompt_version TEXT DEFAULT 'v1',
    raw_json JSONB,
    drive_file_id TEXT,
    source_file TEXT,
    notes TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    item_name TEXT,
    qty NUMERIC(10,2),
    unit_price NUMERIC(12,2),
    amount NUMERIC(12,2),
    sub_category TEXT
);

CREATE TABLE IF NOT EXISTS settlements (
    id SERIAL PRIMARY KEY,
    brand_id INTEGER REFERENCES brands(id),
    platform TEXT,
    period_start DATE,
    period_end DATE,
    gross NUMERIC(12,2),
    commission NUMERIC(12,2),
    payout NUMERIC(12,2),
    orders_count INTEGER,
    delivery_fee NUMERIC(12,2),
    packaging_fee NUMERIC(12,2),
    source_file TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS manual_entries (
    id SERIAL PRIMARY KEY,
    brand_id INTEGER REFERENCES brands(id),
    date DATE,
    description TEXT,
    amount NUMERIC(12,2),
    category TEXT,
    entry_type TEXT DEFAULT 'expense',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    job_type TEXT,
    status TEXT DEFAULT 'pending',
    payload JSONB,
    result JSONB,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

INSERT INTO brands (code, name) VALUES
    ('sevens', 'SEVENS'),
    ('kuro_kare', 'Kuro Kare'),
    ('unassigned', 'Unassigned')
ON CONFLICT (code) DO NOTHING;
"""

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(INIT_SQL)

def save_invoice(data: dict) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO invoices (
                    brand_id, input_channel, date, invoice_no, vendor, total,
                    tax, currency, category, sub_category, confidence,
                    prompt_version, raw_json, drive_file_id, source_file, notes, status
                ) VALUES (
                    (SELECT id FROM brands WHERE code = %s),
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id
            """, (
                data.get("brand", "unassigned"),
                data.get("input_channel", ""),
                data.get("date"),
                data.get("invoice_no"),
                data.get("vendor"),
                data.get("total"),
                data.get("tax"),
                data.get("currency", "HKD"),
                data.get("category"),
                data.get("sub_category"),
                data.get("confidence"),
                data.get("prompt_version", "v1"),
                Json(data.get("raw_json")) if data.get("raw_json") else None,
                data.get("drive_file_id"),
                data.get("source_file"),
                data.get("notes", ""),
                data.get("status", "pending")
            ))
            invoice_id = cur.fetchone()[0]
            for item in data.get("items", []):
                cur.execute("""
                    INSERT INTO invoice_items (
                        invoice_id, item_name, qty, unit_price, amount, sub_category
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    invoice_id,
                    item.get("item_name"),
                    item.get("qty"),
                    item.get("unit_price"),
                    item.get("amount"),
                    item.get("sub_category")
                ))
            return invoice_id

def get_invoice(invoice_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
            return cur.fetchone()

def update_invoice_status(invoice_id: int, status: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE invoices SET status = %s, updated_at = NOW() WHERE id = %s
            """, (status, invoice_id))

def list_invoices(brand: str = None, status: str = None, limit: int = 100):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = []
            params = []
            if brand:
                where.append("b.code = %s")
                params.append(brand)
            if status:
                where.append("i.status = %s")
                params.append(status)
            sql = """
                SELECT i.*, b.code as brand_code, b.name as brand_name
                FROM invoices i
                JOIN brands b ON i.brand_id = b.id
            """
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY i.created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            return cur.fetchall()

def enqueue_job(job_type: str, payload: dict) -> int:
    import json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jobs (job_type, payload) VALUES (%s, %s) RETURNING id
            """, (job_type, json.dumps(payload)))
            return cur.fetchone()[0]
