from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import os
from app.database import supabase

router = APIRouter()

TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # sandbox number

# ── Models ────────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    candidate_id: str
    job_choice: str | None = None
    career_choice: str | None = None
    score: int | None = None

class BulkTriggerRequest(BaseModel):
    candidate_ids: list[str]
    message_override: str | None = None   # optional custom message for admin bulk send

# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_phone(raw: str) -> str:
    """Ensure E.164 with country code — defaults to +91 (India)."""
    phone = raw.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return f"whatsapp:{phone}"
    if phone.startswith("91") and len(phone) == 12:
        return f"whatsapp:+{phone}"
    # Assume India mobile (10 digits)
    return f"whatsapp:+91{phone}"


def _send_whatsapp(to_phone: str, body: str) -> dict:
    """
    Send a WhatsApp message via Twilio sandbox.

    The sandbox requires the recipient to have sent 'join <word>' to the sandbox
    number first. Plain text works fine for sandbox conversations.
    For production numbers, use approved templates with content_sid.
    """
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    try:
        msg = client.messages.create(
            from_=TWILIO_FROM,
            to=_format_phone(to_phone),
            body=body,
        )
        return {"success": True, "sid": msg.sid, "status": msg.status}
    except TwilioRestException as e:
        print(f"=== WHATSAPP ERROR: {e} ===")
        # Error 21654 = ContentSid required → recipient hasn't joined sandbox
        if e.code == 21654:
            return {
                "success": False,
                "error": "sandbox_not_joined",
                "message": "Recipient must send 'join twilio-trial' to +14155238886 on WhatsApp first.",
            }
        return {"success": False, "error": str(e)}


def _build_message(candidate: dict, job_choice: str | None, career_choice: str | None, score: int | None) -> str:
    name  = candidate.get("name", "Candidate")
    score_line = f"Your skill test score: *{score}%*\n" if score else ""
    job_line   = f"Role: *{job_choice}*\n" if job_choice else ""
    career_line = f"Path: *{career_choice}*\n" if career_choice else ""

    return (
        f"Hi {name}! 👋\n\n"
        f"Congratulations on completing the ASSISTLANA skill assessment!\n\n"
        f"{score_line}"
        f"{job_line}"
        f"{career_line}\n"
        f"Our team will review your profile and get back to you shortly.\n\n"
        f"— ASSISTLANA Team"
    )

# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/trigger")
async def trigger_whatsapp(req: TriggerRequest):
    """Trigger WhatsApp message to a single candidate after skill test."""
    # Fetch candidate
    result = await _get_candidate(req.candidate_id)
    if not result:
        raise HTTPException(status_code=404, detail="Candidate not found")

    phone = result.get("phone", "")
    if not phone:
        return {"success": False, "message": "No phone number on record"}

    body = _build_message(result, req.job_choice, req.career_choice, req.score)
    outcome = _send_whatsapp(phone, body)

    # Update whatsapp_triggered flag in DB (even if message failed, record the attempt)
    supabase.table("candidates").update({
        "whatsapp_triggered": True,
        "job_choice": req.job_choice,
        "career_choice": req.career_choice,
    }).eq("id", req.candidate_id).execute()

    return {**outcome, "candidate": result.get("name"), "phone": phone}


@router.post("/bulk-trigger")
async def bulk_trigger(req: BulkTriggerRequest):
    """Admin: send WhatsApp to a list of candidate IDs."""
    results = []
    for cid in req.candidate_ids:
        candidate = await _get_candidate(cid)
        if not candidate:
            results.append({"id": cid, "success": False, "error": "not found"})
            continue

        phone = candidate.get("phone", "")
        if not phone:
            results.append({"id": cid, "success": False, "error": "no phone"})
            continue

        if req.message_override:
            body = req.message_override.replace("{name}", candidate.get("name", "Candidate"))
        else:
            body = _build_message(candidate, candidate.get("job_choice"), candidate.get("career_choice"), candidate.get("skill_test_score"))

        outcome = _send_whatsapp(phone, body)
        supabase.table("candidates").update({"whatsapp_triggered": True}).eq("id", cid).execute()
        results.append({"id": cid, "name": candidate.get("name"), **outcome})

    sent  = sum(1 for r in results if r.get("success"))
    failed = len(results) - sent
    return {"sent": sent, "failed": failed, "results": results}


@router.post("/webhook")
async def whatsapp_webhook(data: dict = None):
    """Twilio webhook — receives candidate replies (optional, for future use)."""
    return {"status": "received"}


# ── Internal helper ───────────────────────────────────────────────────────────

async def _get_candidate(candidate_id: str) -> dict | None:
    try:
        res = supabase.table("candidates").select("*").eq("id", candidate_id).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"DB error: {e}")
    return None