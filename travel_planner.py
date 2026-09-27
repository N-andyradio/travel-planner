#!/usr/bin/env python3
"""
travel_planner.py

Gemini API + Kakao Local API를 조합한 국내 여행 추천 CLI 프로그램.

흐름:
  1) Gemini API로 입력 날짜에 맞는 여행지(도시) 1차 추천 (JSON)
  2) Kakao Local API로 추천 도시의 맛집 검색 (JSON)
  3) Gemini API로 위 결과를 종합해 최종 여행 리포트 생성 (Markdown)
  4) results/ 폴더에 원본 데이터(JSON)와 최종 리포트(Markdown) 저장

실행 예시:
  python travel_planner.py -date "2026-03-15"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# 0. 환경 설정
# ─────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

RESULTS_DIR = Path(__file__).parent / "results"


# ─────────────────────────────────────────────────────────────
# 1. 유틸리티
# ─────────────────────────────────────────────────────────────

def log(msg: str):
    print(msg, flush=True)


def check_required_keys():
    """API 키 미설정 시 즉시 종료 + 설정 방법 안내."""
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not KAKAO_API_KEY:
        missing.append("KAKAO_API_KEY")

    if missing:
        log("[오류] 다음 API 키가 설정되지 않았습니다: " + ", ".join(missing))
        log("")
        log("설정 방법:")
        log("  1) 프로젝트 폴더에 .env 파일을 만듭니다. (.env.example 참고)")
        log("  2) 아래와 같이 키를 작성합니다.")
        log('       GEMINI_API_KEY="발급받은_제미나이_키"')
        log('       KAKAO_API_KEY="발급받은_카카오_REST_API_키"')
        log("  3) 다시 실행합니다.")
        sys.exit(1)


def validate_date(date_str: str) -> str:
    """YYYY-MM-DD 형식 검증. 실패 시 사용법 출력 후 종료."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        log(f'[오류] 날짜 형식이 올바르지 않습니다: "{date_str}"')
        log('사용법: python travel_planner.py -date "YYYY-MM-DD"')
        log('예시:   python travel_planner.py -date "2026-03-15"')
        sys.exit(1)


def extract_json(text: str) -> dict:
    """
    LLM 응답 텍스트에서 JSON 객체만 추출해 파싱한다.
    코드블록(```json ... ```)이 섞여 와도 처리할 수 있도록 방어적으로 작성.
    """
    cleaned = text.strip()

    # ```json ... ``` 또는 ``` ... ``` 코드블록 제거
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # 첫 '{' 부터 마지막 '}' 까지만 추출 (앞뒤 잡담 방어)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    return json.loads(cleaned)


# ─────────────────────────────────────────────────────────────
# 2. Gemini API 호출 함수
# ─────────────────────────────────────────────────────────────

def call_gemini(prompt: str, json_mode: bool = False) -> str:
    """
    Gemini API를 호출해서 텍스트 응답을 반환한다.
    json_mode=True 이면 Gemini가 순수 JSON만 출력하도록 강제한다.
    (프롬프트 안에 "JSON"이라는 단어가 있는지로 판단하지 않고,
     호출하는 쪽에서 명시적으로 지정한다.)
    네트워크/인증/쿼터 오류는 호출부에서 처리할 수 있도록 예외를 그대로 던진다.
    """
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.7,
            "response_mime_type": "application/json" if json_mode else "text/plain",
        },
    }

    response = requests.post(
        GEMINI_URL, headers=headers, params=params, json=payload, timeout=60
    )
    response.raise_for_status()

    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Gemini 응답 구조가 예상과 다릅니다: {data}") from e


def get_travel_recommendation(date_str: str, errors: list) -> dict:
    """
    [1단계] 날짜를 입력받아 추천 도시/날씨/행사/이유를 JSON으로 받아온다.
    JSON 파싱 실패 시 최대 1회 재시도.
    """
    base_prompt = f"""당신은 국내 여행 전문가입니다. {date_str}에 여행하기 좋은
국내 여행지를 1곳 추천해 주세요.

반드시 아래 스키마를 따르는 JSON만 출력하세요. 다른 설명, 코드블록 표시 없이
순수 JSON 객체 하나만 출력해야 합니다.

{{
  "recommended_city": "도시명 (예: 제주, 강릉)",
  "weather": "해당 시기 일반적인 날씨 요약 (한 문장)",
  "events": ["행사/축제 후보 1", "행사/축제 후보 2"],
  "reason": "추천 근거 2~4문장"
}}
"""

    prompt = base_prompt
    last_error = None

    for attempt in range(2):  # 최초 시도 + 재시도 1회
        try:
            raw_text = call_gemini(prompt, json_mode=True)
            parsed = extract_json(raw_text)

            # 필수 키 검증
            required_keys = {"recommended_city", "weather", "events", "reason"}
            if not required_keys.issubset(parsed.keys()):
                raise ValueError(f"필수 키 누락: {parsed.keys()}")

            return parsed

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt == 0:
                log("  - JSON 파싱 실패, 재시도 중...")
                prompt = (
                    base_prompt
                    + "\n\n중요: 반드시 필수 키(recommended_city, weather, "
                      "events, reason)만 포함한 순수 JSON으로 다시 출력하세요."
                )
                continue
            else:
                errors.append({
                    "step": "recommendation",
                    "type": "JSON_PARSE_ERROR",
                    "message": str(last_error),
                })
                log("  - JSON 파싱 재시도도 실패. 기본값으로 진행합니다.")
                return {
                    "recommended_city": "정보 없음",
                    "weather": "정보 없음",
                    "events": [],
                    "reason": "추천 정보를 생성하지 못했습니다.",
                }
        except requests.exceptions.RequestException as e:
            errors.append({
                "step": "recommendation",
                "type": "NETWORK_ERROR",
                "message": str(e),
            })
            log(f"  - 네트워크 오류: {e}")
            return {
                "recommended_city": "정보 없음",
                "weather": "정보 없음",
                "events": [],
                "reason": "네트워크 오류로 추천 정보를 생성하지 못했습니다.",
            }


def generate_final_report(
    date_str: str, recommendation: dict, restaurants: list, errors: list
) -> str:
    """[3단계] 1차 추천 + 맛집 목록을 종합해 최종 Markdown 리포트를 생성한다."""

    restaurants_text = (
        json.dumps(restaurants, ensure_ascii=False, indent=2)
        if restaurants
        else "없음 (검색 결과 0건 또는 API 실패)"
    )

    prompt = f"""아래 정보를 바탕으로 국내 여행 추천 리포트를 Markdown으로 작성하세요.

날짜: {date_str}
1차 추천 정보(JSON): {json.dumps(recommendation, ensure_ascii=False)}
맛집 검색 결과: {restaurants_text}

리포트는 반드시 아래 형식(제목/섹션)을 따르세요:

# {date_str} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 1일 일정 제안
(오전/오후/저녁 순서로 간단히 제안)

주의:
- 맛집 검색 결과가 없으면 "맛집 추천" 섹션에 "데이터 없음"이라고 표기하세요.
- 순수 Markdown 텍스트만 출력하고, 코드블록 표시(```)는 사용하지 마세요.
"""

    try:
        report_md = call_gemini(prompt, json_mode=False)
        return report_md.strip()
    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "report_generation",
            "type": "NETWORK_ERROR",
            "message": str(e),
        })
        log(f"  - 리포트 생성 중 네트워크 오류: {e}")
        return build_fallback_report(date_str, recommendation, restaurants)
    except ValueError as e:
        errors.append({
            "step": "report_generation",
            "type": "RESPONSE_ERROR",
            "message": str(e),
        })
        log(f"  - 리포트 생성 중 응답 오류: {e}")
        return build_fallback_report(date_str, recommendation, restaurants)


def build_fallback_report(date_str: str, recommendation: dict, restaurants: list) -> str:
    """LLM 리포트 생성이 완전히 실패했을 때 쓰는 최소한의 대체 리포트."""
    events = recommendation.get("events", [])
    events_md = "\n".join(f"- {e}" for e in events) if events else "- 데이터 없음"

    if restaurants:
        rest_md = "\n".join(
            f"- {r.get('name', '이름없음')} ({r.get('address', '주소 정보 없음')})"
            for r in restaurants
        )
    else:
        rest_md = "- 데이터 없음"

    return f"""# {date_str} 국내 여행 추천 리포트

## 추천 지역
{recommendation.get('recommended_city', '데이터 없음')}

## 추천 이유
{recommendation.get('reason', '데이터 없음')}

## 날씨 요약
{recommendation.get('weather', '데이터 없음')}

## 행사/축제
{events_md}

## 맛집 추천
{rest_md}

## 1일 일정 제안
- 리포트 자동 생성에 실패하여 상세 일정은 제공되지 않았습니다.
"""


# ─────────────────────────────────────────────────────────────
# 3. Kakao Local API 호출 함수
# ─────────────────────────────────────────────────────────────

def search_restaurants(city: str, errors: list, limit: int = 5) -> list:
    """
    [2단계] Kakao Local API로 도시 기준 맛집을 검색한다.
    실패해도 프로그램은 중단되지 않고 빈 리스트를 반환한다.
    """
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {
        "query": f"{city} 맛집",
        "size": limit,
    }

    try:
        response = requests.get(
            KAKAO_LOCAL_URL, headers=headers, params=params, timeout=15
        )

        if response.status_code in (401, 403):
            errors.append({
                "step": "place_search",
                "type": "AUTH_ERROR",
                "message": f"HTTP {response.status_code}",
            })
            log(f"  - 오류: 인증 실패({response.status_code}). 키 설정을 확인하세요.")
            log("  - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
            return []

        response.raise_for_status()
        data = response.json()
        documents = data.get("documents", [])

        if not documents:
            errors.append({
                "step": "place_search",
                "type": "EMPTY_RESULT",
                "message": f"0 results for query={city} 맛집",
            })
            log("  - 검색 결과 0건. '데이터 없음'으로 다음 단계로 진행합니다.")
            return []

        restaurants = []
        for doc in documents:
            restaurants.append({
                "name": doc.get("place_name", ""),
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_name", ""),
                "url": doc.get("place_url", ""),
                "x": doc.get("x"),  # 경도
                "y": doc.get("y"),  # 위도
            })

        log(f"  - 맛집 {len(restaurants)}곳 검색 완료")
        return restaurants

    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "place_search",
            "type": "NETWORK_ERROR",
            "message": str(e),
        })
        log(f"  - 네트워크 오류: {e}")
        log("  - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        return []


# ─────────────────────────────────────────────────────────────
# 4. 메인 파이프라인
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Gemini + Kakao Local API 기반 국내 여행 추천 프로그램"
    )
    parser.add_argument(
        "-date", "--date", dest="date", required=True,
        help='여행 날짜 (형식: "YYYY-MM-DD")'
    )
    args = parser.parse_args()

    date_str = validate_date(args.date)
    check_required_keys()

    errors = []
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # [1/3] 1차 추천 생성
    log("[1/3] 1차 추천 생성 중(Gemini)...")
    recommendation = get_travel_recommendation(date_str, errors)
    log(f'  - recommended_city: "{recommendation.get("recommended_city")}"')

    # [2/3] 맛집 검색
    log("[2/3] 맛집 검색 중(Kakao Local)...")
    city = recommendation.get("recommended_city", "")
    if city and city != "정보 없음":
        restaurants = search_restaurants(city, errors)
    else:
        restaurants = []
        errors.append({
            "step": "place_search",
            "type": "SKIPPED",
            "message": "추천 도시 정보가 없어 맛집 검색을 건너뜀",
        })
        log("  - 추천 도시 정보가 없어 맛집 검색을 건너뜁니다.")

    # [3/3] 최종 리포트 생성
    log("[3/3] 최종 리포트 생성 중(Gemini)...")
    report_md = generate_final_report(date_str, recommendation, restaurants, errors)

    # errors 섹션을 리포트 끝에 추가
    errors_md = "\n## 오류 요약(errors)\n"
    if errors:
        for err in errors:
            errors_md += f"- [{err['type']}] ({err['step']}) {err['message']}\n"
    else:
        errors_md += "- 없음\n"
    report_md = report_md.rstrip() + "\n" + errors_md

    log("  - 리포트 생성 완료")

    # 결과 저장
    json_path = RESULTS_DIR / f"{date_str}_travel_data.json"
    md_path = RESULTS_DIR / f"{date_str}_travel_plan.md"

    result_data = {
        "date": date_str,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    log("")
    log(f"완료! {md_path} 를 확인하세요.")
    log(f"원본 데이터: {json_path}")


if __name__ == "__main__":
    main()
