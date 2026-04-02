"""로컬 개발 서버 실행 스크립트 - .env 자동 로드 보장"""
import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

# 스크립트 위치로 작업 디렉토리 고정 후 .env 로드
os.chdir(Path(__file__).parent)
load_dotenv(Path(__file__).parent / ".env", override=True)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
