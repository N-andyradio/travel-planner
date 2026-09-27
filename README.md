# 국내 여행 추천 프로그램 (Gemini + Kakao Local API)

Gemini API와 Kakao Local API를 조합하여, 입력한 날짜에 맞는 국내 여행지를 추천하고
맛집 정보를 검색한 뒤 최종 여행 리포트를 생성하는 CLI 프로그램입니다.

## 1. 프로그램 개요

날짜를 입력하면 아래 순서로 동작합니다.

1. **Gemini API** — 해당 시기에 여행하기 좋은 국내 도시를 1곳 추천 (JSON)
2. **Kakao Local API** — 추천된 도시의 맛집 정보를 검색 (JSON)
3. **Gemini API** — 위 결과를 종합해 최종 여행 리포트를 Markdown으로 생성

결과물은 `results/` 폴더에 다음 두 파일로 저장됩니다.

- `{날짜}_travel_data.json` — 1차 추천 + 맛집 검색 결과 + 오류 요약
- `{날짜}_travel_plan.md` — 최종 여행 리포트

## 2. 실행 방법

### 2-1. 사전 준비

```bash
pip install -r requirements.txt
```

### 2-2. API 키 설정 방법

**절대로 API 키를 코드에 직접 작성하지 마세요.** `.env` 파일을 통해 관리합니다.

1. `.env.example` 파일을 복사해서 `.env` 파일을 만듭니다.

   ```bash
   cp .env.example .env
   ```

2. `.env` 파일을 열어 아래처럼 본인의 실제 키 값을 입력합니다.

   ```
   GEMINI_API_KEY="발급받은_제미나이_키"
   KAKAO_API_KEY="발급받은_카카오_REST_API_키"
   ```

3. 키 발급처
   - Gemini API 키: https://aistudio.google.com/apikey
   - Kakao REST API 키: https://developers.kakao.com → 내 애플리케이션 → 앱 키 → **REST API 키** 사용
     (Kakao Local API를 쓰려면 해당 애플리케이션에서 "카카오맵" 관련 API 사용 설정이 되어 있어야 합니다.)

> ⚠️ `.env` 파일은 `.gitignore`에 이미 등록되어 있어 Git에 커밋되지 않습니다.
> 절대 `.env` 파일이나 키 값을 README, 커밋 로그, 결과 파일 등 어디에도 직접 노출하지 마세요.

### 2-3. 실행

```bash
python travel_planner.py -date "2026-03-15"
```

실행하면 아래와 같은 진행 로그가 출력됩니다.

```
[1/3] 1차 추천 생성 중(Gemini)...
  - recommended_city: "제주"
[2/3] 맛집 검색 중(Kakao Local)...
  - 맛집 5곳 검색 완료
[3/3] 최종 리포트 생성 중(Gemini)...
  - 리포트 생성 완료

완료! results/2026-03-15_travel_plan.md 를 확인하세요.
원본 데이터: results/2026-03-15_travel_data.json
```

## 3. 결과물 확인 방법

- `results/{날짜}_travel_plan.md` 를 열어 최종 여행 리포트를 확인합니다.
  (추천 지역, 추천 이유, 날씨 요약, 행사/축제, 맛집 추천, 1일 일정 제안, 오류 요약 섹션 포함)
- `results/{날짜}_travel_data.json` 을 열면 원본 데이터(1차 추천 JSON, 맛집 검색 결과,
  오류 목록)를 확인할 수 있습니다.

## 4. 에러 처리 정책

| 상황 | 동작 |
|---|---|
| API 키 미설정 | 프로그램 즉시 종료, 설정 방법 안내 출력 |
| 날짜 형식 오류 | 사용법 출력 후 종료 |
| Kakao Local API 실패 (네트워크/인증/쿼터) | 맛집 섹션 "데이터 없음" 처리, 리포트 생성은 계속 진행 |
| 맛집 검색 결과 0건 | "데이터 없음" 처리 후 다음 단계로 진행 |
| Gemini JSON 파싱 실패 | 1회 재시도, 그래도 실패하면 기본값으로 진행 |

모든 오류는 `results/*.json`의 `errors` 배열과 리포트의 "오류 요약" 섹션에 기록됩니다.

## 5. 보안 주의사항

- API 키는 반드시 `.env` 파일 또는 환경변수로만 관리합니다.
- `.env` 파일은 Git에 커밋하지 않습니다 (`.gitignore`에 포함되어 있음).
- 스크린샷, 로그, 제출물 어디에도 실제 키 값을 노출하지 않습니다.
