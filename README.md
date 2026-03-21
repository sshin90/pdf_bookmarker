# bookmark_pdf

PDF 파일을 업로드하면 문서 텍스트를 분석해 북마크(목차)를 자동 생성/수정하고, 북마크가 적용된 PDF를 다시 다운로드할 수 있는 Streamlit 앱입니다.

## 주요 기능

- PDF 업로드 후 기존 북마크 확인
- OpenRouter 무료 모델로 북마크 자동 생성
- 생성된 북마크를 표에서 직접 편집(페이지, 레벨, 제목)
- 편집 결과를 즉시 PDF에 반영해 다운로드

## 기술 스택

- Python
- Streamlit
- PyMuPDF
- OpenRouter API (`openai` SDK 사용)

## 빠른 시작

### 1) 저장소 클론

```bash
git clone <your-repo-url>
cd bookmark_pdf
```

### 2) 가상환경 생성/활성화

Windows PowerShell:

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3) 의존성 설치

```bash
pip install -r requirements.txt
```

### 4) 환경 변수 설정

`.env.example`을 복사해 `.env`를 만든 뒤 값을 채웁니다.

```bash
cp .env.example .env
```

`.env`:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

### 5) 앱 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501`로 접속합니다.

### 6) 스모크 테스트(선택)

```bash
pytest -q
```

기본 import 및 모델 옵션 구성이 정상인지 빠르게 확인합니다.

## 모델 선택

앱 상단 드롭다운에서 아래 무료 모델 중 하나를 선택해 사용할 수 있습니다.

- `google/gemini-2.0-flash-lite-preview-02-05:free`
- `google/gemma-3-27b-it:free`
- `mistralai/pixtral-12b:free`
- `mistralai/mistral-small-3.1-24b-instruct:free`
- `meta-llama/llama-3.3-70b-instruct:free`

## OpenRouter 가이드라인 준수 사항

API 호출 시 아래 설정을 사용합니다.

- Base URL: `https://openrouter.ai/api/v1`
- Header:
  - `HTTP-Referer`
  - `X-Title`

## 문제 해결

- `ModuleNotFoundError: No module named 'openai'`
  - 가상환경이 활성화된 상태에서 `pip install -r requirements.txt` 재실행
- `환경 변수(OPENROUTER_API_KEY)가 설정되지 않았습니다.`
  - `.env`에 `OPENROUTER_API_KEY`가 정확히 설정되었는지 확인
- 무료 모델에서 429/Rate Limit 발생
  - 잠시 후 재시도하거나 다른 무료 모델로 변경

## GitHub 업로드 체크리스트

- [x] `.env`는 `.gitignore`에 포함 (민감정보 커밋 방지)
- [x] `.venv`는 `.gitignore`에 포함
- [x] 실행/설치 방법 문서화 (`README.md`)
- [x] 예시 환경변수 파일 제공 (`.env.example`)
- [x] 라이선스 파일 포함 (`LICENSE`, MIT)
- [x] 간단한 스모크 테스트 포함 (`tests/test_smoke.py`)

### 첫 업로드 예시 명령어

```bash
git init
git add .
git commit -m "Initial commit: Streamlit PDF bookmark generator with OpenRouter models"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

## 보안 주의

API 키는 절대 저장소에 커밋하지 마세요.  
키가 채팅/스크린샷/로그 등에 노출되었다면 해당 키는 폐기하고 새 키를 발급받는 것을 권장합니다.
