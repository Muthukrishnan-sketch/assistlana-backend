from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.resume import router as resume_router

app = FastAPI(
    title       = "ASSISTLANA AI Resume Screening API",
    description = "Real AI-powered resume parsing, scoring and matching",
    version     = "1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(resume_router, prefix="/api/resume", tags=["Resume"])


@app.get("/")
def root():
    return {
        "message": "ASSISTLANA AI API is running!",
        "version": "1.0.0",
        "docs":    "/docs"
    }


@app.get("/api/health")
def health():
    return {"status": "healthy"}