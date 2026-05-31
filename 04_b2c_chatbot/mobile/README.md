# 모바일 PWA

FastAPI 백엔드(`api/`)와 연동되는 정적 모바일 프론트엔드입니다.

## 실행

레포 루트에서 API 서버를 먼저 실행합니다.

```bash
uvicorn api.main:app --reload --port 8001
```

다른 터미널에서 모바일 정적 서버를 실행합니다.

```bash
cd mobile
python -m http.server 8000
```

브라우저에서 `http://localhost:8000`에 접속합니다.

## 파일

- `index.html`: SPA 진입점
- `app.js`: 화면 상태, API 호출, 지도 렌더링
- `styles.css`: 모바일 UI 스타일
- `manifest.json`: PWA 메타데이터
- `sw.js`: 서비스 워커
- `icon.svg`: 앱 아이콘
