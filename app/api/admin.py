from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import supabase

router = APIRouter()

# ── Get all candidates ────────────────────────────────────────────────────────
@router.get("/candidates")
async def get_all_candidates():
    result = supabase.table("candidates").select(
        "id, name, email, phone, field, ai_score, skill_test_score, "
        "job_choice, career_choice, status, whatsapp_triggered, created_at, skills"
    ).order("created_at", desc=True).execute()
    return {"candidates": result.data or []}

# ── Update status ─────────────────────────────────────────────────────────────
class StatusUpdate(BaseModel):
    status: str

@router.patch("/candidates/{candidate_id}/status")
async def update_status(candidate_id: str, body: StatusUpdate):
    allowed = {"Reviewing", "Shortlisted", "Hired", "Rejected"}
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {allowed}")
    supabase.table("candidates").update({"status": body.status}).eq("id", candidate_id).execute()
    return {"success": True}

# ── Stats ─────────────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats():
    result = supabase.table("candidates").select(
        "id, ai_score, skill_test_score, status, field, whatsapp_triggered"
    ).execute()
    rows = result.data or []
    total       = len(rows)
    shortlisted = sum(1 for r in rows if r.get("status") == "Shortlisted")
    hired       = sum(1 for r in rows if r.get("status") == "Hired")
    avg_score   = round(sum(r.get("ai_score") or 0 for r in rows) / total, 1) if total else 0
    it_count    = sum(1 for r in rows if r.get("field") == "IT")
    non_it      = sum(1 for r in rows if r.get("field") == "Non-IT")
    wa_sent     = sum(1 for r in rows if r.get("whatsapp_triggered"))
    return {
        "total": total, "shortlisted": shortlisted, "hired": hired,
        "avg_score": avg_score, "it": it_count, "non_it": non_it, "whatsapp_sent": wa_sent,
    }