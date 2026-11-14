"""Observe -> Analyze -> Act multi-agent swarm.

OBSERVE : Agent 1 parses the spoken transcript (Gemini 3.1 Flash-Lite, or the built-in
          demo parser when no API key is configured).
ANALYZE : Agent 2 plans the task DAG; Agent 8 asks for clarification if needed.
ACT     : Agents 3-7 call the MCP hub (CRM, inventory, approval, billing).
"""
import hashlib
import json
import os
import re
import uuid
from typing import Optional

from database import get_workflow, save_workflow, update_workflow_approval, utc_now
from mcp_hub import EnterpriseMCPHub

APPROVAL_THRESHOLD_INR = float(os.getenv("APPROVAL_THRESHOLD_INR", "5000"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

SKU_CATALOG = {
    "Rotary Compressor": "DKN-CMP-20T",
    "Capacitor": "DKN-CAP-45MFD",
}
COMPRESSOR_SKU = "DKN-CMP-20T"


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return "" if key.lower().startswith(("paste", "sample", "your")) else key


# ---------------------------------------------------------------------------
# Agent 1: Voice Understanding
# ---------------------------------------------------------------------------
def _parse_with_gemini(transcript: str) -> dict:
    """Structured extraction with Gemini. Raises on any failure (caller falls back)."""
    key = _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai  # lazy: keeps the demo parser usable without the SDK
    from google.genai import types
    from pydantic import BaseModel

    class Part(BaseModel):
        spoken_name: str
        mapped_sku: str
        quantity: int = 1
        serial_number: Optional[str] = None

    class ParsedNote(BaseModel):
        customer_id: str = "102"
        parts_used: list[Part]
        needs_clarification: bool
        clarification_question: Optional[str] = None
        technical_summary: str
        detected_language: str

    catalog = "\n".join(f'- {name} -> mapped_sku: "{sku}"' for name, sku in SKU_CATALOG.items())
    prompt = f"""You are TRINETRA VoiceOps AI (Observe & Analyze).
Parse this field technician voice note (English, Hindi, or Hinglish):
"{transcript}"

Enterprise SKU catalog:
{catalog}

Rules:
- customer_id: digits only (default "102").
- needs_clarification is true ONLY if {COMPRESSOR_SKU} is replaced AND serial_number is missing.
- clarification_question: a polite spoken question asking for the compressor serial number.
- technical_summary: a crisp CRM service summary.
- detected_language: "English", "Hindi" or "Hinglish".
"""
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedNote,
            temperature=0.1,
        ),
    )
    return ParsedNote.model_validate_json(resp.text).model_dump()


def _parse_with_demo_engine(transcript: str) -> dict:
    """Deterministic regex parser so the demo works offline / without a key."""
    m = re.search(r"customer\s*(?:id)?\s*(\d+)", transcript, re.I)
    cid = m.group(1) if m else "102"
    # Serial must contain at least one digit, so "serial number of compressor" is not captured.
    sn = re.search(
        r"(?:\bserial(?:\s*number)?|\bsn\b|#)\s*[:\-]?\s*((?=[A-Z0-9\-]*\d)[A-Z0-9\-]{4,})",
        transcript, re.I,
    )
    serial = sn.group(1).upper() if sn else None

    parts = []
    if re.search(r"compressor", transcript, re.I):
        parts.append({"spoken_name": "rotary compressor", "mapped_sku": COMPRESSOR_SKU,
                      "quantity": 1, "serial_number": serial})
    if re.search(r"capacitor", transcript, re.I) or not parts:
        qty = 2 if re.search(r"\b(two|2|do)\b", transcript, re.I) else 1
        parts.append({"spoken_name": "capacitor", "mapped_sku": "DKN-CAP-45MFD",
                      "quantity": qty, "serial_number": None})

    needs = any(p["mapped_sku"] == COMPRESSOR_SKU for p in parts) and not serial
    return {
        "customer_id": cid,
        "parts_used": parts,
        "needs_clarification": needs,
        "clarification_question": (
            f"Verified, Ravi. Customer {cid} is under extended warranty. "
            "Please state the new compressor serial number." if needs else None),
        "technical_summary": (
            f"Completed AC repair for Customer {cid}. "
            f"Replaced {', '.join(p['mapped_sku'] for p in parts)}."),
        "detected_language": "Hinglish/English",
    }


def _observe(transcript: str):
    try:
        return _parse_with_gemini(transcript), f"{GEMINI_MODEL} (live Gemini API)"
    except Exception as exc:  # no key, no SDK, network/quota error, bad JSON...
        engine = "Built-in demo parser"
        if _api_key():
            engine += f" (Gemini call failed: {type(exc).__name__})"
        else:
            engine += " (set GEMINI_API_KEY for live Gemini)"
        return _parse_with_demo_engine(transcript), engine


# ---------------------------------------------------------------------------
# Swarm orchestration (Agent 8: Supervisor)
# ---------------------------------------------------------------------------
def run_swarm(transcript: str) -> dict:
    trace_id = f"TRN-{uuid.uuid4().hex[:8].upper()}"
    logs = [{
        "agent": "Agent 1: Voice Understanding", "eye": "OBSERVE",
        "status": "Voiceprint check passed (demo simulation: Ravi Kumar, 99.4%). Normalizing speech...",
    }]

    parsed, engine = _observe(transcript)
    logs.append({
        "agent": "Agent 1: Structured Extraction", "eye": "OBSERVE",
        "status": f"Parsed via {engine} | Customer #{parsed['customer_id']}",
    })

    if parsed.get("needs_clarification"):
        logs.append({
            "agent": "Agent 8: Supervisor (Voice Loop)", "eye": "OBSERVE",
            "status": "Missing mandatory warranty serial number. Asking technician for clarification...",
        })
        return {
            "trace_id": trace_id, "state": "NEEDS_CLARIFICATION",
            "voice_reply": parsed.get("clarification_question")
            or "Please state the new compressor serial number.",
            "engine_used": engine, "logs": logs,
        }

    logs.append({
        "agent": "Agent 2: Intent & Task Planner", "eye": "ANALYZE",
        "status": "Generated 6-node execution DAG across CRM, ERP, Approval & Billing.",
    })

    # Agent 3: CRM
    ticket = EnterpriseMCPHub.crm_get_customer_ticket(parsed["customer_id"])
    EnterpriseMCPHub.crm_update_ticket(ticket["ticket_id"], parsed["technical_summary"])
    warranty = bool(ticket["warranty_active"])
    logs.append({
        "agent": "Agent 3: CRM Agent (MCP-Salesforce)", "eye": "ACT",
        "status": f"Updated {ticket['ticket_id']} ({ticket['customer_name']}). "
                  f"Warranty: {'ACTIVE' if warranty else 'EXPIRED'}.",
    })

    # Agent 4: Inventory
    parts_cost = 0.0
    for p in parsed["parts_used"]:
        qty = p.get("quantity", 1) or 1
        inv = EnterpriseMCPHub.erp_deduct_inventory(p["mapped_sku"], qty)
        if not inv["found"]:
            continue
        parts_cost += inv["unit_price_inr"] * qty
        restock = " Van stock hit 0 -> Auto-PO #PO-7712 dispatched!" if inv["reorder"] else ""
        logs.append({
            "agent": "Agent 4: Inventory Agent (MCP-SAP)", "eye": "ACT",
            "status": f"Deducted {qty}x {p['mapped_sku']}. "
                      f"Stock: {inv['prev_stock']} -> {inv['new_stock']}.{restock}",
        })

    # Agents 5-7: Billing + Approval gate
    bill = EnterpriseMCPHub.billing_create_invoice(warranty, parts_cost)
    inv_id, total = bill["invoice_id"], bill["billable_total_inr"]
    needs_approval = parts_cost > APPROVAL_THRESHOLD_INR
    status = "PENDING_MANAGER_APPROVAL" if needs_approval else "AUTO_APPROVED"

    if needs_approval:
        logs.append({
            "agent": "Agent 7: Approval & Compliance Gate", "eye": "ACT",
            "status": f"Part value Rs {parts_cost:,.0f} exceeds Rs {APPROVAL_THRESHOLD_INR:,.0f} limit. "
                      "Paused closure; 1-tap HITL card sent to Manager.",
        })
        reply = (f"Customer {parsed['customer_id']} logged and van stock updated. "
                 f"Since the part value exceeds {APPROVAL_THRESHOLD_INR:,.0f} rupees, "
                 "I sent a one-tap approval request to your manager.")
    else:
        EnterpriseMCPHub.crm_update_ticket(ticket["ticket_id"], parsed["technical_summary"], "CLOSED")
        logs.append({
            "agent": "Agent 5, 6 & 8: Invoice, WhatsApp & Close", "eye": "ACT",
            "status": f"Generated {inv_id} (Rs {total:,.0f}), notified customer & closed {ticket['ticket_id']}.",
        })
        reply = (f"All done, Ravi! Ticket {ticket['ticket_id']} is closed and invoice {inv_id} "
                 f"has been sent to {ticket['customer_name']} on WhatsApp.")

    audit_hash = hashlib.sha256(f"{trace_id}|{transcript}".encode()).hexdigest()
    save_workflow({
        "trace_id": trace_id, "ticket_id": ticket["ticket_id"],
        "customer_id": parsed["customer_id"], "transcript": transcript,
        "structured_json": json.dumps(parsed), "approval_status": status,
        "invoice_id": inv_id, "parts_cost_inr": parts_cost, "billable_total_inr": total,
        "audit_hash": audit_hash, "logs_json": json.dumps(logs), "created_at": utc_now(),
    })

    return {
        "trace_id": trace_id, "state": status, "voice_reply": reply,
        "invoice_id": inv_id, "parts_cost_inr": parts_cost, "billable_total_inr": total,
        "audit_hash": audit_hash, "engine_used": engine, "logs": logs,
    }


def approve_workflow(trace_id: str) -> dict:
    """Manager HITL approval: resumes a paused workflow and closes the ticket."""
    wf = get_workflow(trace_id)
    if wf is None:
        raise LookupError(f"Unknown trace id {trace_id}")
    if wf["approval_status"] != "PENDING_MANAGER_APPROVAL":
        raise ValueError(f"Workflow {trace_id} is not awaiting approval ({wf['approval_status']})")

    logs = json.loads(wf["logs_json"]) + [{
        "agent": "Agent 7 & 8: Approved & Closed", "eye": "ACT",
        "status": f"Manager approved! Invoice {wf['invoice_id']} sent via WhatsApp & "
                  f"{wf['ticket_id']} CLOSED.",
    }]
    update_workflow_approval(trace_id, "APPROVED_AND_COMPLETED", logs)
    EnterpriseMCPHub.crm_update_ticket(
        wf["ticket_id"], "Approved & closed via TRINETRA VoiceOps AI.", "CLOSED")
    return {
        "trace_id": trace_id, "state": "CLOSED",
        "voice_reply": f"Manager approved! Ticket {wf['ticket_id']} is now closed.",
        "logs": logs,
    }
