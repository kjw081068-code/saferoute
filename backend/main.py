from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import safety

app = FastAPI(title="신림동 안전경로 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(safety.router, prefix="/api")
