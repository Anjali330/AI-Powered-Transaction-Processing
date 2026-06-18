from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers import jobs

app = FastAPI(title="AI-Powered Transaction Processing", version="1.0.0")

app.include_router(jobs.router)


@app.get("/health", tags=["health"])
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
