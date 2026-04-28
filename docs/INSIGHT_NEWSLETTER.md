# StandUp Insight Newsletter (v2)

> 기존 일/주/월 보고를 대체하는 **AI 합성 주간 뉴스레터**.
> exaone3.5 cascade + pgvector RAG 기반.
> 기존 legacy agent 는 폐기하지 않고 STANDUP_MODE 로 분기.

## 아키텍처

```
[LogAnalyzer 9092]   ─┐
[GitHub Issues qa]   ─┼─→ Ingestion Hub ─→ ingestion_events (원본 색인)
[Auto-Tobe journal]  ─┤              │           ↓
[Auto-Tobe commits]  ─┘              ↓     newsletter_chunks (pgvector)
                              [임베딩 by nomic-embed-text]
                                      ↓
                  ┌──────  Synthesis 3-stage cascade  ──────┐
                  │ Stage 1: llama3.2:3b      (요약)         │
                  │ Stage 2: qwen2.5-coder:14b (분석/JSON)   │
                  │ Stage 3: exaone3.5:7.8b   (한국어 본문)  │
                  └──────────────────────────────────────────┘
                                      ↓
                            Newsletter (HTML, KPI, RAG refs)
                                      ↓
                  Email (Gmail SMTP) → recipients (report_types LIKE '%insight%')
                                      ↓
                  발송본 corpus_newsletters 자기참조 색인
```

## 핵심 설계 결정

### 1) 모드 스위치
`STANDUP_MODE` 환경변수:
- `legacy` — 기존 일/주/월 보고만
- `insight` — 신규 주간 뉴스레터만
- `both` — 둘 다 (전환기 권장 기본값)

### 2) 모델 cascade
24GB RAM macbook 에서 모든 모델이 동시에 들어가면 안 됨 — Ollama 가 자동 unload/load 한다.

| Stage | 모델 | 역할 | 메모리 |
|---|---|---|---|
| 1 | `llama3.2:3b` | 청크 요약 | 2GB |
| 2 | `qwen2.5-coder:14b` | 인사이트/패턴 추출 (JSON 출력) | 9GB |
| 3 | `exaone3.5:7.8b` | 최종 한국어 본문 작성 | 5GB |
| Embed | `nomic-embed-text` | 768-dim 임베딩 | 0.3GB |

### 3) RAG 컬렉션 분리
한 pgvector 테이블에 collection 컬럼으로 4 분리:
- `corpus_qa` — QA 이슈 본문 + 해결 댓글
- `corpus_logs` — LogAnalyzer 패턴
- `corpus_fixes` — Auto-Tobe journal + commit
- `corpus_newsletters` — 발송된 뉴스레터 (자기참조 학습용)

### 4) 원본 추적
모든 청크가 `event_id` 로 `ingestion_events` 를 참조 → 어느 본문 한 줄이든 원본 URL 까지 도달 가능.
LLM 출력의 `[REF:url]` 토큰을 후처리로 `<a href>` 로 치환.

## 운영 명령

### Alembic 마이그레이션 (pgvector 확장 포함)
```bash
alembic upgrade head
```
DB 사용자가 `CREATE EXTENSION` 권한이 없으면 DBA 가 사전 실행:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 수동 테스트

수집만:
```bash
curl -X POST http://localhost:9060/api/v1/insight/ingest/run
```

주간 발송 (실제 발송):
```bash
curl -X POST http://localhost:9060/api/v1/insight/weekly/run \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

dry-run (수신자 발송 X, DB 만 기록):
```bash
curl -X POST http://localhost:9060/api/v1/insight/weekly/run \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

뉴스레터 미리보기 (HTML):
```bash
curl http://localhost:9060/api/v1/insight/newsletters/{id}/preview
```

수집된 이벤트 목록:
```bash
curl 'http://localhost:9060/api/v1/insight/events?days=7&source_type=loganalyzer'
```

### 수신자 추가
```sql
INSERT INTO recipients (name, email, report_types, is_active)
VALUES ('홍길동', 'a@b.com', 'insight', true);
```
또는 기존 수신자에 추가:
```sql
UPDATE recipients SET report_types = 'all,insight' WHERE email = 'a@b.com';
```

## 디버깅

LLM 호출 실패 시: synthesis 가 raw 데이터로 fallback 본문 생성 → 발송은 계속 진행.
임베딩 실패 시: 청크는 저장되지만 embedding 컬럼 NULL → 다음 ingestion 사이클에서 재시도.

`synthesis_meta.stage{1,2,3}_ms` 로 단계별 시간 측정 가능. 합성 한 번에 보통 30~120초 (M5 24GB 기준).

## 향후 확장

1. **자동 효과 검증** (`docs/AGENT_DATA_CONTRACT.md` 참고) — fix 후 재발 여부 자동 라벨
2. **피드백 루프** — 메일의 👍/👎 링크가 현재 mailto 단순 링크. 추후 `/api/v1/insight/feedback?nl=...&v=up` 으로 교체 + 라벨이 RAG metadata 에 반영
3. **추가 source** — InfraWatcher, qadashboard 등 connector 추가는 `Connector` ABC 구현만으로 가능
