"""SQLite persistence layer for TRINETRA VoiceOps AI.

SQLite keeps the demo zero-config. For production, swap the functions in this
module for Firestore (the rest of the code only talks to these helpers).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent / "trinetra_enterprise.db"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per operation (safe with FastAPI's threadpool)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            customer_id TEXT,
            customer_name TEXT,
            customer_phone TEXT,
            equipment TEXT,
            warranty_active INTEGER,
            status TEXT,
            summary TEXT,
            updated_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS inventory (
            sku TEXT PRIMARY KEY,
            part_name TEXT,
            unit_price_inr REAL,
            van_stock INTEGER,
            reorder_triggered INTEGER
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS workflows (
            trace_id TEXT PRIMARY KEY,
            ticket_id TEXT,
            customer_id TEXT,
            transcript TEXT,
            structured_json TEXT,
            approval_status TEXT,
            invoice_id TEXT,
            parts_cost_inr REAL,
            billable_total_inr REAL,
            audit_hash TEXT,
            logs_json TEXT,
            created_at TEXT
        )""")
        now = utc_now()
        conn.executemany(
            "INSERT OR IGNORE INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("TKT-2026-8841", "102", "Sharma Enterprises", "+91-98220-44102",
                 "Daikin 2-Ton Inverter Split AC", 1, "IN_PROGRESS",
                 "Technician Ravi Kumar dispatched for cooling failure.", now),
                ("TKT-2026-8842", "105", "Apex Tech Park", "+91-98220-55105",
                 "Carrier 5-Ton Ductable AC", 0, "IN_PROGRESS",
                 "Routine capacitor & contactor check.", now),
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO inventory VALUES (?,?,?,?,?)",
            [
                ("DKN-CMP-20T", "Rotary Compressor (2-Ton Inverter)", 14500.0, 1, 0),
                ("DKN-CAP-45MFD", "Dual Run Capacitor 45+5 MFD", 650.0, 6, 0),
            ],
        )


def reset_demo_db() -> None:
    DB_PATH.unlink(missing_ok=True)
    init_db()


def save_workflow(row: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO workflows (trace_id, ticket_id, customer_id, transcript,
               structured_json, approval_status, invoice_id, parts_cost_inr,
               billable_total_inr, audit_hash, logs_json, created_at)
               VALUES (:trace_id, :ticket_id, :customer_id, :transcript,
               :structured_json, :approval_status, :invoice_id, :parts_cost_inr,
               :billable_total_inr, :audit_hash, :logs_json, :created_at)""",
            row,
        )


def get_workflow(trace_id: str) -> Optional[dict]:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM workflows WHERE trace_id = ?", (trace_id,)).fetchone()
        return dict(r) if r else None


def update_workflow_approval(trace_id: str, status: str, logs: list) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE workflows SET approval_status = ?, logs_json = ? WHERE trace_id = ?",
            (status, json.dumps(logs), trace_id),
        )


def fetch_dashboard() -> dict:
    with get_conn() as conn:
        return {
            "tickets": [dict(r) for r in conn.execute("SELECT * FROM tickets")],
            "inventory": [dict(r) for r in conn.execute("SELECT * FROM inventory")],
            "workflows": [dict(r) for r in conn.execute(
                "SELECT * FROM workflows ORDER BY created_at DESC")],
        }
