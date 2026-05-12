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

## tech_trend 채널 (PR1~3) — Medium Digest + 외부 뉴스 → HopenVision 자동 제안

기존 3 source(loganalyzer/github_qa/auto_tobe) 외에 **외부 기술 동향**을 같은 hub 로
흡수하는 채널이 추가되었다.

```
[medium-digest-agent reports/*.md] ─┐
                                     ├─→ TechTrendConnector ─→ corpus_tech
[Google News RSS / Naver News API] ─┘                                │
                                                                    ↓
                                                  Synthesis (변경 없음)
                                                                    ↓
                                  SynthesisOutput.tech_topics (키워드별 묶음)
                                              ↓                     ↓
                            Newsletter '이번 주 기술 토픽' 섹션      ↓
                                                                    ↓
                            HopenVisionProposalService.propose_from_tech_topics()
                                              ↓
                            HopenVisionProposal (cluster_key='tech:<slug>')
                                              ↓
                                  TECH_TREND_AUTO_DEV_PLAN=true 면
                                              ↓
                                          DevPlan(DRAFT) 자동 초안화
```

핵심 환경변수:

| Key | 기본값 | 설명 |
|-----|-------|------|
| `TECH_TREND_ENABLED` | `false` | connector 활성화 |
| `TECH_TREND_KEYWORDS` | `java,spring,react` | 콤마 구분 검색·필터 키워드 |
| `MEDIUM_DIGEST_REPORTS_DIR` | `""` | medium-digest-agent 가 만든 `reports/*.md` 경로 |
| `TECH_NEWS_MAX_PER_KEYWORD` | `5` | 키워드당 뉴스 검색 결과 상한 |
| `NAVER_CLIENT_ID/SECRET` | `""` | 미설정 시 Google News RSS 만 사용 |
| `TECH_TREND_AUTO_DEV_PLAN` | `true` | 합성 후 즉시 DevPlan 초안화 |
| `TECH_TREND_MAX_TOPICS_PER_RUN` | `3` | 1회 합성당 LLM 호출 최대 토픽 수 |

운영 메모:
- **Gmail 수신은 medium-digest-agent 가 전담** — StandUp 은 산출 markdown 만 import
- 외부 뉴스 검색은 AllergyInsight 와 동일하게 RSS 기반 (별도 유료 키 불필요)
- HopenVision 제안 캐시는 `cluster_key=tech:<slug>` 로 클러스터 기반 제안과 분리
- 대시보드 `/dashboard/insights` 의 ④번 섹션에서 자동 생성된 제안 + DevPlan 링크 확인

## HopenVision-Tight 게이트 (PR4)

PR3 까지는 `tech_trend_keywords` 매칭만 통과하면 모든 토픽이 LLM 제안 → DevPlan 초안화
경로를 탔다. 이 때문에 Autonomous-QA-Agent / Unity / 머신비전 같이 HopenVision 과
무관한 토픽도 제안 큐에 올라와 범위가 너무 확장되었다.

PR4 부터는 토픽 → 제안 사이에 **HopenVision 적합도 게이트**가 추가된다.

```
TechTopic (키워드+디지스트+뉴스)
   ↓ stack 키워드 매칭 (0~60점, 결정적)
   ↓ LLM 분류 (0~40점, 모델=qwen2.5-coder)
   ↓ score >= HOPEN_BRIEF_FITNESS_THRESHOLD ?
   ├─ Yes → HopenVisionProposalService 로 진입, repo index 와 fitness 결과를
   │         프롬프트에 동봉. proposal 행에 fitness_score/impact_area/effort_hours 저장.
   └─ No  → filtered_out 으로 표시 (DB 저장 X, 로그에만 남김)
```

핵심 입력은 **로컬 hopenvision clone** 의 트리 인덱스:
- Spring `@RestController` / `@Entity` / `@Service` 클래스 + 패키지 + 라우트
- `web-admin/web-user/web-shared` 의 페이지 컴포넌트 목록

인덱스는 `BASE_DIR/.cache/hopenvision_repo_index.json` 에 24h TTL 로 캐시.
LLM 프롬프트에 `condense_for_prompt(idx)` 결과가 들어가 모델이 *실제 모듈명* 으로
candidate_modules 를 제안하게 한다.

| Key | 기본값 | 설명 |
|-----|-------|------|
| `HOPENVISION_REPO_PATH` | `""` | HopenVision 로컬 clone 경로 (미설정 시 게이트는 stack 매칭만으로 동작) |
| `HOPENVISION_STACK_TAGS` | `java,spring,spring-boot,react,postgresql,typescript,jpa,jwt,docker` | 토픽 텍스트와 매칭할 스택 태그 |
| `HOPEN_BRIEF_FITNESS_THRESHOLD` | `60` | 0~100. 미달 토픽은 LLM 제안 생성 skip |
| `HOPEN_REPO_INDEX_TTL_HOURS` | `24` | repo index 캐시 TTL |

운영 메모:
- 1회 실행에 LLM 호출이 (토픽당 게이트 1회 + 제안 1회) 발생 — 게이트 모델은
  `OLLAMA_MODEL_ANALYZE` (기본 qwen2.5-coder:14b), 제안 모델은 `OLLAMA_MODEL_COMPOSE`.
  스택 매칭이 0 인 토픽은 게이트 LLM 호출도 skip 되므로 비용 가드.
- `HopenVisionProposal.fitness_score / impact_area / effort_hours` 컬럼이 추가됨
  — 대시보드에서 "참고 보관" 탭 / 제안 정렬에 활용 (PR5 에서 UI 노출).
- 게이트를 끄려면 `HOPEN_BRIEF_FITNESS_THRESHOLD=0` 으로 설정 (PR3 동작 복원).

## 상세 산출물 (PR5) — Mermaid · 적용 사례 · PoC 코드 힌트

PR4 의 적합도 게이트를 통과한 토픽에 대해 *카드형 메일 한 토픽 = 한 페이지* 수준의
상세 산출물을 추가로 생성한다. 모든 결과는 `hopenvision_proposals` 행에 함께 저장.

`app/synthesis/tech_brief_detailer.py` 가 세 단계를 묶어 호출:

| 단계 | 산출물 | 모델/외부 호출 |
|------|--------|----------------|
| 1) Mermaid 다이어그램 | `diagram_mermaid` (As-Is / To-Be subgraph 형식) | `OLLAMA_MODEL_ANALYZE` |
| 2) 적용 사례 | `case_studies` (`title/url/image_url/description/site_name/source`) | 뉴스 article URL 에서 og:image / canonical 추출 (`article_image_extractor`) |
| 3) PoC 코드 힌트 | `code_hints` (`file/change_sketch/snippet`) | `OLLAMA_MODEL_ANALYZE` — repo index 파일 경로 외 항목은 ⚠ 표시 |

각 단계는 독립 try/except — 한 단계가 실패해도 다른 산출물은 정상 저장된다.
`enable_detail=False` 로 호출하면 detailer 자체를 skip (테스트·디버그용).

새 메일 템플릿 `app/templates/hopen_tech_brief.html` 가 토픽 1~3 건을 카드로 표현:
- 적합도 / 예상공수 배지, priority / impact_area 배지
- Mermaid 코드블록 + `mermaid.live` 링크 (Gmail 에서 직접 렌더는 미지원, 코드 복붙으로 시각화)
- 사례 카드 (썸네일 + 제목 + 사이트명 + 짧은 설명)
- 코드 힌트 (실파일 경로 + 변경 스케치 + 옵션 snippet)

PR6 에서 일일 cron 으로 이 템플릿을 호출하는 별도 `[HopenTechBrief]` 메일 채널 추가 예정.

## 향후 확장

1. **자동 효과 검증** (`docs/AGENT_DATA_CONTRACT.md` 참고) — fix 후 재발 여부 자동 라벨
2. **피드백 루프** — 메일의 👍/👎 링크가 현재 mailto 단순 링크. 추후 `/api/v1/insight/feedback?nl=...&v=up` 으로 교체 + 라벨이 RAG metadata 에 반영
3. **추가 source** — InfraWatcher, qadashboard 등 connector 추가는 `Connector` ABC 구현만으로 가능
