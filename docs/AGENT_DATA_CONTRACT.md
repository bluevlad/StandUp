# Agent Data Contract — Insight Newsletter (v2)

> StandUp 의 Insight Newsletter 가 외부 agent 데이터를 **pull** 방식으로 수집할 때
> 각 agent 에 요청하는 형식 가이드. 추가 push 엔드포인트 미운영 — 모든 수집은
> StandUp 측에서 connector 가 호출/조회.

## 공통 원칙

- **외부 agent 의 추가 구현 최소화** — 기존 산출물(GitHub Issues, log DB, fix journal, git commit)을 그대로 재활용.
- **원본 추적성 보장** — 모든 이벤트는 `source_url` 을 가지고, 뉴스레터에서 클릭 한 번에 원본까지 도달.
- **멱등성** — 같은 데이터 반복 수집 시 중복 행 X (`(source_type, source_id, content_hash)` UNIQUE).

## 1. Autonomous-QA-Agent (외부 PC, 새벽 스케줄)

### 채널: GitHub Issues + (선택) qadashboard 공유 DB

QA Agent 가 새벽 점검 후 결과를 GitHub Issues 에 자동 등록한다는 가정.

### 요청사항

**라벨 표준화** (필수):
- `qa-agent` — 모든 QA Agent 등록 이슈에 부착 (StandUp 이 이 라벨로 필터)
- `severity:critical` / `severity:high` / `severity:medium` / `severity:low` — 심각도
- `service:academy` / `service:allergy` / ... — 대상 서비스 식별

**Issue body 권장 형식**:
```markdown
## 점검 요약
2026-04-28 새벽 정기 점검 결과

## machine-readable
\`\`\`yaml
qa_run_id: 2026-04-28-0300
target_service: allergy
test_suite: smoke
pass_rate: 0.94
duration_sec: 132
failed_cases:
  - login_token_refresh
  - recipe_search_empty
\`\`\`

## 상세
... (사람이 보는 본문) ...
```

### StandUp 측 활용

`app/ingestion/connectors/github_qa.py` 가 PyGithub 로 직접 호출:
```python
issues = repo.get_issues(state="all", labels=["qa-agent"], since=...)
```

## 2. LogAnalyzer (macbook Docker, 9092)

### 채널: 기존 HTTP API (별도 구현 불필요 — **현재 운영 중**)

LogAnalyzer 9092 가 노출하는 라우트 중 다음을 사용:

| 엔드포인트 | 용도 |
|---|---|
| `GET /api/errors/summary?hours=N` | 기간 KPI (total/critical/high/...) |
| `GET /api/errors/groups?status=open&sort_by=occurrence_count` | 오류 그룹 top N — fingerprint, service_group, severity, occurrence_count, github_issue_url |
| `GET /api/errors/types?days=N` | error_type 분포 |
| `GET /api/dashboard/summary` | 서비스별 24h 통계 |

### 응답 핵심 필드 (이미 모두 제공됨)

```json
{
  "id": 14,
  "fingerprint": "9d3837dc212e6c26",
  "container_name": "unmong-gateway",
  "service_group": "Gateway",
  "error_type": "proxy_error",
  "severity": "HIGH",
  "sample_message": "...",
  "first_seen": "2026-03-31T07:34:22Z",
  "last_seen": "2026-04-28T08:02:56Z",
  "occurrence_count": 80391,
  "status": "open",
  "github_issue_url": null
}
```

### LogAnalyzer 측 추가 요청 (선택)

향후 재발 추적 정확도 향상을 위해:
- `GET /api/errors/groups/{fingerprint}/timeline?since=...` — 패턴별 발생 분포 (있으면 RAG 검색 개선)
- `pattern_signature` 가 fingerprint 와 동의어로 안정 유지 (해시 알고리즘 변경 시 재발 추적 깨짐 방지)

## 3. Auto-Tobe-Agent (macbook 로컬)

### 채널 A: Fix Journal (Markdown 파일)

`AUTO_TOBE_JOURNAL_GLOB` 환경변수의 glob 패턴으로 매칭되는 모든 .md 파일.

**권장 형식** (entry 별 YAML front-matter):
```markdown
## 2026-04-28 09:14 fix-{repo}-{sha8}

\`\`\`yaml
target_service: allergy
original_error: "AttributeError: 'NoneType' object has no attribute 'name'"
files_changed:
  - app/api/ingredient.py
  - app/schemas/ingredient.py
fix_type: null-handling
before_log_signature: "534c11c4240a341e"  # LogAnalyzer fingerprint 와 매칭하면 효과 검증 자동
\`\`\`

원본이 None 일 때 .name 접근 → AttributeError. Optional 처리로 수정.
```

### 채널 B: Git commits with Root-Cause footer

CLAUDE.md 의 fix 커밋 규약을 그대로 활용:
```
fix(api): 알레르기 성분 조회 시 None 응답 처리

- ingredient가 Optional인데 None 체크 없이 .name 접근하여 AttributeError 발생

Root-Cause: null-handling
Error-Category: logic-error
Affected-Layer: backend/api
```

`git log --grep="Root-Cause:"` 로 자동 수집. 추가 구현 0.

## 4. (제외) InfraWatcher

이번 v2 범위에서 제외. 필요 시 connector 추가는 동일 패턴으로 가능.

## 자동 효과 검증 로직 (구현됨 — `app/services/fix_verification_service.py`)

1. Auto-Tobe fix 이벤트에서 fingerprint 추출:
   - journal — YAML `before_log_signature: "..."` (복수 entry 는 모두 수집)
   - commit — footer `Before-Log-Signature: <fingerprint>` (선택, Root-Cause 옆에 추가)
2. fix 시점 + `FIX_VERIFICATION_WINDOW_DAYS`(기본 7일) 동안 LogAnalyzer
   `error_group` 이벤트에서 같은 fingerprint 재등장 여부를 조회
3. 판정 (결정적, LLM 무관):
   - `verified` ✅ window 경과 + 재발 없음
   - `recurred` ❌ window 내 재등장 (최초 시각·횟수 기록)
   - `pending` ⏳ window 미경과
   - `unlinked` fingerprint 연결 정보 없음 → 검증 불가
4. 뉴스레터 반영 — stage-3 compose 에 `[효과 검증]` 블록으로 주입되어
   LLM 은 이 판정만 인용 (임의 판정 금지). `newsletters.kpis.fix_verifications`
   에도 저장되어 API 로 조회 가능.
5. 조회: `GET /api/v1/insight/verifications?lookback_days=14`

확정 판정(verified/recurred)은 `corpus_fixes` 청크의 `metadata_json.verification`
에 누적되어, retrieval 우선순위에 반영됨.

> commit footer 예시:
> ```
> Root-Cause: null-handling
> Before-Log-Signature: 534c11c4240a341e
> Affected-Layer: backend/api
> ```
