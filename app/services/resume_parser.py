import pdfplumber
import PyPDF2
import re
import io


def extract_text_from_pdf(file_bytes: bytes, filename: str = "") -> str:
    """Extract text from PDF or DOCX"""
    text = ""

    # Handle DOCX files
    if filename.lower().endswith(".docx"):
        try:
            import zipfile
            from xml.etree import ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    ns   = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    paras = root.findall(".//w:p", ns)
                    for para in paras:
                        texts = para.findall(".//w:t", ns)
                        line  = " ".join(t.text for t in texts if t.text)
                        if line.strip():
                            text += line + "\n"
            return text.strip()
        except Exception as e:
            print(f"DOCX error: {e}")
            return ""

    # Handle PDF files
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass

    if not text.strip():
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception:
            pass

    return text.strip()


def extract_email(text: str) -> str:
    """Extract real email - skip generated ones"""
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    matches  = re.findall(pattern, text)
    # Filter out image/file extensions
    valid = [m for m in matches if not any(
        m.lower().endswith(ext) for ext in ['.png','.jpg','.pdf','.com.png']
    )]
    return valid[0] if valid else ""


def extract_phone(text: str) -> str:
    """Extract Indian phone number properly"""
    clean = re.sub(r'[^\d\s\+\-\(\)]', ' ', text)
    lines = text.split('\n')

    # Search line by line for phone patterns
    for line in lines:
        # Pattern: +91 XXXXXXXXXX
        m = re.search(r'\+91[\s\-]?([6-9]\d{9})', line)
        if m:
            return "+91" + m.group(1)

        # Pattern: 91XXXXXXXXXX
        m = re.search(r'\b91([6-9]\d{9})\b', line)
        if m:
            return "+91" + m.group(1)

        # Pattern: standalone 10-digit
        m = re.search(r'\b([6-9]\d{9})\b', line)
        if m:
            return m.group(1)

        # Pattern: XXXXX XXXXX
        m = re.search(r'\b([6-9]\d{4})[\s](\d{5})\b', line)
        if m:
            return m.group(1) + m.group(2)

    return ""


def extract_name(text: str, nlp) -> str:
    """Extract candidate name - multiple strategies with location filtering"""

    # Known locations/places to skip if detected as PERSON
    LOCATION_WORDS = {
        'tamil', 'nadu', 'kerala', 'karnataka', 'andhra', 'pradesh',
        'chennai', 'mumbai', 'bangalore', 'hyderabad', 'delhi', 'india',
        'street', 'road', 'nagar', 'district', 'state', 'city', 'village',
        'tambaram', 'villupuram', 'coimbatore', 'madurai',
    }

    # Strategy 1: spaCy NER on first 400 chars
    doc = nlp(text[:400])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            name_lw = name.lower()
            # Must have 2+ words, no digits, not a location
            if (len(name.split()) >= 2 and
                not any(c.isdigit() for c in name) and
                not any(loc in name_lw for loc in LOCATION_WORDS) and
                len(name) < 50):
                return name

    # Strategy 2: Scan first 10 lines for name-like line
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    SKIP_WORDS = [
        'resume', 'cv', 'curriculum', 'vitae', 'email', 'phone',
        'address', 'linkedin', 'github', 'objective', 'summary',
        'profile', 'contact', 'mobile', 'www', 'http', '@',
        'engineer', 'developer', 'analyst', 'manager', 'designer',
        'tamil', 'nadu', 'kerala', 'india', 'street', 'road',
        'nagar', 'district', 'state', 'city', 'village', 'near',
        'post', 'pin', 'education', 'experience', 'skills',
        'objective', 'declaration', 'project', 'intern',
    ]

    for line in lines[:10]:
        line_lw = line.lower()

        # Skip if contains skip words
        if any(w in line_lw for w in SKIP_WORDS):
            continue

        # Skip if contains special chars
        if any(c in line for c in ['@', '|', '/', '\\', '+', ':', ';']):
            continue

        # Skip if looks like address (has numbers + letters mixed)
        if re.search(r'\d', line) and re.search(r'[A-Za-z]{3}', line):
            continue

        # Skip if too long (likely a sentence)
        if len(line) > 45:
            continue

        words = line.split()

        # Good name: 1-4 words, all start with capital or are short connectors
        if 1 <= len(words) <= 4:
            # All words should start with uppercase
            if all(w[0].isupper() for w in words if len(w) > 1):
                # Make sure it's not all caps header like "EDUCATION"
                if not line.isupper() or len(words) >= 2:
                    return line.strip()

    # Strategy 3: Look for ALL CAPS name (common in Indian resumes)
    for line in lines[:8]:
        words = line.split()
        if 1 <= len(words) <= 4 and line.isupper() and len(line) > 3:
            # Convert "MUTHUKRISHNAN S" to "Muthukrishnan S"
            name = ' '.join(w.capitalize() for w in words)
            name_lw = name.lower()
            if not any(loc in name_lw for loc in LOCATION_WORDS):
                return name

    return lines[0][:50] if lines else "Unknown"

def extract_skills(text: str) -> list:
    all_skills = [
        # Programming
        "Python", "Java", "JavaScript", "TypeScript", "C", "C++", "C#",
        "Ruby", "Go", "Swift", "Kotlin", "PHP", "R", "Scala", "Rust",
        # Web Frontend
        "React", "Next.js", "Vue", "Angular", "HTML", "CSS", "Tailwind",
        "Bootstrap", "Redux", "jQuery", "SASS", "LESS",
        # Web Backend
        "Node.js", "FastAPI", "Django", "Flask", "Spring", "Express",
        "Laravel", "ASP.NET", "Servlet",
        # Database
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Firebase",
        "Oracle", "SQL Server", "Cassandra",
        # Cloud & DevOps
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
        "Jenkins", "GitHub Actions", "CI/CD", "Linux", "Nginx",
        # AI / ML / Data
        "Machine Learning", "Deep Learning", "NLP", "TensorFlow", "PyTorch",
        "scikit-learn", "spaCy", "Keras", "BERT", "OpenCV",
        "Pandas", "NumPy", "Matplotlib", "Seaborn", "Tableau",
        "Power BI", "Excel", "SPSS", "SAS", "Hadoop", "Spark",
        # Tools
        "Git", "GitHub", "JIRA", "Figma", "Postman", "VS Code",
        "REST API", "GraphQL", "Microservices", "Agile", "Scrum",
        # Data Analytics specific
        "SQL", "Data Analysis", "Data Visualization", "Statistics",
        "ETL", "Business Intelligence", "BI", "Looker", "Metabase",
    ]

    found   = []
    text_lw = text.lower()
    for skill in all_skills:
        if skill.lower() in text_lw:
            found.append(skill)
    return list(set(found))


def extract_experience_years(text: str) -> int:
    text_lw = text.lower()
    patterns = [
        r'(\d+)\+?\s*years?\s*of\s*(?:work\s*)?experience',
        r'experience\s*:?\s*(\d+)\+?\s*years?',
        r'(\d+)\+?\s*years?\s*experience',
        r'(\d+)\+?\s*yrs?\s*(?:of\s*)?exp',
        r'total\s*experience\s*:?\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lw)
        if match:
            return int(match.group(1))

    # Count from work history
    year_ranges = re.findall(r'(20\d{2})\s*[-–to]+\s*(20\d{2}|present|current)', text_lw)
    total_years = 0
    for start, end in year_ranges:
        s = int(start)
        e = 2026 if end in ['present','current'] else int(end)
        total_years += max(0, e - s)
    if total_years > 0:
        return min(total_years, 20)

    return 1


def estimate_age_from_text(text: str) -> int:
    current_year = 2026
    text_lw      = text.lower()

    # From SSLC/10th year
    sslc_patterns = [
        r'(?:sslc|10th|x std|matriculation|secondary).*?(20\d{2})',
        r'(20\d{2}).*?(?:sslc|10th|x std)',
    ]
    for pat in sslc_patterns:
        match = re.search(pat, text_lw)
        if match:
            year = int(match.group(1))
            if 2005 <= year <= 2022:
                return current_year - year + 15

    # From graduation
    grad_patterns = [
        r'(?:b\.?tech|b\.?e|b\.?sc|bca|graduation|graduated|passout).*?(20\d{2})',
        r'(20\d{2}).*?(?:b\.?tech|b\.?e|b\.?sc|bca)',
    ]
    for pat in grad_patterns:
        match = re.search(pat, text_lw)
        if match:
            year = int(match.group(1))
            if 2010 <= year <= 2025:
                return current_year - year + 21

    # Earliest 4-digit year in education section
    years = [int(y) for y in re.findall(r'\b(20(?:0[5-9]|1[0-9]|2[0-4]))\b', text)]
    if years:
        earliest = min(years)
        age      = current_year - earliest + 18
        if 18 <= age <= 45:
            return age

    return None


def extract_location(text: str) -> str:
    # Extended city list
    cities = [
        "Chennai", "Mumbai", "Bangalore", "Bengaluru", "Hyderabad",
        "Delhi", "New Delhi", "Kolkata", "Pune", "Ahmedabad", "Jaipur",
        "Chennai", "Chengalpattu", "Kanchipuram", "Tiruvallur", "Ranipet",
        "Tirupathur", "Vellore", "Tiruvannamalai", "Villupuram", "Kallakurichi",
        "Cuddalore", "Mayiladuthurai", "Nagapattinam", "Tiruvarur", "Thanjavur",
        "Tiruchirappalli", "Perambalur", "Ariyalur", "Pudukkottai", "Sivaganga",
        "Madurai", "Theni", "Dindigul", "Ramanathapuram", "Virudhunagar",
        "Thoothukudi", "Tirunelveli", "Tenkasi", "Kanniyakumari", "Salem",
        "Namakkal", "Erode", "Tiruppur", "Coimbatore", "The Nilgiris",
        "Karur", "Dharmapuri", "Krishnagiri",
        "Nagpur", "Surat", "Lucknow", "Patna", "Bhubaneswar", "Visakhapatnam",
        "Mysuru", "Mysore", "Mangalore", "Hubli", "Belgaum",
    ]
    text_lw = text.lower()
    for city in cities:
        if city.lower() in text_lw:
            return city
    return "Not specified"




def extract_education(text: str) -> dict:
    text_lw = text.lower()

    # Try to isolate Education section
    edu_match = re.search(
        r"(education|academic qualification|qualification)(.*?)(experience|skills|projects|certifications|internship|achievements|$)",
        text_lw,
        re.DOTALL
    )

    search_text = edu_match.group(2) if edu_match else text_lw

    patterns = [
        ("PhD", [
            r"\bph\.?d\b",
            r"\bdoctorate\b"
        ]),

        ("M.Tech", [
            r"\bm\.?tech\b",
            r"\bmaster of technology\b"
        ]),

        ("MBA", [
            r"\bmba\b",
            r"\bmaster of business administration\b"
        ]),

        ("MCA", [
            r"\bmca\b",
            r"\bmaster of computer applications?\b"
        ]),

        ("M.E", [
            r"\bm\.?e\b",
            r"\bmaster of engineering\b"
        ]),

        ("M.Sc", [
            r"\bm\.?sc\b",
            r"\bmaster of science\b"
        ]),

        ("B.E", [
            r"\bb\.?e\b",
            r"\bbachelor of engineering\b"
        ]),

        ("B.Tech", [
            r"\bb\.?tech\b",
            r"\bbachelor of technology\b"
        ]),

        ("BCA", [
            r"\bbca\b",
            r"\bbachelor of computer applications?\b"
        ]),

        ("B.Sc", [
            r"\bb\.?sc\b",
            r"\bbachelor of science\b"
        ]),

        ("B.Com", [
            r"\bb\.?com\b",
            r"\bbachelor of commerce\b"
        ]),

        ("Diploma", [
            r"\bdiploma\b"
        ]),
    ]

    for degree, regex_list in patterns:
        for pattern in regex_list:
            if re.search(pattern, search_text, re.IGNORECASE):
                return {"level": degree}

    return {"level": "Unknown"}