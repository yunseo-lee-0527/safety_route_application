"""
모바일 PWA 런처 — FastAPI 백엔드(8001) + 정적 서버(8000) 한 번에 실행.

사용:
    python run_mobile.py

브라우저에서 열기:
    http://127.0.0.1:8000      ← 모바일 PWA (메인 시연용)
    http://127.0.0.1:8001/docs ← FastAPI Swagger (디버깅용)

Ctrl+C 로 두 서버 모두 종료.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOBILE_DIR = HERE / "mobile"

API_CMD = [
    sys.executable, "-m", "uvicorn",
    "api.main:app",
    "--host", "127.0.0.1",
    "--port", "8001",
]
STATIC_CMD = [
    sys.executable, "-m", "http.server",
    "8000",
    "--bind", "127.0.0.1",
]


def main() -> int:
    print("[run_mobile] FastAPI 백엔드 시작 (포트 8001)...")
    api_proc = subprocess.Popen(API_CMD, cwd=str(HERE))

    print("[run_mobile] 정적 서버 시작 (포트 8000)...")
    static_proc = subprocess.Popen(STATIC_CMD, cwd=str(MOBILE_DIR))

    # 백엔드가 데이터 로드하는 동안 잠시 대기 후 브라우저 열기
    time.sleep(4)
    url = "http://127.0.0.1:8000"
    print(f"[run_mobile] 브라우저 열기: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("\n=================================================================")
    print("  모바일 PWA:   http://127.0.0.1:8000")
    print("  API Swagger: http://127.0.0.1:8001/docs")
    print("  종료: Ctrl+C")
    print("=================================================================\n")

    def shutdown(signum, frame):
        print("\n[run_mobile] 종료 중...")
        for p in (api_proc, static_proc):
            try:
                p.terminate()
            except Exception:
                pass
        for p in (api_proc, static_proc):
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    # 두 프로세스 중 하나라도 죽으면 다른 것도 정리
    while True:
        api_rc = api_proc.poll()
        static_rc = static_proc.poll()
        if api_rc is not None:
            print(f"[run_mobile] FastAPI 종료됨 (exit {api_rc})")
            shutdown(None, None)
        if static_rc is not None:
            print(f"[run_mobile] 정적 서버 종료됨 (exit {static_rc})")
            shutdown(None, None)
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
