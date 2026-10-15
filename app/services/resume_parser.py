import pdfplumber
import PyPDF2
import re
import io


def extract_text_from_pdf(file_bytes: bytes, filename: str = "") -> str:
    text = ""

    if filename.lower().endswith(".docx"):
        try:
            import zipfile
            from xml.etree import ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    ns   = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    for para in root.findall(".//w:p", ns):
                        line = " ".join(t.text for t in para.findall(".//w:t", ns) if t.text)
                        if line.strip():
                            text += line + "\n"
            return text.strip()
        except Exception as e:
            print(f"DOCX error: {e}")
            return ""

    # pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                w = page.width
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if page_text and len(page_text.strip()) > 50:
                    text += page_text + "\n"
                else:
                    # Two-column fallback
                    for col in [page.crop((0, 0, w/2, page.height)),
                                 page.crop((w/2, 0, w, page.height))]:
                        col_text = col.extract_text(x_tolerance=3, y_tolerance=3)
                        if col_text:
                            text += col_text + "\n"
        if text.strip():
            return text.strip()
    except Exception as e:
        print(f"pdfplumber error: {e}")

    # PyPDF2
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        if text.strip():
            return text.strip()
    except Exception as e:
        print(f"PyPDF2 error: {e}")

    # pdfminer
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(io.BytesIO(file_bytes))
        if text and text.strip():
            return text.strip()
    except Exception as e:
        print(f"pdfminer error: {e}")

    print("ALL extraction failed!")
    return ""


def extract_email(text: str) -> str:
    """
    Extract email — handles broken formatting like 'user @gmail.co m'
    by removing ALL whitespace before searching.
    """
    # Strategy 1: Remove all whitespace and search
    no_space = re.sub(r'\s+', '', text)
    pattern  = r'[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
    matches  = re.findall(pattern, no_space)
    invalid  = ['.png', '.jpg', '.pdf', '.svg', '.gif', '.ico']
    valid    = [m for m in matches if not any(m.lower().endswith(e) for e in invalid)]
    if valid:
        return valid[0]

    # Strategy 2: Single-space cleaned version
    clean   = re.sub(r'\s+', ' ', text)
    matches = re.findall(pattern, clean)
    valid   = [m for m in matches if not any(m.lower().endswith(e) for e in invalid)]
    return valid[0] if valid else ""


def extract_phone(text: str) -> str:
    # Remove ALL whitespace and search for phone patterns
    no_space = re.sub(r'\s+', '', text)

    # +91 prefix
    m = re.search(r'\+?91([6-9]\d{9})', no_space)
    if m:
        return "+91" + m.group(1)

    # Standalone 10-digit Indian number
    m = re.search(r'([6-9]\d{9})', no_space)
    if m:
        return m.group(0)

    # Line-by-line search as fallback
    for line in text.split('\n'):
        clean = re.sub(r'[^\d\+]', '', line)
        m = re.search(r'\+?91?([6-9]\d{9})', clean)
        if m:
            return m.group(1)
        m = re.search(r'([6-9]\d{9})', clean)
        if m:
            return m.group(0)

    return ""


def extract_name(text: str, nlp=None) -> str:
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    SKIP_WORDS = [
        'resume', 'cv', 'curriculum', 'vitae', 'email', 'phone',
        'address', 'linkedin', 'github', 'objective', 'summary',
        'profile', 'contact', 'mobile', 'www', 'http', '@',
        'engineer', 'developer', 'analyst', 'manager', 'designer',
        'scientist', 'junior', 'senior', 'fresher', 'data',
        'tamil', 'nadu', 'kerala', 'india', 'street', 'road',
        'nagar', 'district', 'state', 'city', 'village', 'near',
        'post', 'pin', 'education', 'experience', 'skills',
        'declaration', 'project', 'intern', 'full', 'stack',
        'b.tech', 'b.e', 'b.sc', 'bca', 'm.tech', 'mba',
    ]

    def is_likely_name(line):
        lw = line.lower()
        if any(w in lw for w in SKIP_WORDS):
            return False
        if any(c in line for c in ['@', '|', '/', '\\', '+', ':', ';', ',', '📍', '📞', '✉', '🌐', '💻']):
            return False
        if re.search(r'\d', line):
            return False
        if len(line) > 45:
            return False
        words = line.split()
        if not (1 <= len(words) <= 4):
            return False
        title_ok = all(w[0].isupper() for w in words if len(w) > 1)
        caps_ok  = line.replace(' ', '').isupper() and len(words) >= 2
        return title_ok or caps_ok

    for line in lines[:12]:
        if is_likely_name(line):
            if line.replace(' ', '').isupper():
                return ' '.join(w.capitalize() for w in line.split())
            return line.strip()

    return lines[0][:50] if lines else "Unknown"


def extract_skills(text: str) -> list:
    all_skills = [
        "Python", "Java", "JavaScript", "TypeScript", "C", "C++", "C#",
        "Ruby", "Go", "Swift", "Kotlin", "PHP", "R", "Scala", "Rust",
        "React", "Next.js", "Vue", "Angular", "HTML", "CSS", "Tailwind",
        "Bootstrap", "Redux", "jQuery", "SASS",
        "Node.js", "FastAPI", "Django", "Flask", "Spring", "Express",
        "Laravel", "ASP.NET",
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Firebase",
        "Oracle", "SQL Server", "Cassandra",
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
        "Jenkins", "GitHub Actions", "CI/CD", "Linux", "Nginx",
        "Machine Learning", "Deep Learning", "NLP", "TensorFlow", "PyTorch",
        "scikit-learn", "spaCy", "Keras", "BERT", "OpenCV",
        "Pandas", "NumPy", "Matplotlib", "Seaborn", "Tableau",
        "Power BI", "Excel", "SPSS", "SAS", "Hadoop", "Spark",
        "Git", "GitHub", "JIRA", "Figma", "Postman",
        "REST API", "GraphQL", "Microservices", "Agile", "Scrum",
        "SQL", "Data Analysis", "Data Visualization", "Statistics",
        "ETL", "Business Intelligence", "BI", "Looker",
        "XGBoost", "LightGBM", "NLTK", "LangChain", "FAISS", "MLflow",
        "ReactJS", "Ajax",
    ]
    found   = []
    text_lw = text.lower()
    for skill in all_skills:
        if skill.lower() in text_lw:
            found.append(skill)
    return list(set(found))


def extract_experience_years(text: str) -> int:
    text_lw = text.lower()

    explicit = [
        r'(\d+)\+?\s*years?\s*of\s*(?:work\s*)?experience',
        r'experience\s*:?\s*(\d+)\+?\s*years?',
        r'(\d+)\+?\s*years?\s*experience',
        r'(\d+)\+?\s*yrs?\s*(?:of\s*)?exp',
        r'total\s*experience\s*:?\s*(\d+)',
    ]
    for pat in explicit:
        m = re.search(pat, text_lw)
        if m:
            return int(m.group(1))

    # Merge overlapping date ranges
    year_ranges = re.findall(
        r'(20\d{2})\s*[-–to]+\s*(20\d{2}|present|current)', text_lw
    )
    if year_ranges:
        intervals = sorted(
            [(int(s), 2026 if e in ['present','current'] else int(e))
             for s, e in year_ranges if int(s) < (2026 if e in ['present','current'] else int(e))]
        )
        merged = []
        for s, e in intervals:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append([s, e])
        total = sum(e - s for s, e in merged)
        if total > 0:
            return min(total, 20)

    return 1


def estimate_age_from_text(text: str):
    current_year = 2026
    text_lw      = text.lower()

    sslc_pats = [
        r'(?:sslc|10th|x std|matriculation|secondary).*?(20\d{2})',
        r'(20\d{2}).*?(?:sslc|10th|x std)',
    ]
    for pat in sslc_pats:
        m = re.search(pat, text_lw)
        if m:
            year = int(m.group(1))
            if 2005 <= year <= 2022:
                return current_year - year + 15

    grad_pats = [
        r'(?:b\.?tech|b\.?e|b\.?sc|bca|m\.?tech|mca|graduation|graduated|passout).*?(20\d{2})',
        r'(20\d{2}).*?(?:b\.?tech|b\.?e|b\.?sc|bca)',
    ]
    for pat in grad_pats:
        m = re.search(pat, text_lw)
        if m:
            year = int(m.group(1))
            if 2010 <= year <= 2025:
                return current_year - year + 21

    years = [int(y) for y in re.findall(r'\b(20(?:0[5-9]|1[0-9]|2[0-4]))\b', text)]
    if years:
        age = current_year - min(years) + 18
        if 18 <= age <= 45:
            return age

    return None


def extract_location(text: str) -> str:
    cities = [
        "Chennai", "Mumbai", "Bangalore", "Bengaluru", "Hyderabad",
        "Delhi", "New Delhi", "Kolkata", "Pune", "Ahmedabad", "Jaipur",
        "Noida", "Gurgaon", "Gurugram", "Chandigarh", "Indore", "Bhopal",
        "Nagpur", "Surat", "Lucknow", "Patna", "Bhubaneswar",
        "Visakhapatnam", "Mysuru", "Mysore", "Mangalore",
        "Villupuram", "Tambaram", "Coimbatore", "Madurai", "Trichy",
        "Tiruchirappalli", "Salem", "Tirunelveli", "Vellore", "Erode",
        "Tirupur", "Tiruppur", "Thanjavur", "Cuddalore", "Nagapattinam",
        "Kanchipuram", "Chengalpattu", "Tiruvallur", "Ranipet",
        "Tiruvannamalai", "Kallakurichi", "Perambalur", "Ariyalur",
        "Pudukkottai", "Sivaganga", "Dindigul", "Ramanathapuram",
        "Virudhunagar", "Thoothukudi", "Tenkasi", "Kanniyakumari",
        "Namakkal", "Karur", "Dharmapuri", "Krishnagiri", "Theni",
        "Mayiladuthurai", "Tiruvarur", "Kongarappattu", "Rettanai",
        "Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur",
        "Hubli", "Belgaum",
        "Vijayawada", "Tirupati", "Warangal",
    ]
    text_lw = text.lower()
    for city in cities:
        if re.search(r'\b' + re.escape(city.lower()) + r'\b', text_lw):
            return city
    return "Not specified"


def extract_education(text: str) -> dict:
    text_lw = text.lower()

    # Try to isolate Education section
    edu_match = re.search(
        r'(?:education|academic|qualification)(.*?)(?:experience|skills|project|work|certification|internship|hobby|strength|extra|personal|declaration|$)',
        text_lw, re.DOTALL | re.IGNORECASE
    )
    search_texts = []
    if edu_match:
        search_texts.append(edu_match.group(1))
    search_texts.append(text_lw)  # always search full text as fallback

    # Ordered by priority — most specific first
    degree_patterns = [
        ("PhD",    [r'\bph\.?d\b', r'\bdoctorate\b']),
        ("M.Tech", [r'\bm\.?\s*tech\b', r'\bmaster of technology\b', r'\bmtech\b']),
        ("MCA",    [r'\bmca\b', r'\bmaster of computer application']),
        ("MBA",    [r'\bmba\b', r'\bmaster of business']),
        ("M.E",    [r'\bm\.?\s*e\b', r'\bmaster of engineering\b']),
        ("M.Sc",   [r'\bm\.?\s*sc\b', r'\bmaster of science\b', r'\bmsc\b']),
        ("M.A",    [r'\bm\.?\s*a\b', r'\bmaster of arts\b']),
        ("B.Tech", [
            r'\bb\.?\s*tech\b', r'\bbachelor of technology\b', r'\bbtech\b',
            r'\bb\.tech\s*[-–]\s*\w+',       # B.Tech - IT
            r'\bb\.tech\s*\(\s*\w+\s*\)',     # B.Tech (IT)
            r'b\.tech\s*[-–]\s*information',  # B.Tech - Information Technology
        ]),
        ("B.E",    [r'\bb\.?\s*e\.?\b', r'\bbachelor of engineering\b']),
        ("BCA",    [r'\bbca\b', r'\bbachelor of computer application']),
        ("B.Sc",   [r'\bb\.?\s*sc\b', r'\bbachelor of science\b', r'\bbsc\b']),
        ("B.Com",  [r'\bb\.?\s*com\b', r'\bbachelor of commerce\b']),
        ("B.A",    [r'\bb\.?\s*a\b', r'\bbachelor of arts\b']),
        ("Diploma",[r'\bdiploma\b']),
    ]

    for search_text in search_texts:
        for degree, patterns in degree_patterns:
            for pattern in patterns:
                if re.search(pattern, search_text, re.IGNORECASE):
                    return {"level": degree}

    return {"level": "Unknown"}

def generate_suggestions(skills, experience_years, education, resume_text="", score=0):
    """Generate personalized resume improvement suggestions"""
    suggestions = []
    text_lw = (resume_text or "").lower()

    # Skills count check
    if len(skills) < 4:
        suggestions.append(
            f"You listed only {len(skills)} skill(s). Add more relevant technical skills to improve your match rate."
        )
    elif len(skills) >= 8:
        suggestions.append(
            f"Great skill coverage ({len(skills)} skills detected)! Make sure your strongest skills appear early in your resume."
        )

    # Experience check
    if not experience_years or experience_years == 0:
        suggestions.append(
            "No work experience detected. Add internships, freelance work, or academic projects with dates."
        )
    elif experience_years < 2:
        suggestions.append(
            "You have limited experience. Highlight specific achievements and quantify your impact (e.g. 'improved performance by 30%')."
        )

    # Education check
    if not education or education == "Unknown":
        suggestions.append(
            "Education not clearly detected. Make sure your degree, institution and graduation year are clearly listed."
        )

    # Contact info check
    if "@" not in text_lw:
        suggestions.append(
            "Your email wasn't detected. Place your email address near the top of your resume."
        )

    # Quantified achievements check
    has_numbers = any(char.isdigit() for char in resume_text[:1500]) if resume_text else False
    if not has_numbers:
        suggestions.append(
            "Add measurable achievements with numbers (e.g. 'led a team of 5', 'reduced costs by 20%')."
        )

    # Action verbs check
    action_verbs = ["led", "built", "developed", "designed", "managed", "created", "improved", "launched"]
    if not any(verb in text_lw for verb in action_verbs):
        suggestions.append(
            "Use strong action verbs (Led, Built, Developed, Designed) at the start of your bullet points."
        )

    # Score-based suggestion
    if score < 60:
        suggestions.append(
            "Your AI score is below average. Focus on adding more relevant skills and quantifying your experience."
        )
    elif score >= 85:
        suggestions.append(
            "Excellent profile! Keep your resume updated as you gain new skills."
        )

    if not suggestions:
        suggestions.append("Your resume looks solid! Consider tailoring it for each job you apply to.")

    return suggestions[:6]
