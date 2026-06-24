from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import List

from app.services.resume_parser import (
    extract_text_from_pdf, extract_email, extract_phone,
    extract_name, extract_skills, extract_experience_years,
    extract_education, extract_location, estimate_age_from_text,
)
from app.services.scoring_engine import calculate_final_score
from app.database import supabase

router = APIRouter()
nlp    = None  # spaCy disabled — using rule-based extraction


# ── Generate personalized suggestions from resume content ──
def generate_suggestions(skills: list, experience_years: int,
                          education: str, resume_text: str = "",
                          score: int = 0) -> list:
    suggestions = []
    text_lw = (resume_text or "").lower()

    # Skill count
    if len(skills) < 4:
        suggestions.append(
            f"Only {len(skills)} skill(s) detected. Add more relevant technical skills "
            f"to improve your job match rate."
        )
    elif len(skills) >= 8:
        suggestions.append(
            f"Good skill coverage ({len(skills)} skills)! Make sure your strongest "
            f"skills appear prominently near the top of your resume."
        )

    # Missing high-value skills
    skill_lw = [s.lower() for s in skills]
    if "docker" not in skill_lw and "kubernetes" not in skill_lw:
        suggestions.append(
            "Add Docker/Kubernetes to your skills — containerisation is required in "
            "over 60% of engineering job postings."
        )
    if "sql" not in skill_lw and "postgresql" not in skill_lw and "mysql" not in skill_lw:
        suggestions.append(
            "SQL is expected in almost every data/backend role. "
            "Explicitly list it in your skills section."
        )
    if not any(c in skill_lw for c in ["aws", "gcp", "azure"]):
        suggestions.append(
            "Cloud platform experience (AWS / GCP / Azure) is increasingly required. "
            "Add any cloud skills you have or consider getting certified."
        )

    # Experience
    if not experience_years or experience_years < 1:
        suggestions.append(
            "No work experience detected. Include internships, freelance projects, "
            "or academic work with clear start–end dates."
        )
    elif experience_years < 2:
        suggestions.append(
            "Limited experience detected. Highlight your specific achievements and "
            "quantify your impact (e.g. 'reduced load time by 30%')."
        )

    # Education
    if not education or education in ["Unknown", "Graduate"]:
        suggestions.append(
            "Education section wasn't clearly detected. State your degree, "
            "institution and graduation year explicitly."
        )

    # Quantified results
    action_verbs = [
        "improved", "reduced", "increased", "built", "led", "managed",
        "created", "designed", "launched", "delivered", "achieved"
    ]
    has_action = any(v in text_lw for v in action_verbs)
    if not has_action:
        suggestions.append(
            "Use action verbs and numbers in your bullet points "
            "(e.g. 'Built API that reduced response time by 40%')."
        )

    # GitHub / Portfolio
    if "github.com" not in text_lw and "portfolio" not in text_lw:
        suggestions.append(
            "Add a GitHub profile URL or portfolio link — recruiters actively "
            "look at these to verify your skills."
        )

    # LinkedIn
    if "linkedin" not in text_lw:
        suggestions.append(
            "Include your LinkedIn profile URL to make it easier for HR to "
            "find and connect with you."
        )

    # Summary
    if "summary" not in text_lw and "objective" not in text_lw and "profile" not in text_lw:
        suggestions.append(
            "Add a short professional summary (3–4 lines) at the very top of "
            "your resume describing your expertise and career goal."
        )

    # Score-based
    if score < 55:
        suggestions.append(
            "Your AI score is below average. Focus on adding missing skills, "
            "quantifying achievements, and clarifying your education."
        )
    elif score >= 85:
        suggestions.append(
            "Strong profile! Keep updating your resume as you acquire new skills "
            "and certifications to maintain this high score."
        )

    # Fallback
    if not suggestions:
        suggestions.append(
            "Your resume looks solid! Tailor it slightly for each role you apply "
            "to by mirroring the job description's keywords."
        )

    return suggestions[:6]


@router.post("/parse-and-save")
async def parse_and_save(
    file: UploadFile = File(...),
    candidate_email: str = None
):
    """Parse resume — UPDATE existing candidate or INSERT new"""
    if not (file.filename.lower().endswith(".pdf") or
            file.filename.lower().endswith(".docx")):
        raise HTTPException(400, "Only PDF or DOCX accepted")

    try:
        file_bytes = await file.read()
        text       = extract_text_from_pdf(file_bytes, file.filename)

        if not text:
            return JSONResponse(content={
                "success": False,
                "error":   f"Could not extract text. size={len(file_bytes)}, name={file.filename}"
            })

        # Extract
        name      = extract_name(text, nlp)
        email     = extract_email(text)
        phone     = extract_phone(text)
        skills    = extract_skills(text)
        exp_years = extract_experience_years(text)
        education = extract_education(text)
        location  = extract_location(text)
        age       = estimate_age_from_text(text)

        # Score
        score_result = calculate_final_score(
            skills           = skills,
            experience_years = exp_years,
            education_level  = education["level"],
            text             = text
        )

        # Personalized suggestions
        suggestions = generate_suggestions(
            skills           = skills,
            experience_years = exp_years,
            education        = education["level"],
            resume_text      = text,
            score            = score_result["total_score"]
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
            "ai_suggestions":   suggestions,
        }

        if phone: extracted_data["phone"] = phone
        if email: extracted_data["email"] = email

        # UPDATE existing candidate
        if candidate_email:
            print(f"=== UPDATING {candidate_email} ===")
            print(f"=== SUGGESTIONS: {suggestions} ===")
            print(f"=== AI_SCORE: {score_result['total_score']} ===")
            result = supabase.table("candidates") \
                .update(extracted_data) \
                .eq("email", candidate_email) \
                .execute()
            print(f"=== UPDATE RESULT: {result.data} ===")

            if result.data:
                return JSONResponse(content={
                    "success":   True,
                    "candidate": result.data[0],
                    "score":     score_result,
                    "mode":      "updated",
                    "message":   f"Profile updated!"
                })
            else:
                return JSONResponse(content={
                    "success": False,
                    "error":   "Update returned no data — email may not match any row"
                })

        # ── No email provided → try UPDATE first, then INSERT ──
        final_email = email if email else name.lower().replace(" ", ".") + "@email.com"

        # Check if candidate already exists
        existing = supabase.table("candidates") \
            .select("id") \
            .eq("email", final_email) \
            .execute()

        if existing.data:
            # UPDATE existing
            result = supabase.table("candidates") \
                .update({**extracted_data, "name": name}) \
                .eq("email", final_email) \
                .execute()
        else:
            # INSERT new
            new_candidate = {
                **extracted_data,
                "name": name,
                "email": final_email,
                "status": "Pending",
            }
            result = supabase.table("candidates").insert(new_candidate).execute()

        result = supabase.table("candidates").insert(new_candidate).execute()

        if result.data:
            return JSONResponse(content={
                "success":   True,
                "candidate": result.data[0],
                "score":     score_result,
                "mode":      "inserted",
                "message":   f"'{name}' parsed and saved!"
            })

        return JSONResponse(content={"success": False, "error": "Database insert failed"})

    except Exception as e:
        import traceback
        return JSONResponse(content={
            "success": False,
            "error":   str(e),
            "trace":   traceback.format_exc()
        })


@router.post("/parse-batch")
async def parse_batch(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        try:
            file_bytes = await file.read()
            text       = extract_text_from_pdf(file_bytes, file.filename)
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

            suggestions = generate_suggestions(
                skills=skills, experience_years=exp_years,
                education=education["level"], resume_text=text,
                score=score_result["total_score"]
            )

            candidate = {
                "name":             name,
                "email":            email if email else
                                    name.lower().replace(" ", ".") + "123@email.com",
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
                "resume_text":      text[:3000],
                "ai_suggestions":   suggestions,
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
    result = supabase.table("candidates").select("*") \
        .order("ai_score", desc=True).execute()
    return {"candidates": result.data}


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    supabase.table("candidates").delete().eq("id", candidate_id).execute()
    return {"success": True}


from pydantic import BaseModel

class JDMatchRequest(BaseModel):
    candidate_id: str
    job_id:       str
    resume_text:  str
    jd_text:      str

@router.post("/match-jd")
async def match_jd(request: JDMatchRequest):
    try:
        from app.services.jd_matcher import compute_jd_match
        match_score = compute_jd_match(request.resume_text, request.jd_text)
        supabase.table("candidates") \
            .update({"jd_match": match_score}) \
            .eq("id", request.candidate_id) \
            .execute()
        return {"success": True, "jd_match": match_score}
    except Exception as e:
        return {"success": False, "error": str(e)}