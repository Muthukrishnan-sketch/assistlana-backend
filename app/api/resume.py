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

#####-----new codes------###
# ── Ollama config ──
import os, httpx
OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

async def call_ollama(prompt: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=120) as client:  # ← change 60 to 120
            res = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
            )
            return res.json().get("response", "")
    except Exception as e:
        return f"ERROR: {e}"

class SkillTestRequest(BaseModel):
    skills:         list
    candidate_name: str  = "Candidate"
    is_non_it:      bool = False
class CodeEvalRequest(BaseModel):
    skill:     str
    question:  str
    code:      str
    language:  str = "python"

import re, json, os, httpx

def fix_ollama_mcq_json(text: str) -> dict:
    """
    Fix Ollama's common mistake of putting 'answer' and 'explanation'
    inside the options array instead of at question level.
    Also handles multiple JSON objects in one response.
    """
    if not text or text.startswith("ERROR:"):
        return {}

    # Remove markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    # Take only FIRST JSON object (ignore second one Ollama sometimes adds)
    start = text.find('{')
    if start == -1:
        return {}

    depth = 0
    end   = -1
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return {}

    json_str = text[start:end]

    # Fix: move "answer" and "explanation" out of options array
    # Pattern: options array contains "answer": "X" or "explanation": "..."
    def fix_question(q: dict) -> dict:
        if not isinstance(q.get("options"), list):
            return q
        clean_options = []
        extracted_answer = q.get("answer", "")
        extracted_expl   = q.get("explanation", "")
        for opt in q["options"]:
            if isinstance(opt, str):
                # Check if it's a real option (starts with A) B) C) D))
                if re.match(r'^[A-D]\)', opt.strip()):
                    clean_options.append(opt)
                # If "answer": "B" ended up as a string key somehow, skip
            elif isinstance(opt, dict):
                # Ollama put {"answer": "B"} as an element
                if "answer" in opt:
                    extracted_answer = opt["answer"]
                if "explanation" in opt:
                    extracted_expl   = opt["explanation"]
        if clean_options:
            q["options"]     = clean_options
        if extracted_answer:
            q["answer"]      = extracted_answer
        if extracted_expl:
            q["explanation"] = extracted_expl
        return q

    try:
        data = json.loads(json_str)
        if "mcq" in data:
            data["mcq"] = [fix_question(q) for q in data["mcq"]]
        return data
    except Exception:
        # Last resort: regex extract answer from broken JSON
        try:
            questions = []
            # Find all question blocks roughly
            q_blocks = re.findall(
                r'"question"\s*:\s*"([^"]+)".*?"answer"\s*:\s*"([A-D])"',
                json_str, re.DOTALL
            )
            for q_text, ans in q_blocks:
                # Find options for this question
                opts = re.findall(r'"([A-D]\)[^"]+)"', json_str)
                if opts:
                    questions.append({
                        "skill":       "General",
                        "question":    q_text,
                        "options":     opts[:4],
                        "answer":      ans,
                        "explanation": "See correct answer above."
                    })
            if questions:
                return {"mcq": questions}
        except Exception:
            pass
        return {}

@router.post("/generate-skill-test")

async def generate_skill_test(req: SkillTestRequest):
    try:
        print(f"=== REQUEST: skills={req.skills}, is_non_it={req.is_non_it} ===")
        all_skills = req.skills
        skill_count = len(all_skills)
        is_non_it = req.is_non_it

        print(f"=== SKILL TEST: skills={all_skills}, count={skill_count}, is_non_it={is_non_it} ===")

        # MCQ count based on skill count
        # Non-IT gets more MCQ since there's no code challenge
        if is_non_it:
            if skill_count == 1:
                mcq_count = 6  # 6 per skill instead of 4
            elif skill_count == 2:
                mcq_count = 10
            elif skill_count <= 5:
                mcq_count = 12
            else:
                mcq_count = 15
        else:
            if skill_count == 1:
                mcq_count = 4
            elif skill_count == 2:
                mcq_count = 6
            elif skill_count <= 5:
                mcq_count = 8
            else:
                mcq_count = 10

        print(f"=== TARGET MCQ COUNT: {mcq_count} ===")

        all_mcq = []
        test_skills = all_skills[:min(skill_count, 5)]

        # Generate 1 question per batch — most reliable for Ollama
        for batch_i in range(mcq_count):
            if len(all_mcq) >= mcq_count:
                break

            skill_for_batch = test_skills[batch_i % len(test_skills)]

            if is_non_it:
                prompt = f"""You are a professional workplace skills assessor.

        Generate exactly 1 scenario-based MCQ question to test the skill: {skill_for_batch}

        The candidate is from a NON-IT business background. Do NOT ask any programming or technical questions.
        Ask a real workplace scenario question about {skill_for_batch}.

        Return ONLY this JSON, no other text:
        {{"mcq": [{{"skill": "{skill_for_batch}", "question": "your scenario question here?", "options": ["A) first option", "B) second option", "C) third option", "D) fourth option"], "answer": "B", "explanation": "reason why B is correct"}}]}}"""
            else:
                prompt = f"""You are a technical interviewer.

        Generate exactly 1 MCQ question to test the skill: {skill_for_batch}

        Return ONLY this JSON, no other text:
        {{"mcq": [{{"skill": "{skill_for_batch}", "question": "your technical question here?", "options": ["A) first option", "B) second option", "C) third option", "D) fourth option"], "answer": "B", "explanation": "reason why B is correct"}}]}}"""

            raw = await call_ollama(prompt)
            parsed = fix_ollama_mcq_json(raw)
            print(f"=== BATCH {batch_i} skill={skill_for_batch} parsed={bool(parsed.get('mcq'))} ===")

            mcq_list = parsed.get("mcq", [])
            for q in mcq_list:
                opts = [o for o in q.get("options", []) if isinstance(o, str) and re.match(r'^[A-D]\)', o.strip())]
                if len(opts) >= 2 and q.get("answer") and q.get("question"):
                    q["options"] = opts
                    all_mcq.append(q)
                    break  # Take only 1 per batch call

        print(f"=== TOTAL VALID MCQ: {len(all_mcq)} ===")

        if not all_mcq:
            return JSONResponse(content={
                "success": False,
                "error":   "Could not generate questions. Please try again."
            })

        # ── Code challenge for IT only ──
        code_challenge = None
        if not is_non_it and all_skills:
            code_skill = all_skills[0]

            # Step 1: Ask for problem description only (plain text — more reliable)
            desc_prompt = f"""You are creating a coding test for a {code_skill} developer.

        Write a short coding problem in plain English (2-3 sentences only).
        Do NOT write any code. Just describe what function to write, what it takes as input, and what it should return.
        Make it simple — suitable for a fresher or junior level.

        Problem:"""

            desc_raw = await call_ollama(desc_prompt)
            desc_raw = desc_raw.strip().split("\n")[0][:300]  # Take first line only
            print(f"=== CODE DESC: {desc_raw} ===")

            # Step 2: Ask for function signature only (plain text)
            sig_prompt = f"""For this problem: {desc_raw}

        Write ONLY the Python function signature and parameter names.
        Example: def calculate_average(numbers):
        Write ONLY one line, no code, no explanation."""

            sig_raw = await call_ollama(sig_prompt)
            sig_raw = sig_raw.strip().split("\n")[0].strip()
            # Make sure it starts with def
            if not sig_raw.startswith("def "):
                sig_raw = f"def solution():"
            print(f"=== CODE SIG: {sig_raw} ===")

            # Step 3: Build the code challenge ourselves — no JSON from Ollama
            # Build starter code with only hints, no real logic
            func_name = sig_raw.replace("def ", "").split("(")[0].strip()
            params = sig_raw.split("(")[1].replace("):", "").replace(")", "").strip() if "(" in sig_raw else ""

            starter = f"{sig_raw}\n    # Step 1: Understand the inputs\n    # Step 2: Write your logic here\n    # Step 3: Return the result\n    pass"

            code_challenge = {
                "skill": code_skill,
                "title": f"{code_skill} — Write a function",
                "description": desc_raw,
                "explanation": f"Step 1: Read the problem carefully and understand what inputs the function receives.\nStep 2: Think about the logic needed to process those inputs.\nStep 3: Write your code inside the function and use 'return' to give back the result.\nRemember: Don't just return a hardcoded value — write the actual logic.",
                "starter_code": starter,
                "expected_output": f"{func_name}(...) should return the correct result",
            }
            print(f"=== CODE CHALLENGE BUILT: {code_challenge['title']} ===")
            print(f"=== STARTER: {starter} ===")

        return JSONResponse(content={
            "success": True,
            "test": {
                "mcq":            all_mcq[:mcq_count],
                "code_challenge": code_challenge,
            },
            "skills_tested":   all_skills,
            "total_questions": len(all_mcq[:mcq_count]),
            "is_non_it":       is_non_it,
            "has_code":        code_challenge is not None,
        })

    except Exception as e:
        import traceback
        return JSONResponse(content={
            "success": False,
            "error":   str(e),
            "trace":   traceback.format_exc()
        })

class CodeEvalRequest(BaseModel):
    skill:        str
    question:     str           # problem title
    description:  str = ""      # ← ADD THIS — actual problem statement
    code:         str
    language:     str = "python"
    starter_code: str = ""      # ← ADD THIS — to detect unchanged submission

@router.post("/evaluate-code")
async def evaluate_code(req: CodeEvalRequest):
    try:
        # ── Guard: empty or unchanged submission ──
        submitted = req.code.strip()
        starter   = req.starter_code.strip()

        # Check if code is just the starter or near-empty
        meaningful_lines = [
            l for l in submitted.splitlines()
            if l.strip() and not l.strip().startswith("#") and l.strip() != "pass"
        ]
        is_just_return   = len(meaningful_lines) == 1 and meaningful_lines[0].strip() in ("return", "return None", "return ''", 'return ""')
        is_unchanged     = starter and submitted == starter
        is_empty_logic   = len(meaningful_lines) == 0

        if is_unchanged or is_empty_logic or is_just_return:
            return JSONResponse(content={
                "success": True,
                "evaluation": {
                    "passed":           False,
                    "score":            0,
                    "feedback":         "No solution was written. The starter code was submitted unchanged. Please write your actual logic inside the function.",
                    "improvements":     ["Write the actual logic instead of leaving it as 'pass' or 'return'", "Read the problem description carefully before coding"],
                    "correct_approach": "Write your own solution — see the problem description above."
                }
            })

        # ── Full evaluation with problem description ──
        problem_context = req.description if req.description else req.question

        prompt = f"""You are a strict but fair code reviewer for a technical interview.

Skill being tested: {req.skill}

Problem that was asked:
{problem_context}

Candidate's submitted code:
```{req.language}
{req.code}
```

Evaluate whether this code correctly solves the problem above.
Respond with EXACTLY this JSON and nothing else:
{{
  "passed": true,
  "score": 75,
  "feedback": "2-3 sentences evaluating whether the logic actually solves the stated problem.",
  "improvements": ["specific tip 1", "specific tip 2"],
  "correct_approach": "def function_name(params): return correct_logic_here"
}}

Rules:
- passed: true ONLY if the logic actually solves the described problem correctly
- score: 0 if wrong logic, 40-60 if partial, 70-85 if correct with minor issues, 90+ if clean and correct
- correct_approach: must solve the EXACT problem described above, not a generic example
- Return ONLY valid JSON, no extra text"""

        raw = await call_ollama(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

        result = json.loads(raw)
        return JSONResponse(content={"success": True, "evaluation": result})

    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})