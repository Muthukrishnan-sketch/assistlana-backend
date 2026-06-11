from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import List


from app.services.resume_parser  import (
    extract_text_from_pdf, extract_email, extract_phone,
    extract_name, extract_skills, extract_experience_years,
    extract_education, extract_location, estimate_age_from_text,
)
from app.services.scoring_engine import calculate_final_score
from app.database                import supabase

router = APIRouter()

nlp=None


@router.post("/parse-and-save")
async def parse_and_save(
    file: UploadFile = File(...),
    candidate_email: str = None
):
    """Parse resume - UPDATE existing candidate or INSERT new"""

    if not (file.filename.lower().endswith(".pdf") or
            file.filename.lower().endswith(".docx")):
        raise HTTPException(400, "Only PDF or DOCX accepted")

    try:
        file_bytes = await file.read()
        text       = extract_text_from_pdf(file_bytes, file.filename)
        print(f"=== FILE: {file.filename}, SIZE: {len(file_bytes)} bytes ===")
        print(f"=== EXTRACTED: {len(text)} chars ===")
        print(f"=== TEXT SAMPLE: {text[:300]} ===")

        if not text:
            return JSONResponse(content={
                "success": False,
                "error":   "Could not extract text from file"
            })

        # ── Extract real data ──
        name      = extract_name(text, nlp)
        email     = extract_email(text)
        phone     = extract_phone(text)
        skills    = extract_skills(text)
        exp_years = extract_experience_years(text)
        education = extract_education(text)
        location  = extract_location(text)
        age       = estimate_age_from_text(text)

        score_result = calculate_final_score(
            skills           = skills,
            experience_years = exp_years,
            education_level  = education["level"],
            text             = text
        )

        extracted_data = {
            "skills":           skills,
            "experience_years": exp_years,
            "education":        education["level"],
            "qualification":    education["level"],
            "location":         location,
            "age":              age,
            "ai_score":         score_result["total_score"],
            "jd_match":         score_result["total_score"],
            "status":           "Reviewing",
            "resume_text":      text[:3000],
        }

        # Add phone and email only if extracted
        if phone:
            extracted_data["phone"] = phone
        if email:
            extracted_data["email"] = email

        # ── If candidate_email provided → UPDATE existing row ──
        if candidate_email:
            result = supabase.table("candidates") \
                .update(extracted_data) \
                .eq("email", candidate_email) \
                .execute()

            if result.data:
                return JSONResponse(content={
                    "success":   True,
                    "candidate": result.data[0],
                    "score":     score_result,
                    "mode":      "updated",
                    "message":   f"Profile updated for '{result.data[0].get('name')}'"
                })

        # ── No email provided → INSERT new candidate (HR upload) ──
        new_candidate = {
            **extracted_data,
            "name":   name,
            "email":  email if email else name.lower().replace(" ",".") + "@email.com",
            "status": "Pending",
        }

        result = supabase.table("candidates").insert(new_candidate).execute()

        if result.data:
            return JSONResponse(content={
                "success":   True,
                "candidate": result.data[0],
                "score":     score_result,
                "mode":      "inserted",
                "message":   f"'{name}' parsed and saved!"
            })

        return JSONResponse(content={"success": False, "error": "Database error"})

    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})

@router.post("/parse-batch")
async def parse_batch(files: List[UploadFile] = File(...)):
    """Parse multiple resumes at once"""
    results = []
    for file in files:
        try:
            file_bytes = await file.read()
            text = extract_text_from_pdf(file_bytes, file.filename)
            if not text:
                results.append({"filename": file.filename, "success": False, "error": "No text"})
                continue

            name      = extract_name(text, nlp)
            email     = extract_email(text)
            phone     = extract_phone(text)
            skills    = extract_skills(text)
            exp_years = extract_experience_years(text)
            education = extract_education(text)
            location  = extract_location(text)
            age       = estimate_age_from_text(text)

            score_result = calculate_final_score(
                skills=skills, experience_years=exp_years,
                education_level=education["level"], text=text
            )

            candidate = {
                "name":             name,
                "email":            email if email else name.lower().replace(" ", ".") + "123@email.com",
                "phone":            phone if phone else None,
                "skills":           skills,
                "experience_years": exp_years,
                "education":        education["level"],
                "qualification":    education["level"],
                "location":         location,
                "age":              age,
                "ai_score":         score_result["total_score"],
                "jd_match":         score_result["total_score"],
                "status":           "Pending",
                "resume_text": text[:3000],
            }

            db_result = supabase.table("candidates").insert(candidate).execute()
            results.append({
                "filename":  file.filename,
                "success":   True,
                "candidate": db_result.data[0] if db_result.data else candidate,
                "score":     score_result["total_score"],
            })

        except Exception as e:
            results.append({"filename": file.filename, "success": False, "error": str(e)})

    return JSONResponse(content={
        "total":   len(files),
        "success": sum(1 for r in results if r.get("success")),
        "results": results,
    })


@router.get("/candidates")
async def get_candidates():
    result = supabase.table("candidates").select("*").order("ai_score", desc=True).execute()
    return {"candidates": result.data}


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    supabase.table("candidates").delete().eq("id", candidate_id).execute()
    return {"success": True}

# connecting backend
from pydantic import BaseModel

class JDMatchRequest(BaseModel):
    candidate_id: str
    job_id:       str
    resume_text:  str
    jd_text:      str

@router.post("/match-jd")
async def match_jd(request: JDMatchRequest):
    """Compute JD match score for a candidate"""
    try:
        from app.services.jd_matcher import compute_jd_match
        match_score = compute_jd_match(request.resume_text, request.jd_text)

        # Update candidate's jd_match in Supabase
        supabase.table("candidates") \
            .update({"jd_match": match_score}) \
            .eq("id", request.candidate_id) \
            .execute()

        return {"success": True, "jd_match": match_score}
    except Exception as e:
        return {"success": False, "error": str(e)}
