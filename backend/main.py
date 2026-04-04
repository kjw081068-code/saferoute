from pathlib import Path

from dotenv import load_dotenv

# 환경변수 로드 (라우터 import 전에 실행)
# override=True: OS에 빈 TMAP_APP_KEY 등이 있어도 backend/.env 값이 우선 (로컬 개발용)
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import safety
from routers import route

app = FastAPI(title="신림동 안전경로 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://saferoute-two.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(safety.router, prefix="/api")
app.include_router(route.router, prefix="/api")
