from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

print("Loading sentence transformer model...")
model = SentenceTransformer("all-MiniLM-L6-v2")
print("Model loaded!")


def compute_jd_match(resume_text: str, job_description: str) -> int:
    if not resume_text or not job_description:
        return 50
    try:
        embeddings = model.encode([
            resume_text[:1000],
            job_description[:500]
        ])
        similarity = cosine_similarity(
            embeddings[0].reshape(1, -1),
            embeddings[1].reshape(1, -1)
        )[0][0]
        return max(0, min(100, round(float(similarity) * 100)))
    except Exception as e:
        print(f"JD match error: {e}")
        return 50