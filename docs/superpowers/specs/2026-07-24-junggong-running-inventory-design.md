# 준공 기반 러닝재고 순부족 모델 — 설계 (spec)

- 날짜: 2026-07-24
- 관련 메모리: `hub-permit-integration`, `agongmap-data-pipeline`, `aptweather-project`, `shinssam-lecture-archive`
- 선행: 2026-07-23 건축HUB 통합(인허가 meas + 착공 fwd_far) 구현 완료 but **activate off로 미배포**. 본 설계가 그 점수 로직을 대체한다.

## 배경 / 왜 다시 설계하나

2026-07-23 통합은 `dC`(인허가)를 시군구 실측으로 교체하고 forward를 착공 기반 2→4년으로 확장했다. 그런데 실호출 진단(2026-07-24)에서 두 가지가 드러났다:

1. **착공일(stcnsDay)은 미래공급 신호로 못 쓴다.** 활성 개발지(화성·평택) 실측: 미래 준공예정 37단지·약 4만 세대가 **전부 착공일이 비어 있음**. 착공 기반 `fwd_far`는 이 물량을 거의 다 놓친다.
2. **`useInsptSchedDay`(사용검사예정일=준공예정)이 진짜 미래공급 신호다.** 인허가 단지의 86%가 준공예정일을 갖고, 2026~2030에 고르게 분포. 추정(착공+3.25년)도, 분양데이터 대조도 불필요.

또한 단지 레코드에 인허가일·착공일·준공일·준공예정일이 **한 레코드에 다 있어**(`mgmHsrgstPk` = 단지 PK), 단지를 **최신 단계 하나로만** 분류하면 인허가/착공/준공/입주예정 간 **중복이 원천 소멸**한다.

→ 결론: 건축HUB **단일 소스**로, 단지를 준공(과거)·준공예정(미래)으로 분류하고, 신쌤 **러닝재고 모형**에 공급 입력으로 넣어 **누적 순부족**을 산출한다.

## 설계 결정 (브레인스토밍 2026-07-24)

- **Q1=C** 누적 순부족으로 재구축 + 시간가중
- **Q2=A** 적정(수요) 유지 + 준공 기반 공급계열로 재캘리브레이션
- **Q3=B** 러닝재고 모형 (`재고 = max(0, 이전 + 준공 − 적정)`)
- **Q4=A** 미래 준공예정에 신뢰 감쇠 (먼 예정일수록 낮게)
- **Q5=B** 상세 리스트 = 미래(준공예정) + 최근 과거(준공) 2섹션
- **Q6=A** 기존 Task6/7 점수 변경을 되돌리고 새로 구축, inactive 롤아웃 유지

## 목표 / 비목표

**목표**: 생활권별 순부족을 건축HUB 단일소스·단지 무중복·러닝재고로 산출. 가격 예측력을 주는 신쌤 적정 모형은 유지하되 공급계열을 준공 실측으로 정밀화.

**비목표 (YAGNI)**: odcloud 입주예정·청약홈 분양·착공일 사용(전부 제거). 수요 정의 교체(적정 유지). 인허가/착공을 별도 점수항목으로 세는 것(준공예정에 흡수).

## 핵심 모델 (생활권별)

```
# 과거: 신쌤 러닝재고 (앵커 t0 ~ 현재)
I(t) = max(0, I(t-1) + 준공(t) - 적정_z)          # 준공(t) = 분기 t 준공 세대(useInsptDay)
I_now = I(현재분기)                                 # 현재 재고 버퍼(과잉 잔량), ≥0

# 미래: 순부족
순부족_z = Σ_{t=미래분기}( 적정_z )
         - ( I_now + Σ_{t=미래분기} 준공예정(t) * conf(t) )
```
- `적정_z`: 생활권 z의 신쌤 캘리브 적정물량(분기당). 아래 재캘리브레이션.
- `준공예정(t)`: 분기 t에 준공 예정인 세대(useInsptSchedDay). `conf(t)`: 신뢰 감쇠(0~1), 먼 미래일수록↓.
- **부호**: 순부족 > 0 = 부족(발산막대 오른쪽), < 0 = 과잉(왼쪽). 기존 시그니처 방향 유지.
- **해석**: "앞으로 필요한 양 − (지금 쌓인 재고 + 앞으로 들어올 양)". 재고 버퍼가 미래 공급을 뒷받침 = 신쌤 이론 정합.

**정확한 파라미터(구현 시 캘리브레이션 대상, 순위 검증으로 확정)**:
- 앵커 t0: 준공 이력 시작(~2010년대 초). `max(0)` 소진으로 초기값 영향 씻김.
- 미래 창: 준공예정 있는 분기까지(~2030), `conf(t)`가 먼 분기를 자연 소멸시킴.
- `conf(t)` 곡선: 기본 후보 = 1년 내 1.0에서 시작해 매년 일정 비율 감쇠(예: -20%/년), ~5년에서 ≈0. 실제 준공예정→실제준공 슬립 통계로 보정 가능(향후).

## 단지 무중복 분류 (핵심)

각 단지(mgmHsrgstPk)를 **가장 진행된 단계 하나로만**:
- `useInsptDay`(실제 준공) 있음 → **과거 공급**, 준공 분기에 배치.
- 없고 `useInsptSchedDay`(준공예정) 있음 → **미래 공급**, 준공예정 분기에 배치.
- 둘 다 없음 → **미정**(점수 미반영, 리스트엔 "미정" 표기).
착공일·인허가일은 점수에 **직접 안 씀**(분류/표시 참고용). → 인허가·착공·준공·입주 중복 0.

## 컴포넌트 / 파일

**재사용 (변경 없음/최소)**
- `tools/fetch_hub_permits.py` — 수집 엔진(페이싱·curl·에러분류·`meta['scanned']` 재개·타깃도출·부천 unresolved·PK dedup) 그대로. **버킷만 교체**(아래).
- `.github/workflows/update-hub.yml`, `hub-probe.yml` — 그대로.
- activate/존별 완결성 게이트 메커니즘 — 그대로(새 롤아웃에 재사용).
- `tools/hub_common.py` — `to_quarter`·`dedupe`·`apt_records` 유지. `shift_quarter`(착공+13) **삭제**(불필요).

**교체 (수집 버킷)**
- `fetch_hub_permits.py` 집계: `permit_q`(apprvDay)·`start_q`(stcnsDay) → **`done_q`(useInsptDay)·`sched_q`(useInsptSchedDay)**. 단지 PK 최신단계 1회 분류. `hub_permits.json` 스키마:
  ```json
  {"meta":{"fetched","mode","unresolved_legacy","scanned","activate"},
   "sgg":{"<code>":{"name","done_q":{"YYYYQn":세대},"sched_q":{"YYYYQn":세대}}},
   "productive_bjdong":[...]}
  ```

**재작성 (점수)**
- `tools/update_adv_data.py` `hub_derive` → 생활권별 **준공 분기시계열 `done`** + **준공예정 분기시계열 `sched`**를 `adv['permits']`에 주입(러닝재고 입력). activate/완결성 게이트 유지. 원시 단지 레코드는 번들 제외.
- `tools/make_zone_pages.py` `calc()` → 3항목 가중합 제거, **러닝재고 순부족** 산출(위 모델). `index.html` `scCalc()` 동치 미러.
- `tools/estimate_ref_inventory.py` → 적정을 **준공 기반 공급계열로 재피팅**(기존 입주물량 계열 → 준공 계열).
- `tools/verify_dc_rankdiff.py` → `verify_rankdiff.py`로 교체: 구모델 vs 신모델 36존 순위 diff + 순부족 성분 진단.

**상세페이지 리스트**
- `make_zone_pages.py` 단지 리스트 = 2섹션: **앞으로 들어올 물량**(sched 단지, "YYYY.MM 예정"/"미정"/먼 건 "지연가능" 회색) + **최근 들어온 물량**(최근 N년 done 단지).

## 데이터 흐름

```
HUB API ─curl─▶ fetch_hub_permits.py(done_q/sched_q) ─▶ hub_permits.json(커밋)
                                                              │
                        update_adv_data.hub_derive ───────────┤ permits.done, permits.sched (activate·완결성 게이트)
                                                              ▼
                                        data.js ─split─▶ data-core.js / data-rest.json
                                                              │
              calc()(존페이지) ◀────────러닝재고 순부족(동치)────────▶ scCalc()(홈)
                     │
              estimate_ref_inventory(적정 재캘리브, 준공계열)
```

## 검증 / 테스트

- **단지 분류 단위테스트**: 준공/준공예정/미정 분류, PK 최신단계 1회(같은 단지 중복 배제).
- **러닝재고 단위테스트**: `max(0,…)` 재귀, 앵커 초기값 씻김, 순부족 = 미래수요 − (재고+미래공급×conf) 산식.
- **미러 등가**: Node `scCalc` vs Python `calc` max abs diff < 1e-6(양 경로).
- **적정 재캘리브 검증**: 준공계열로 재피팅한 적정이 가격 저점 타이밍과 여전히 맞는지(estimate_ref_inventory 자체 검증 로직).
- **순위 diff(핵심)**: 구모델 vs 신모델 36존 순위. 급변 존이 실측 근거로 설명 가능해야. 활성 개발지(화성·평택 등)가 미래공급 반영으로 과잉↑ 방향이면 정합.
- **동기화 체크리스트**([[agongmap-data-pipeline]]): hub_permits.json→hub_derive→data.js→split(data-core/rest)→sw.js.

## 리스크

1. **적정 재캘리브레이션이 순위를 흔듦** — 준공계열은 입주물량 계열과 시점이 다름(준공=사용검사, 입주물량=실입주). 재피팅 후 가격저점 정합 재확인 필수.
2. **먼 준공예정 슬립** — conf(t) 감쇠로 완화. 초기엔 보수적 곡선.
3. **준공예정 결측(미정) 단지** — 미완공인데 예정일 없음(~14%). 점수 미반영이라 그 존은 미래공급 과소 → 부족 편향 가능. 완결성 게이트로 부분수집 라이브 오염은 막되, 구조적 결측은 문서화.
4. **미래공급이 준공예정 하나에만 의존** — odcloud 실측 입주예정을 버리므로, 준공예정의 데이터 품질에 민감. 시드 후 near 구간을 구 odcloud와 스팟 대조 권장.

## 롤아웃 (안전 흐름 유지)

1. Task6/7의 dC(meas)·착공(fwd_far)·forward 변경을 **되돌려** pre-HUB calc/scCalc 기반 확보.
2. 러닝재고 모델을 그 위에 새로 구축(수집기 버킷·hub_derive·calc·scCalc·리스트·적정 재캘리브·테스트).
3. `meta.activate` off로 라이브 무변화 유지.
4. 전량 시드(`update-hub.yml mode=full` 재개가능, 일일 쿼터 확인).
5. `verify_rankdiff`로 36존 순위 검토(사용자 승인 게이트 — 지표 정의 변경).
6. 승인 시 `meta.activate=true` → 다음 daily가 data.js 반영.

## 구현 순서(개요 — 상세는 plan)

1. Task6/7 점수 변경 되돌리기(pre-HUB 기반).
2. 수집기 버킷 교체(done_q/sched_q) + `useInsptSchedDay` 채움 확인 반영, 테스트.
3. hub_derive 재작성(done/sched 시계열 주입, 게이트 유지).
4. 적정 재캘리브레이션(estimate_ref_inventory, 준공계열).
5. calc() 러닝재고 순부족 + verify_rankdiff, 순위 검토.
6. scCalc 동치 미러(0.0 재증명).
7. 상세 리스트 2섹션.
8. 롤아웃 배선(시드·검토·activate 문서화), 동기화·sw.js.
