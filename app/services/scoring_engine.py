from typing import List

WEIGHTS = {
    "skills":     0.40,
    "experience": 0.30,
    "education":  0.20,
    "extras":     0.10,
}

EDUCATION_SCORES = {
    "PhD":      100,
    "M.Tech":   90,
    "MBA":      85,
    "M.Sc":     85,
    "B.Tech":   75,
    "B.E":      75,
    "BCA":      65,
    "B.Sc":     65,
    "B.Des":    65,
    "Diploma":  50,
    "Graduate": 50,
}

HIGH_VALUE_SKILLS = {
    "Machine Learning": 25, "Deep Learning": 25, "NLP": 20,
    "Python": 20, "SQL": 15, "TensorFlow": 20, "PyTorch": 20,
    "spaCy": 15, "React": 15, "Node.js": 12, "FastAPI": 15,
    "AWS": 15, "Docker": 12, "Kubernetes": 15,
    "JavaScript": 12, "TypeScript": 12, "Java": 12,
}


def score_skills(skills: List[str]) -> float:
    if not skills:
        return 0
    total = 0
    for skill in skills:
        total += HIGH_VALUE_SKILLS.get(skill, 5)
    return min((total / 150) * 100, 100)


def score_experience(years: int) -> float:
    if years <= 0: return 20
    if years == 1: return 35
    if years == 2: return 50
    if years == 3: return 65
    if years == 4: return 75
    if years == 5: return 85
    if years == 6: return 90
    return 100


def score_education(level: str) -> float:
    return EDUCATION_SCORES.get(level, 50)


def score_extras(skills: List[str], text: str) -> float:
    score   = 0
    text_lw = text.lower()
    if any(k in text_lw for k in ["certified", "certification", "aws certified"]):
        score += 20
    if "github.com" in text_lw or "portfolio" in text_lw:
        score += 20
    if "project" in text_lw:
        score += 15
    if "publication" in text_lw or "research" in text_lw:
        score += 15
    if len(skills) >= 10:
        score += 20
    elif len(skills) >= 6:
        score += 10
    return min(score, 100)


def calculate_final_score(skills, experience_years, education_level, text) -> dict:
    s_skills = score_skills(skills)
    s_exp    = score_experience(experience_years)
    s_edu    = score_education(education_level)
    s_extra  = score_extras(skills, text)

    total = (
        s_skills * WEIGHTS["skills"]     +
        s_exp    * WEIGHTS["experience"] +
        s_edu    * WEIGHTS["education"]  +
        s_extra  * WEIGHTS["extras"]
    )

    return {
        "total_score":      round(total),
        "skills_score":     round(s_skills),
        "experience_score": round(s_exp),
        "education_score":  round(s_edu),
        "extras_score":     round(s_extra),
        "breakdown": {
            "skills":     f"{round(s_skills * WEIGHTS['skills'])} / 40",
            "experience": f"{round(s_exp    * WEIGHTS['experience'])} / 30",
            "education":  f"{round(s_edu    * WEIGHTS['education'])} / 20",
            "extras":     f"{round(s_extra  * WEIGHTS['extras'])} / 10",
        }
    }