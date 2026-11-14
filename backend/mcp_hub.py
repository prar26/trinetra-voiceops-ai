"""Enterprise connectors (CRM, ERP/inventory, billing).

In the prototype these are in-process functions over SQLite. Each method maps
1:1 to an MCP tool, so a real Salesforce / SAP / Zoho MCP server can replace
the body without touching the agents.
"""
import uuid
from typing import Optional

from database import get_conn, utc_now

LABOR_CHARGE_INR = 1416.0  # flat demo labor charge incl. GST


class EnterpriseMCPHub:
    # ----- CRM (MCP-Salesforce) -------------------------------------------
    @staticmethod
    def crm_get_customer_ticket(customer_id: str) -> dict:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE customer_id = ?", (customer_id,)
            ).fetchone()
        if row:
            return dict(row)
        # Unknown customer: synthesise a ticket so the demo never dead-ends.
        return {
            "ticket_id": f"TKT-2026-{customer_id}",
            "customer_id": customer_id,
            "customer_name": f"Enterprise Client #{customer_id}",
            "customer_phone": "+91-98000-00102",
            "equipment": "Commercial HVAC Split Unit",
            "warranty_active": 1,
            "status": "IN_PROGRESS",
        }

    @staticmethod
    def crm_update_ticket(ticket_id: str, summary: str, status: Optional[str] = None) -> None:
        with get_conn() as conn:
            if status:
                conn.execute(
                    "UPDATE tickets SET summary=?, status=?, updated_at=? WHERE ticket_id=?",
                    (summary, status, utc_now(), ticket_id),
                )
            else:
                conn.execute(
                    "UPDATE tickets SET summary=?, updated_at=? WHERE ticket_id=?",
                    (summary, utc_now(), ticket_id),
                )

    # ----- ERP / inventory (MCP-SAP) --------------------------------------
    @staticmethod
    def erp_deduct_inventory(sku: str, quantity: int) -> dict:
        quantity = max(1, int(quantity))
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM inventory WHERE sku = ?", (sku,)).fetchone()
            if not row:
                return {"sku": sku, "found": False, "unit_price_inr": 0.0,
                        "prev_stock": 0, "new_stock": 0, "reorder": False}
            prev = row["van_stock"]
            new = max(0, prev - quantity)
            reorder = 1 if new == 0 else 0
            conn.execute(
                "UPDATE inventory SET van_stock=?, reorder_triggered=? WHERE sku=?",
                (new, reorder, sku),
            )
        return {"sku": sku, "part_name": row["part_name"], "found": True,
                "unit_price_inr": row["unit_price_inr"], "prev_stock": prev,
                "new_stock": new, "reorder": bool(reorder)}

    # ----- Billing (MCP-Zoho / Razorpay) ----------------------------------
    @staticmethod
    def billing_create_invoice(warranty_active: bool, parts_cost_inr: float) -> dict:
        total = LABOR_CHARGE_INR if warranty_active else parts_cost_inr + LABOR_CHARGE_INR
        return {"invoice_id": f"INV-2026-{uuid.uuid4().hex[:4].upper()}",
                "billable_total_inr": total}
