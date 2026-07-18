# 아공맵 디자인 감사 — AI 디폴트 탈피 (2026-07-18)

> 상태: **진단 완료 · 구현 보류**. 사용자 지시로 코드 변경은 하지 않음.
> 산출: 18개 에이전트 병렬 감사 — 방향 4개 독립 제안 → 3관점(회의적 AD·실사용자·구현 엔지니어) 교차심사 → 종합.

## 사용자 질문

> 크림색 베이지가 너무 진하다. 전체적으로 AI 디자인 톤이 많이 느껴지는데 베이지 때문인가? 아님 다른 부분도 있나?

## 직답

베이지 때문이 맞지만, 베이지는 4분의 1입니다. 나머지 4분의 3이 더 큽니다.

**직답 1 — 베이지는 진짜 원인이 맞다(25%).** `--paper:#f6f4ee`는 스킬이 지목한 AI 디폴트 #1(warm cream ~#F4F1EA)과 사실상 같은 값입니다. 다만 "진하다"는 체감의 실체는 명도가 아니라 **노란기(웜 방향)** 입니다. 그리고 원인은 이 한 색이 아닙니다 — 실측 결과 `var(--paper)`는 CSS 전체에서 **단 4번** 쓰이고, 나머지 웜 뉴트럴은 18종이 하드코딩으로 흩어져 있습니다(#fcfbf7 #faf8f2 #f3efe4 #efeadd #e6e0d1 #e2dbc9 …). 같은 계열이 3~5% 차이로 겹치니 '의도한 색'이 아니라 '흐려진 흰색'으로 읽히고, 그 위에 `background:#fff`가 CSS 블록에만 **78회** 떠 있어 바탕이 때 탄 것처럼 보입니다. → **즉, --paper 한 줄만 바꾸면 오히려 나빠집니다.** 하드코딩 웜 회수와 같은 커밋이어야 합니다(원자적 작업).

**직답 2 — 더 큰 원인은 타이포입니다(40%).** 실측 확인했습니다. `index.html:73`에 `font-family:'Pretendard'`가 적혀 있는데 **@font-face·CDN·@import가 파일 전체에 0건**입니다. 즉 Windows에서는 맑은 고딕, Mac에서는 Apple SD Gothic Neo로 렌더됩니다. 그런데 `font-weight:800`이 **84회**, 700이 **55회** — 전체 153개 선언 중 139개(91%)가 700 이상입니다. 맑은 고딕에는 800 자족이 없으므로 브라우저가 **가짜 볼드(faux bold)를 합성**합니다. 결과적으로 화면 전체가 굵기 차이 없이 균일하게 뭉개지고, 위계가 '크기'로만 존재합니다. 이게 AI 느낌의 최대 단일 지분입니다. 링크 한 줄이면 해결되는 문제인데 안 고쳐져 있습니다.

**직답 3 — 장식·카드 반복(25%)과 색 토큰 붕괴(10%).** '흰 카드 + --line + 라운드 + 그림자' 레시피가 15개 클래스에 반복되고, radius는 16종 혼재(12px×17, 10px×14, 8px×10 …), 아무것도 인코딩하지 않는 장식 원 3개, 모든 메타를 알약 배지로 만드는 습관 12종. 색은 상승 빨강이 5종(#c0392b 19회 / #a93226 20회 / #e0564a 27회 / #d2342a 1회 / #b23022 1회), 하락 파랑이 3종(#1a5276 23회 / #2c5f9e 3회 / #1565c0 1회)으로 흩어져 사용자가 색을 의미로 학습할 수 없습니다.

**보너스 — 리디자인과 무관하게 지금 데이터가 거짓말하고 있는 곳 2군데를 찾았습니다.**
1. `index.html:716-720` — `.sc-track{height:14px;border-radius:8px}` + `.sc-fill{border-radius:8px}`. 높이 14px에 반경 8px이면 반경이 높이의 절반(7px)을 넘어 **완전한 알약**이 됩니다. 시그니처 지표인 발산 막대의 양 끝점이 각 8px씩 안으로 말려 있습니다 — 취향이 아니라 값 왜곡입니다.
2. `index.html:3112` — `Math.sqrt(Math.abs(u.tot)/mx)*50`. 발산 막대는 **선형이 아니라 제곱근 스케일**입니다. (이 사실이 "셀 하나=1,000세대" 같은 눈금 아이디어를 전부 무효화하므로, 그쪽 방향은 채택하지 않았습니다.)

## 원인 분해

| 원인 | 비중 |
|---|---|
| 타이포 부재 (폰트 미로딩 + 가짜 볼드) | 40% |
| 장식·카드 반복 | 25% |
| 베이지 (웜 뉴트럴 18종 산개) | 25% |
| 색 토큰 붕괴 | 10% |

## AI 시그널 상세

### [HIGH] 웹폰트가 0건인데 font-weight:800을 84회 선언 — 맑은 고딕/Apple SD Gothic Neo에 800 자족이 없어 브라우저 합성 볼드(faux bold)로 렌더된다. 굵기 위계가 존재하지 않고 화면 전체가 균일하게 뭉개진다. AI 느낌의 최대 단일 원인.

근거:

```
body{font-family:'Pretendard',-apple-system,...} 이나 @font-face·googleapis·jsdelivr 폰트 링크 검색 결과 0건. CSS 블록(65~764행) 내 font-weight:800 ×84, 700 ×39, 600 ×7, 500 ×2, 400 ×2 → 700 이상이 134개 중 123개(92%).
```

### [HIGH] 한글 텍스트에 Latin 조판 규칙을 그대로 적용한 아이브로우. uppercase는 한글에 아무 효과가 없고, letter-spacing .16em은 이미 정사각 프레임인 한글을 자간이 벌어진 낱글자로 흩뜨려 가독성을 떨어뜨린다. 게다가 내용이 전부 '· 구분 메타 3연발' 패턴.

근거:

```
.eyebrow{font-size:13px;letter-spacing:.16em;text-transform:uppercase;font-weight:800} / .qeyebrow / .home-eyebrow 동일 값. 실제 내용은 한글: class="eyebrow">한국 부동산 순환 사이클 · 시도·생활권 분석, class="hs-kicker">10문항 · 3분 · 즉시 채점. CSS 블록 내 text-transform:uppercase ×7, letter-spacing:.16em ×4, .hs-kicker는 letter-spacing:.14em으로 HTML에 5회 반복.
```

### [HIGH] 정보를 하나도 인코딩하지 않는 순수 장식 원 3개. 세 개 모두 border 1.5px·--line·opacity .4~.5로 값까지 동일해 '템플릿에서 복사한 장식'임이 드러난다.

근거:

```
.hero::after{width:340px;height:340px;border:1.5px solid var(--line);border-radius:50%;opacity:.5} / .hero::before{width:160px;height:160px;...opacity:.4} / .home-hero::after{width:300px;height:300px;...opacity:.4}
```

### [HIGH] '흰 카드 + --line 1px 테두리 + 라운드 + 옅은 그림자' 단일 레시피의 무한 반복. 레이아웃에 아이디어가 하나뿐이고, 위계는 radius 값만 조금씩 다르게 주는 것으로 대체돼 있다.

근거:

```
CSS 블록 내 background:#fff ×37(전체 #fff 66회). 동일 레시피 클래스: .chartbox .conf .hcol .qpick-card .qopt .nextstep .subs .ctrl .rank-wrap .adv-tblwrap .tbl-wrap .calc-card .calc-out .hcard .adv-links a — 15개 이상. 예: .chartbox{background:#fff;border:1px solid var(--line);border-radius:10px} vs .hcard{...border-radius:16px} vs .qopt{...border-radius:14px} vs .nextstep{...border-radius:16px}
```

### [MEDIUM] radius 체계 부재 — 18종 혼재. 2·3·4·6·7·8·9·10·12·14·16·18·20·24·30px + 50% + 999px. 어떤 스케일(4의 배수, 피보나치 등)도 아니고 컴포넌트 성격과도 무관하게 배정돼 있다.

근거:

```
border-radius 빈도: 12px×17, 10px×14, 8px×10, 14px×7, 20px×6, 16px×6, 50%×9, 999px×3, 6px×3, 9px×2, 3px×2, 2px×2, 18px×2, 7px×1, 4px×1, 30px×1, 24px×1
```

### [MEDIUM] 모든 메타데이터를 색깔 알약(pill) 배지로 처리하는 반사적 습관. 10~13px + weight 800 + letter-spacing + 라운드 20~999px 조합이 12개 이상 클래스에 반복돼, 화면이 '배지 밭'이 된다.

근거:

```
.verdict{border-radius:30px} .conf .clevel{border-radius:20px} .pc-badge{border-radius:12px} .adv-badge{border-radius:10px} .rcard .rc-lv{border-radius:16px} .hc-badge{border-radius:12px} .sc-tier{border-radius:7px} .read .lab{border-radius:20px} .map-datechip span{border-radius:999px} .mainkicker/.refkicker{border-radius:20px} .adv-tabs button{border-radius:999px} — 전부 font-weight:800
```

### [HIGH] 베이지가 한 색이 아니라 18종 웜 뉴트럴로 번져 있다. 페이지 바탕·강조 블록·표머리·트랙 배경·타일 테두리를 전부 같은 계열이 맡아 서로 3~5%밖에 차이나지 않으니, 색이 아니라 '때'로 읽힌다. 사용자가 '진하다'고 느낀 실체.

근거:

```
--paper:#f6f4ee, --paper2:#edeae1(var(--paper2) 16회 사용: .take .read .qexp .qshare-box .tldr-rate #stat-tbl th table.adv thead th .rank-tbl thead th .adv-badge .qprogress 등) + 하드코딩 #fcfbf7(section.step.ref) #fbfaf6(section.ref) #fafaf7(#stat-tbl 짝수행) #faf8f2(.sc-det .bb-det .lz-det .clock-det ×4) #fbf7ea(tr.fut ×2) #f5efdd(bandrow ×3) #f3efe4 #f1eee6 #efeadd #e6e0d1(.sc-track) #e2dbc9(.lz-tile) #e0d5b4 #cfc9b8 #c9c2b0 #b9b3a4
```

### [MEDIUM] --paper:#f6f4ee가 스킬이 지목한 AI 디폴트 #1(warm cream ~#F4F1EA)과 사실상 동일. 단독으로도 감식 대상이지만, 그 위에 #fff 카드가 66회 떠 있어 3% 차이의 '더러운 흰색'으로 보이는 게 더 큰 문제다.

근거:

```
:root{--paper:#f6f4ee} + body{background:var(--paper)}. #f6f4ee와 #fff의 명도차 약 3%. 반면 카드 테두리 --line:#dad5c9 역시 웜 그레이라 카드 경계도 약하다.
```

### [HIGH] 토큰 붕괴 — CSS에 고유 hex 87종이 존재하는데 :root 토큰은 13개뿐. 특히 서비스의 신성한 규칙인 '빨강=상승 / 파랑=하락'이 서로 다른 hex로 흩어져 사용자가 색 언어를 학습할 수 없다. 상승 빨강 5종, 하락 파랑 3종.

근거:

```
상승/부족 계열: --maemae #c0392b(×6), #a93226(×8, .calc-big.bad·table.adv td.lo·.bb-chip.lo·.sc-tier.t4·.sc-key .k-r b), #e0564a(×4, .hcol.short·.qopt.wrong·.rc-dots i.no·.chart-legend .cl-ma), #d2342a(.chg-up), #b23022(.v-weak). 하락/과잉 계열: #1a5276(×9), #1565c0(.chg-dn), #2c5f9e(.hcol.long). 즉 .chg-up은 #d2342a인데 table.adv td.up은 #c0392b, .rank-tbl td.up도 #c0392b — 같은 '상승'이 세 가지 빨강.
```

### [MEDIUM] 토큰을 우회한 생짜 회색 텍스트. --ink2/--muted가 있는데 #444·#333·#222·#666·#4a4a4a를 직접 박아, 나중에 덧붙여 생성된 블록임이 그대로 보인다.

근거:

```
#444 ×5(.calc-desc .clock-det td .bb-det .sc-det .lz-det), #333(.bb-lab .lz-lab), #222(.sc-lab), #666(.bb-chip .sc-tier), #4a4a4a(.lz-tv), #2b2620(.lz-tn) — 전부 --ink2:#3b4569 / --muted:#6f6a5c 를 두고 별도 정의
```

### [MEDIUM] 이모지를 아이콘 시스템 대신 사용. 특히 결과 카드에서 54px 이모지가 히어로 역할을 한다 — AI 생성 결과화면의 대표적 인장.

근거:

```
.rcard .rc-emoji{font-size:54px} / .hcard .hc-emoji{font-size:34px} / .qpick-card .pc-emoji{font-size:26px}. HTML 내 pc-emoji ×3, rc-emoji ×1
```

### [MEDIUM] 장식용 각도 그라디언트 카드. 160deg/135deg로 흰색→옅은 틴트로 흐르는 카드 배경 4개는 정보와 무관한 순수 데코이며, 특히 .rcard는 '다크 네이비 그라디언트 + 골드 2px 테두리 + 20px 라운드 + 큰 그림자 + 큰 숫자'라는 AI 스코어카드 아키타입 그 자체.

근거:

```
.rcard{background:linear-gradient(160deg,#1a2235,#2a3550);border:2px solid var(--gold);border-radius:20px;box-shadow:0 12px 32px rgba(22,32,58,.35)} + .rc-score{font-size:46px;font-weight:800}. .versus.win{linear-gradient(160deg,#fff,#eafaf3)} .versus.lose{...#fdecea} .versus.draw{...#fdf6e3} .hcard.feat{linear-gradient(135deg,#fff,#fbf3dc)}
```

### [LOW] transition:.15s를 속성 지정 없이 전 속성에 거는 습관이 7회 — 무엇이 왜 움직이는지에 대한 판단 없이 '부드럽게' 붙인 티가 난다. 무한 반복 바운스 애니메이션도 1건.

근거:

```
transition:.15s ×7(.toggle button .home-cta .hcard .smode button .adv-tabs button .adv-links a .gt button), transition:all .15s ×2(.qpick-card .qopt). .tldr-arrow{animation:tldrbob 1.4s ease-in-out infinite}
```

### [LOW] 카드 hover 시 transform:translateY로 떠오르는 처리 — 데이터 분석 서비스의 '냉정한' 톤과 상충하며, SaaS 랜딩페이지 템플릿의 기본 반응이다.

근거:

```
.hcard:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 6px 20px rgba(22,32,58,.08)} / .adv-links a:hover{border-color:var(--accent);transform:translateY(-1px)} / .qpick-card:active{transform:scale(.99)} 등 scale(.99) 계열 5회
```

## 보존할 것 — 건드리면 안 되는 것

- 아공맵 발산 막대의 0 기준선 구현 — .sc-track::before{left:50%;width:1px;background:rgba(22,32,58,.28)} 와 .sc-zero{left:50%}. 막대 길이를 읽으려면 중앙이 보여야 한다는 판단이 코드와 주석에 남아 있다. 이건 장식이 아니라 정보 설계다. 절대 건드리지 말 것.
- 축 범례 .sc-key — 왼쪽 k-l은 파랑 그라디언트(rgba(26,82,118,.13)→.02), 오른쪽 k-r은 빨강(.02→rgba(169,50,38,.13))으로 막대 방향과 색을 그대로 미러링한다. '막대 색과 반드시 일치시킬 것' 주석까지 있음. 범례가 규칙을 가르치는 드문 사례.
- 숫자 조판 — font-variant-numeric:tabular-nums 9곳(.rc-score .vs-score #stat-tbl td table.adv .rank-tbl .sc-val .lz-val .calc-kv b). 순위·세대수·%가 본질인 서비스에서 정확히 옳은 선택이며, 폰트를 교체하더라도 이 속성은 반드시 승계해야 한다.
- body{word-break:keep-all} — 한글에서 어절 중간 줄바꿈을 막는 조치. 한국어 조판을 아는 사람의 선택이고, overflow-wrap:break-word와 짝지은 것도 정확하다.
- 접근성 기본선 — a/button/select/input/summary/[tabindex]/[role=button]에 일괄 :focus-visible{outline:2px solid var(--ink);outline-offset:2px;box-shadow:0 0 0 4px rgba(22,32,58,.20)} + @media(prefers-reduced-motion:reduce) 전역 차단. 리디자인 시 outline 색만 새 토큰으로 갈고 구조는 유지.
- @media(max-width:400px)에서 .sc-row 고정폭을 축소해 가로 스크롤을 막은 블록 — '반드시 .sc-val/.sc-tier 정의 뒤에 와야 덮어쓴다(같은 특이도라 순서가 승패를 가름)' 주석 포함. 시그니처 컴포넌트의 실측 기반 수정이므로 선택자 순서를 절대 바꾸지 말 것.
- 데이터 테이블 엔지니어링 — table.adv의 thead th{position:sticky;top:0} + 첫 열 th/td{position:sticky;left:0;z-index:1} + thead th:first-child{z-index:2}. 모바일에서 매트릭스를 숨기고 compact로 전환하는 @media(max-width:720px) 분기까지 포함해 실사용 검증을 거친 구조다.
- section.step의 스코프 토큰 패턴 — {--part:var(--stock);--part-bg:#e8f3ee;--part-ink:#1a6b54} 와 .ref 변형. 이 파일에서 유일하게 '체계적'인 부분이며, 앞으로 색 토큰을 정리할 때 이 방식을 나머지 전체로 확장하면 된다.
- .howto 다크 밴드 — background:var(--ink);color:#e8ebf2 로 페이지 흐름을 끊는 구조 장치. 또 하나의 흰 카드가 아니라 '반전 띠'라는 점에서 리듬을 만든다. 카드 남발을 줄일 때 이런 밴드형 장치를 오히려 늘려야 한다.
- .hero-map — opacity:.34에 radial mask-image를 씌운 히어로 배경. 빈 원 3개와 달리 이건 실제 데이터(지도)를 배경 텍스처로 쓴 것이라 정당하다. 장식 원은 지우되 이건 남길 것.
- .maemae:#c0392b / .jeonse:#6c4ab6 토큰 자체 — 매매 빨강, 전세 보라의 축은 옳다. 문제는 이 토큰이 아니라 이를 우회한 #a93226·#e0564a·#d2342a 하드코딩이므로, 토큰을 바꾸지 말고 하드코딩을 토큰으로 회수하는 방향으로 정리할 것.

## 방향 심사 결과

| 점수 | 방향 | 독창 | 주제적합 | 실현 | 데이터무결 | 한글폰트 |
|---|---|---|---|---|---|---|
| 34.67 | 단위: 호 | 7.3 | 8.7 | 5 | 6.7 | 7 |
| 34.17 | 입면도(立面圖) | 7.7 | 8.7 | 5.3 | 5.3 | 7.2 |
| 33.67 | 영점 자오선 (Zero Meridian) | 7.7 | 8.7 | 4.7 | 6.3 | 6.3 |
| 24.47 | 야장(野帳) — 측량 야장에서 출발한 실측 도면 체계 | 7.5 | 8.3 | 4.8 | 6.7 | 7.2 |

## 채택 방향

**원부(原簿) — 「표두 + 관통 0선 + 우측 고정 숫자열」. 최고점 방향인 ledger(단위: 호)를 뼈대로 삼되, 그 방향의 치명적 결함 3개(존재하지 않는 마루부리 CDN, 한글 웹폰트 3패밀리 통짜 로딩, 숫자를 막대 끝에 붙여 원부의 가장 기능적인 규칙을 스스로 어긴 것)를 잘라내고 재조립했다. 핵심 명제: 아공맵의 재료는 부동산원·KOSIS 원자료이므로, 화면은 앱이 아니라 그 자료가 인쇄되던 물건 — 통계 원부 — 의 조판을 따른다. 원부에는 카드도 배지도 장식 원도 없고 표번호·단위 표기·괘선·각주·출처만 있는데, 이 다섯은 전부 콘텐츠의 사실을 인코딩하므로 하나도 장식이 아니다.**

세 후보(ledger 34.67 / material 34.17 / instrument 33.67)가 0.5점 안에 몰려 있어 점수만으로는 선택 근거가 되지 않았다. 실제로 갈린 것은 **각 방향의 킬샷이 실측 코드에서 재현되는가**였다.

material의 유닛 셀 격자(1칸=1,000세대)는 index.html:3112의 `Math.sqrt(Math.abs(u.tot)/mx)*50` 하나로 무효화된다 — 막대가 제곱근 스케일이라 셀당 세대수가 위치마다 달라지고, "칸을 세면 세대수가 나온다"는 유일한 약속이 거짓이 된다. 균일한 단색 fill보다 오히려 부정직하다. instrument의 페이지 관통 자오선은 `.sc-track{flex:1}`(index.html:716)이라 그 50%가 뷰포트 좌표가 아닌 데다, 통계 탭의 14개 차트가 전부 canvas라 CSS 축이 물리적으로 관통할 수 없다. 한 군데서 12px 어긋나는 순간 "단 하나의 정확한 축"이라는 주장이 자기파괴적이 된다. cadastre의 배경 방안 격자는 반응형 폭에서 1칸의 실제 세대수가 기기마다 달라져 축척 선언이 유지 불가능하다.

ledger만이 **기존 코드가 이미 갖고 있는 판단을 확장하는** 방향이었다. `.sc-track::before{left:50%}`의 0 기준선, `.sc-key`의 좌우 색 미러링, tabular-nums 9곳, `word-break:keep-all` — 이 파일에서 유일하게 옳은 정보 설계들이 전부 '원부'의 문법이다. 새 옷을 입히는 게 아니라 이미 있던 뼈대를 페이지 전체로 승격시키는 일이라, 병렬 세션이 같은 파일을 24시간에 수십 번 건드리는 환경에서 **단계별로 쪼개도 중간 상태가 깨져 보이지 않는다**는 결정적 실행 이점이 있다.

다만 ledger를 그대로 쓰지 않았다. (1) 이 방향이 유일하게 제시한 검증 가능한 근거인 마루부리 jsdelivr 경로가 404라는 지적을 받아들여 폰트 계획을 통째로 교체했다. (2) IBM Plex Sans KR + Plex Mono + 마루부리 3패밀리는 모바일 우선 서비스에 수 MB를 물리므로 2패밀리로 줄이고, 그중 하나는 자체 호스팅 서브셋으로 돌렸다. (3) 가장 중요한 수정 — ledger는 원부를 인용하면서 숫자를 막대 끝에 붙여 x좌표가 행마다 움직이게 설계했다. 원부의 원칙은 정반대로 숫자를 **우측 고정 열**에 몰아넣는 것이고, 그래야 tabular-nums를 도입한 이득이 살아난다. 사용자가 실제로 하는 행동은 "내 동네 순위와 세대수를 위아래 행과 비교"이므로 이건 미학이 아니라 기능이다.

그리고 이 방향이 AI 디폴트 #3(브로드시트)로 착지한다는 지적에 대한 대응: 다단 조판을 쓰지 않고(모바일 1단), 선을 균일한 헤어라인으로 깔지 않고 2.5px/겹줄/1px 3단 위계로 운용하며, 신문의 조밀한 텍스트 블록 대신 표두→겹줄→데이터→각주라는 표 단위로 넉넉한 세로 리듬을 갖는다. 참조 대상이 신문이 아니라 통계 원부라는 점이 구조(표번호·단위·출처·기준일)에서 드러난다. 라틴 모노를 기본 어휘로 쓰지 않는 것도 의도적이다 — 그게 '데이터 터미널 룩'이라는 네 번째 디폴트로 가는 문이다.

## 시그니처

## 표두(表頭) + 관통 0선 + 우측 고정 숫자열

대담함은 여기 한 곳에만 쓰고, 그 대가로 나머지는 전부 조용합니다 — 배지 없음, 그림자 없음, 장식 그라디언트 없음, 장식 원 없음.

### 1) 표두 — 모든 블록이 같은 방식으로 열린다

`.hs-kicker`(12px/800/자간 .14em, 6회)와 eyebrow 5곳을 통계표의 표두로 교체합니다. 한 줄에 세 개의 **사실**이 들어갑니다:

```
표2 · 생활권별 누적 순부족                    (단위: 호)
════════════════════════════════════════════════════  ← 겹줄
                                    n=36 · 07-18 기준
```

- 왼쪽: 표번호 + 제목 (Pretendard 600 / 19px / 먹색)
- 오른쪽 끝: 괄호 단위 (11px / --muted)
- 아래: 표본 수와 갱신일 (11px / --muted)
- 그 아래 겹줄(1px + 3px 간격 + 1px)이 화면 폭을 가름

**판정 규칙 하나로 집행합니다: 슬러그에 형용사가 들어가면 그건 아이브로우이므로 삭제한다.** 들어갈 수 있는 것은 수량·단위·기간·기준일·출처 다섯 종뿐. 「10문항 · 3분 · 즉시 채점」 같은 · 구분 메타 3연발은 표두 아래 각주 줄(주1)로 내립니다. **인코딩할 사실이 없는 섹션에는 표두를 달지 않습니다** — 번호만 남기거나 아무것도 두지 않습니다.

왜 이게 옳은가: 아이브로우는 0개의 사실을 전달하지만 표두는 세 가지를 전달합니다. (a) 표번호는 실제 일련번호라 각주에서 「표2 참조」 상호참조가 성립하고 리포트 6고리 「제1환~제6환」과 맞물립니다. (b) 호/세대/%/개소/㎡가 한 화면에 섞이는 서비스에서 단위 표기는 사치가 아니라 **숫자 오독 방지 기능**입니다. (c) 집 사려는 사람이 이 사이트를 믿느냐 마느냐는 폰트가 아니라 "이 숫자 어디서 온 거냐, 언제 기준이냐"에서 갈립니다 — 갱신일이 상시 노출되는 순간 화면이 '디자인'에서 '자료'로 바뀝니다.

### 2) 관통 0선 — 척추

지금 0선은 `.sc-track::before{left:50%}`(index.html:718)로 **각 행 안에 조각조각** 들어 있습니다. 새 구조에서는 축 범례부터 36개 행, 각주 위까지 **단 하나의 연속된 1px 먹색 선**이 위에서 아래로 꿰뚫습니다. 막대는 카드 안의 그래픽이 아니라 이 척추에서 좌우로 자라난 조직이 됩니다.

구현은 조용합니다 — 선을 각 행의 `::before`가 아니라 **컨테이너 하나에** 절대 위치로 걸고, 행들은 그 x좌표에 정렬됩니다.

**중요 — 범위를 정확히 한정합니다.** 이 선은 아공맵 스코어 블록 **내부에서만** 연속합니다. 페이지 전체를 관통시키자는 안(자오선)은 기각했습니다: `.sc-track{flex:1}`이라 그 50%가 뷰포트 좌표가 아니고, 통계 탭 14개 차트가 전부 canvas라 CSS 축이 물리적으로 관통할 수 없으며, 한글 본문 문단 한가운데를 세로선이 지나가면 계기가 아니라 오식으로 읽힙니다. **한 군데서 어긋나는 순간 "하나의 정확한 축"이라는 주장이 자기파괴적이 됩니다.**

### 3) 우측 고정 숫자열 — 원안의 자기모순을 고친 부분

발산 막대는 0 기준선에서 좌우로 뻗지만, **세대수 숫자는 막대 끝을 따라가지 않고 우측 고정 열에 정렬**됩니다.

```
        과잉 ←        ┃        → 부족
 ░░░░░░░░░░░░░░░░░░░░ ┃ ▒▒▒▒▒▒▒▒▒▒▒▒▒▒
  1 │ 수원 영통       ┃███████████    12,400 │ ★
  2 │ 대전 유성       ┃████████        9,120 │
  3 │ 서울 강동       ┃██████          6,050 │ ★
 34 │ 대구 수성 █████████               11,200 │
 35 │ 세종      ██████████              13,600 │
 ─────────────────────────────────────────────
 주1) ★ = 실거주 유리
 주2) 순부족 = 3년 누적 입주 − 멸실 − 가구증가
 출처) 부동산원 주간시계열 · 국토부 입주예정물량
```

사용자가 실제로 하는 행동은 "내 동네 순위와 세대수를 위아래 행과 비교"입니다. 숫자가 막대 끝에 붙어 x좌표가 행마다 움직이면 tabular-nums를 도입한 이득이 전부 상쇄됩니다. **원부의 가장 기능적인 규칙이 바로 숫자를 우측 고정 열에 몰아넣는 것**이고, 참조한 원안은 원부를 인용하면서 이 규칙을 어겼습니다.

**부호 표기 주의:** '순부족'이라는 이름에 마이너스를 붙이면 이중부정이 됩니다("부족이 -면 남는다는 건가?"). 방향(좌/우)과 색(파랑/빨강)이 이미 부호를 인코딩하므로, 숫자는 절대값으로 쓰고 부족/과잉은 위치와 색으로만 말하게 하세요.

### 절대 보존할 것

- `.sc-key` 축 범례의 좌우 색 미러링 — 왼쪽 파랑 그라디언트, 오른쪽 빨강. "막대 색과 반드시 일치시킬 것" 주석까지 있는, 범례가 규칙을 가르치는 드문 사례입니다. 이 그라디언트는 장식이 아니라 정보이므로 '그라디언트 전면 금지' 규칙의 유일한 예외입니다.
- `@media(max-width:400px)`의 `.sc-row` 축소 블록 — "반드시 .sc-val/.sc-tier 정의 뒤에 와야 덮어쓴다(같은 특이도라 순서가 승패를 가름)" 주석 포함. **선택자 순서를 절대 바꾸지 마세요.**
- `table.adv`의 sticky thead/first-column 구조와 720px 이하 compact 전환.
- `:focus-visible` 일괄 규칙 — outline 색만 새 --ink로 갈고 구조 유지.
- `.hero-map` — 실제 지도를 텍스처로 쓴 배경이므로 정당합니다(opacity .34 → .18로 낮춰 표제 아래로 물림). 반면 `.hero::after`(340px 원) `.hero::before`(160px) `.home-hero::after`(300px) 장식 원 3개는 삭제.
- `.howto` 다크 밴드 — 또 하나의 흰 카드가 아니라 '반전 띠'로 페이지 흐름을 끊는 구조 장치. 카드를 줄일 때 이런 밴드형 장치는 오히려 늘려야 합니다.

## 토큰 before/after

| 토큰 | before | after | 비고 |
|---|---|---|---|
| --paper | #f6f4ee | #F4F6F5 | 핵심 수정. 명도를 L*96.0→96.8로 올려 '진하다'는 체감을 실제로 해소하면서, 색상각을 45°(웜 크림)에서 160° 부근 극저채도 쿨 그린-그레이로 회전시킨다. 사용자가 느낀 '진함'의 실체는 명도가 아니라 노란기였다. 순백으로 도망치지 않은 이유는 흰색을 '값이 있는 면' 전용으로 예약해야 하기 때문 — #fff가 78회 떠 있는 지금 상태에서 바탕까지 흰색이면 위계가 0이 된다. 참고: ledger 원안의 #EDF0F2(L*94)는 현재보다 오히려 어두워 사용자 불만과 정면 충돌하므로 기각했다. |
| --paper2 | #edeae1 | #E9EDEB | var(--paper2) 16회 사용(.take .read .qexp .qshare-box .tldr-rate #stat-tbl th table.adv thead th .rank-tbl thead th .qprogress 등). --paper와 6% 이상 벌려 단 한 계단만 둔다. 3~5% 차이의 중간 톤이 '흐려진 흰색'의 원인이었으므로 중간 단계는 만들지 않는다. 대비 검증: --maemae #c0392b on #E9EDEB = 4.60:1로 AA 통과(material 원안의 #E5E9E7은 4.44:1로 미달이었다). |
| --line | #dad5c9 | #C4CEC9 | 현재 --line은 웜 그레이라 --paper와 명도차가 작아 카드 경계가 바탕에 녹아 사라진다. 쿨 축으로 옮기고 명도를 낮추면 1px이 실제로 선으로 보인다. --paper 대비 1.52:1 — 카드 테두리를 버리고 괘선만으로 구획을 만들 수 있는 최소 조건이다. 이 값이 확보되지 않으면 카드 해체 단계(6단계) 자체가 성립하지 않는다. |
| --ink | #16203a | #131E24 | 현재 값은 채도 있는 네이비라 '브랜드 컬러'로 읽히고 데이터 파랑(#1a5276)과 색상환에서 겹쳐 '텍스트인지 값인지' 혼선을 준다. 청록 쪽으로 눕히고 채도를 낮춰 인쇄 먹에 가깝게. --paper 대비 15.6:1. :focus-visible outline 색도 이 값으로 통일(구조는 그대로 유지). |
| --ink2 | #3b4569 | #4C5F66 | --paper 대비 6.24:1. 보조 텍스트·표 캡션 담당. |
| --muted | #6f6a5c | #5E6F74 | 주석 색 — 단위 표기, 각주, 출처, 기준시점, 축 라벨 전담. 대비 4.89:1로 본문 기준선 4.5:1 충족(웜 축의 #6E7F84는 3.86:1로 미달이라 더 어둡게 잡았다). **이 색 하나가 배지·알약 12종의 일을 전부 대신한다** — 메타데이터는 배경을 얻지 않고 색만 잃는다. 동시에 토큰을 우회한 생짜 회색 #444(×5) #333 #222 #666 #4a4a4a를 전부 여기로 흡수. |
| --gwaing | (토큰 없음, #1a5276 하드코딩 23회) | #1A5276 | 신규 토큰. 값은 바꾸지 않고 이름만 준다 — 가장 많이 쓰인 검증된 값을 그대로 승격. 이 서비스의 색 언어는 빨강/파랑 두 축인데 빨강만 토큰이고 파랑은 없어서 #1565c0·#2c5f9e로 새고 있었다. 대비 7.71:1. |
| --maemae | #c0392b | #c0392b (불변) | 신성 규칙이므로 값에 손대지 않는다. --paper 대비 5.01:1로 AA 통과. 대신 새 규칙 하나를 건다: **이 빨강을 UI 크롬(버튼·링크·탭·활성 상태)에 절대 쓰지 않는다.** 화면에 빨강이 보이면 그건 언제나 '상승/공급 부족'이다. 이 한 줄로 데이터 색 의미론이 '지켜지는 것'에서 '구조적으로 위반 불가능한 것'으로 격상된다. |
| --jeonse | #6c4ab6 | #6c4ab6 (불변) | 매매/전세는 계열 축이 다른 별도 토큰이므로 그대로 유지. --stock #1f8a70, --flow #d99a00도 유지 — 이 둘은 section.step의 스코프 토큰(--part/--part-bg/--part-ink)으로 사이클 리포트의 카테고리를 인코딩하고 있어, 삭제하면 UI 정리가 아니라 데이터 차원 삭제가 된다. |
| --accent | #3d4a8a | 폐기 → var(--ink) | 버튼·링크·활성 탭은 색이 아니라 먹색과 괘선 굵기로 구별한다. 지금은 네이비 액센트가 데이터 색 옆에서 같은 강도로 소리쳐 사용자가 색을 의미로 학습할 수 없다. |
| --gold / --gold-ink | #b8862f / #8f6510 | 전면 폐기 | .rcard의 '다크 네이비 그라디언트 + 골드 2px 테두리 + 20px 라운드 + 46px 숫자'는 AI 스코어카드 아키타입 그 자체다. 골드가 사라지면 그 카드는 자동으로 해체된다. |
| --r-data / --r-touch | radius 16종 혼재 | 0 / 3px | 규칙 한 문장: **잰 것은 각지고, 누르는 것만 3px.** 데이터 표면(막대·트랙·표·차트박스·타일맵·표두)은 예외 없이 0, 손가락이 닿는 것(하단 4탭·퀴즈 선지·버튼·인풋·셀렉트)만 3px. 999px 알약과 50% 원은 전면 폐기(장식용 빈 원 3개는 삭제, 지도 현재위치 점만 50% 허용). 근거가 취향이 아니다 — index.html:716-720에서 높이 14px 트랙에 반경 8px이 걸려 발산 막대 양 끝이 실제로 말려 있다. |
| JS GRID | #e7e3d9 (index.html:1467) | #DDE4E1 | 14개 차트의 격자선 색. CSS 토큰이 아니라 JS 상수라서 :root만 고치면 통계 탭 격자만 누렇게 남는다. index.html:1467의 INK/INK2/GRID/MUTED 상수 4줄을 :root 교체와 **같은 커밋에** 동기화할 것. MAEMAE/JEONSE/STOCK/FLOW는 값 불변이므로 건드리지 않는다. |

## 폰트 계획

## 전제: 지금 폰트가 안 걸려 있다는 사실이 이 계획의 출발점

`index.html:73`에 `font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif`가 적혀 있고 `index.html:1466`에 같은 문자열이 JS 상수 `FONT`로 또 있는데, **@font-face·CDN 링크·@import가 파일 전체에 0건**입니다. 코드가 의도한 폰트를 실제로 불러오는 것 — 이게 선택자 수정 0줄, head 한 줄로 끝나는 최대 ROI 작업입니다.

## 패밀리는 2개까지만. 한글 웹폰트 3패밀리는 모바일에서 재앙이다

심사된 방향들이 공통으로 저지른 실수가 폰트 페이로드를 한 번도 계량하지 않은 것입니다. 마루부리·에스코어드림 같은 한글 완성형 폰트를 서브셋 없이 통짜로 받으면 웨이트당 1MB를 넘고, 하필 그게 걸리는 자리가 히어로 표제입니다. 474KB짜리 사이트에 폰트만 수 MB가 붙습니다.

### 1) 본문·숫자·UI 전체 — Pretendard Variable (dynamic subset)

```html
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
```

- **dynamic-subset이 핵심입니다.** 이 CSS는 한글을 unicode-range로 수백 조각으로 쪼개 배포하므로 실제 페이지에 등장하는 글자의 서브셋만 내려옵니다. 통짜 `pretendardvariable.css`(1MB+)를 쓰면 안 됩니다.
- 가변 폰트라 400/500/600/700이 **진짜 자족**으로 존재합니다. 지금의 합성 볼드 문제가 이 한 줄로 해결됩니다.
- `font-family` 선언을 고칠 필요가 전혀 없습니다 — 이미 'Pretendard'가 첫 순위로 적혀 있고, 나머지 20곳은 `inherit`입니다.
- **배포 전 반드시 실물 확인**(peer 방향 하나가 "CDN 실재 확인함"이라고 적고 404였습니다):
  ```bash
  curl -sI "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css" | head -1
  ```
  200이 아니면 `@v1.3.9`를 최신 태그로 바꾸거나 npm 경로(`/npm/pretendard@1.3.9/dist/web/variable/...`)로 대체하세요.

### 2) 디스플레이(표제 전용) — 마루부리 자체 호스팅 서브셋 [5단계, 선택]

한글 명조를 표제에만 씌우면 라틴 하이컨트라스트 세리프(AI 디폴트 #1)와 계보가 다르면서 본문 고딕과 '서체 전환' 축이 생깁니다. 단 **CDN 통짜 로딩은 금지**하고, 실제 표제에 쓰는 글자만 서브셋해 이 저장소에 넣습니다. GitHub Pages가 이미 정적 자산을 서빙 중이니 추가 인프라가 없습니다.

```bash
pip install fonttools brotli
# 1) 실제 표제 문자열만 모아 텍스트 파일로 (h1/h2/표두 제목 전부)
#    예: display-strings.txt  ← "아파트는 공급이 알파이자 오메가 생활권별 누적 순부족 …"
# 2) SemiBold 한 벌만 서브셋
pyftsubset MaruBuri-SemiBold.ttf \
  --text-file=display-strings.txt \
  --layout-features='kern,liga' \
  --flavor=woff2 \
  --output-file=fonts/maruburi-sub.woff2
```
결과물은 보통 **20~40KB**입니다(통짜 대비 1/30). 원본 폰트는 네이버 마루부리 공식 배포처(hangeul.naver.com) 또는 Google Fonts의 MaruBuri에서 받고, OFL 라이선스 고지를 리포지토리에 포함하세요.

```css
@font-face{
  font-family:'MaruBuriSub';
  src:url('/fonts/maruburi-sub.woff2') format('woff2');
  font-weight:600; font-style:normal;
  font-display:swap;                 /* FOIT 금지 */
  size-adjust:100%;                  /* 폴백 리플로우 최소화, 실측 후 미세조정 */
  unicode-range:U+AC00-D7A3,U+0020-007E;
}
```
**주의: 서브셋 방식은 표제 문구를 바꿀 때마다 재생성해야 합니다.** 이 운영 부담이 부담스러우면 5단계를 통째로 건너뛰세요 — 1~4단계만으로도 이득의 대부분이 나옵니다.

### 3) 라틴 모노 — 도입하지 않는다 (또는 아주 좁게)

심사된 방향 셋 모두가 IBM Plex Mono를 계측 라벨용으로 제안했지만, 문제는 **제안된 슬러그 내용이 전부 한글이라는 점**입니다(「표본 36 생활권 · 단위 세대 · 2026.07 기준」). Plex Mono에는 한글 글리프가 없어 한 줄 안에서 폰트가 갈리고 11px에서 베이스라인·x-height가 어긋납니다. 게다가 '쿨 그레이 + 라틴 모노 캡션'은 금지된 3종을 피한 게 아니라 **네 번째 AI 디폴트(데이터 터미널 룩)** 입니다.

대신 숫자는 이렇게 분리합니다:
- 기존 `font-variant-numeric:tabular-nums` **9곳을 전부 승계**하고(.rc-score .vs-score #stat-tbl td table.adv .rank-tbl .sc-val .lz-val .calc-kv b), 아직 안 걸린 숫자 자리까지 확대. Pretendard는 tnum을 지원합니다.
- 숫자의 '다른 재질'은 서체가 아니라 **위치**로 만듭니다 — 우측 고정 열 + 먹색 + 라벨보다 한 단계 큰 크기.
- 정말 모노가 필요하면 **순수 숫자·라틴 토큰에만**(07-18, n=36, 12,400) 적용하고 한글이 한 글자라도 섞이면 Pretendard로 — 이 규칙을 지킬 수 없으면 아예 넣지 마세요.

## 웨이트 배급제 — 이게 진짜 처방이다

현재 800×84, 700×55. **800은 전면 금지**(→0회). 허용 웨이트는 400(본문) / 500(강조·라벨) / 600(소제목·계측 숫자) / 700 세 자리뿐:
1. 히어로 표제
2. 발산 막대의 값과 순위 1~3위
3. 현재 활성 네비 탭

굵기를 아껴야 굵기가 다시 신호가 됩니다. 위계는 웨이트가 아니라 **(1) 괘선 굵기 3단, (2) 먹/주석 2색, (3) 우측 숫자열의 크기 대비**로 만듭니다.

## 조판 규칙 (한국어)

- `text-transform:uppercase` 7회 **전량 삭제** — 한글에 아무 효과가 없습니다.
- `letter-spacing:.16em`(4회), `.hs-kicker`의 `.14em` **전량 삭제** — 이미 정사각 프레임인 한글을 낱글자로 흩뜨립니다. 한글 자간은 -0.01em~0 범위만, 양수 자간은 라틴 전용 최대 .04em.
- 히어로의 `letter-spacing:-.025em`도 폐기(과도).
- `word-break:keep-all` + `overflow-wrap:break-word` **유지** — 한국어 조판을 아는 사람의 선택입니다.
- `clamp(30px,6.4vw,48px)` 같은 자유 유동값 폐기, 스케일 9단 고정: 디스플레이 3단(clamp(26px,7vw,40px) / 24 / 19) · 본문 3단(16 / 15 / 13) · 원부 3단(13 / 12 / 11).

## ⚠️ 반드시 동봉해야 할 것 — Chart.js 재렌더

`index.html:1469`의 `Chart.defaults.font.family=FONT`는 init 시점에 텍스트를 한 번 래스터화하고, 폰트 로드 이벤트로 다시 그리지 않습니다. **링크만 넣으면 14개 차트만 맑은 고딕으로 남아 본문과 어긋납니다.** 현재 차트 인스턴스를 모아둔 배열조차 없으므로:

```js
const CHARTS = [];
// new Chart( 14곳을 → CHARTS.push(new Chart( … )) 로 변경
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => CHARTS.forEach(c => c.update()));
}
```
이걸 1단계 커밋에 포함하지 않으면 리디자인 첫걸음부터 통계 탭이 깨져 보입니다.

## PWA 함정

`sw.js:43`이 `if (url.origin !== self.location.origin) return;`로 cross-origin을 흘려보내므로 jsdelivr 폰트는 SW 캐시에 잡히지 않습니다. 오프라인 상태에서는 폰트가 안 와서 **지금 탈출하려는 그 OS 기본 폰트 화면으로 정확히 되돌아갑니다.** 5단계의 자체 호스팅 서브셋은 same-origin이라 SW 프리캐시가 가능하다는 점이 CDN 대비 부가 이점입니다.

## 적용 단계 — 보류 중

### 1. Pretendard 실제 로딩 + Chart.js 재렌더 (한 커밋)

head에 preconnect + pretendardvariable-dynamic-subset.css 링크 2줄 추가. 동시에 new Chart( 14곳을 const CHARTS=[] 배열에 담고 document.fonts.ready.then(()=>CHARTS.forEach(c=>c.update())) 추가. 배포 전 curl -sI로 CDN 200 확인 필수. 선택자·font-family 수정 0줄 — 이미 'Pretendard'가 첫 순위로 적혀 있다.

**리스크 / 되돌리기:** 되돌리기: 링크 2줄 삭제로 즉시 원복. 실패 모드는 CDN 경로 404 하나뿐이고 curl로 사전 차단된다. 차트 재렌더를 빠뜨리면 통계 탭만 맑은 고딕으로 남으므로 반드시 동봉. FOUT은 dynamic-subset + font-display:swap 기본값으로 완화되나, 첫 방문 시 히어로에서 미세한 리플로우가 보일 수 있다.

### 2. 웨이트 배급제 — 800 전면 제거

단일 style 블록 내 font-weight:800(84회) → 600 일괄 치환. 이어서 700(55회)을 지정 3자리(히어로 표제 / 발산 막대 값·순위 1~3위 / 활성 네비 탭)만 남기고 500~600으로 하향. 같은 스윕에서 text-transform:uppercase 7회, letter-spacing:.16em 4회, .hs-kicker의 .14em, 히어로의 -.025em 삭제.

**리스크 / 되돌리기:** 되돌리기: 단일 style 블록 안의 기계적 치환이라 git revert 한 번. 병렬 세션과 충돌 위험이 낮다(89/92 radius, 대부분 weight 선언이 한 블록에 몰려 있음). 1단계 없이 이것만 하면 효과가 반감되지만 해롭지는 않다. 반대로 1단계만 하고 이걸 안 하면 진짜 800 자족이 생겨 오히려 더 무거워지므로 순서를 지킬 것.

### 3. radius 2값화 + 발산 막대 데이터 왜곡 수정

--r-data:0 / --r-touch:3px 도입. 최우선으로 index.html:716,720의 .sc-track/.sc-fill border-radius:8px → 0 (높이 14px에 반경 8px이라 양 끝이 완전히 말려 값을 왜곡 중). 이어 표·차트박스·타일맵·표두를 0으로, 하단 4탭·퀴즈 선지·버튼·인풋을 3px로. 999px 알약 3회와 장식용 50% 원(.hero::after/.hero::before/.home-hero::after) 삭제.

**리스크 / 되돌리기:** 되돌리기 쉬움 — 순수 CSS, HTML 구조 무변경. 위험 0에 이득 확정인 유일한 항목이며, 리디자인 채택 여부와 무관하게 값어치가 있다. 알약 배지 12종을 한꺼번에 없애면 티어·평가처럼 폰에서 훑을 때 실제로 일하는 신호까지 죽을 수 있으니, 배지는 사각 칩(radius 0 + 좌측 3px 컬러 바)으로 '형태만' 바꾸고 정보는 남길 것.

### 4. 색 토큰 전환 — 원자적 커밋 (분할 금지)

:root 7줄(--paper/--paper2/--line/--ink/--ink2/--muted 교체, --gwaing 신규, --accent/--gold/--gold-ink 폐기) + JS 상수 4줄(index.html:1467의 INK/INK2/GRID/MUTED) + 하드코딩 웜 뉴트럴 18종 회수 + 사용 1~3회짜리 #d2342a·#b23022·#1565c0·#2c5f9e 회수. 생짜 회색 #444(×5)·#333·#222·#666·#4a4a4a → --muted.

**리스크 / 되돌리기:** ⚠️ 이 단계만 부분 적용이 허용되지 않는다. --paper는 CSS에서 4번밖에 안 쓰이므로 토큰만 쿨 축으로 옮기면 하드코딩된 웜 60여 개가 '때 낀 종이'로 보여 현재보다 나빠진다. 반드시 한 커밋. 또 #a93226(20회)·#e0564a(27회)는 이 단계에서 건드리지 말 것 — index.html:1479~1892 구간에서 Chart.js 데이터셋 색으로도 쓰여 계열 구분을 담당할 수 있으므로, 각 사용처를 눈으로 확인한 뒤 --maemae-d/--maemae-l 3단 램프로 승격시키는 별도 작업으로 뺀다.

### 5. 표두(表頭) 도입 — 아이브로우 전량 교체

.hs-kicker 6곳 + eyebrow/home-eyebrow/qeyebrow/qresult-eyebrow 5곳을 표두로 교체. 좌: 「표N · 제목」, 우측 정렬: 「(단위: 호)」, 아래 줄: 「n=36 · 07-18 기준 · 출처」, 그 아래 겹줄. 갱신일 값은 코드가 이미 갖고 있다. 「10문항 · 3분 · 즉시 채점」류 3연발 메타는 각주 줄로 강등. 형용사가 들어가면 삭제하는 규칙을 적용.

**리스크 / 되돌리기:** HTML 마크업 11군데를 건드리므로 병렬 세션과 충돌 가능성이 처음 생긴다 — 커밋 직전 pull, 커밋 직후 push. 되돌리기는 CSS 클래스 하나 되살리는 수준. 어떤 팔레트·서체와도 결합돼 있지 않아 앞 단계가 하나라도 실패해도 그대로 얹힌다. 심사된 네 방향 전부가 이걸 bestIdea로 지목한 유일한 항목이다.

### 6. 카드 해체 — 괘선·밴드·흰색 배급제

'흰 카드 + --line + 라운드 + 그림자' 15개 클래스(.chartbox .conf .hcol .qpick-card .qopt .nextstep .subs .ctrl .rank-wrap .adv-tblwrap .tbl-wrap .calc-card .calc-out .hcard .adv-links a)를 순차 해체. 구획은 괘선 3종으로만 — 2.5px 먹색=장 경계, 겹줄=표두/데이터 경계, 1px --line=행 구분. 흰색 규칙: #fff는 '숫자가 있는 표 본문 영역'에만. 리듬은 .howto 다크 밴드 패턴을 확장해 만든다. hover translateY, transition:.15s 7회, .tldr-arrow 무한 바운스, 장식용 각도 그라디언트 4개(.rcard .versus.win/.lose/.draw .hcard.feat) 삭제.

**리스크 / 되돌리기:** 가장 큰 단계이므로 반드시 클래스 2~3개씩 쪼개서 커밋. 한 번에 15개를 건드리면 중간 상태가 전부 깨져 보이고 병렬 세션 충돌이 확정적이다. 선행 조건: 4단계의 --line #C4CEC9가 --paper 대비 1.52:1을 확보해야 괘선만으로 구획이 성립한다 — 이게 안 되면 화면이 그냥 무너지므로 4단계 배포 후 실제 폰에서 야외 밝기로 눈으로 확인하고 진행할 것.

### 7. 시그니처 — 관통 0선 + 우측 고정 숫자열

.sc-track::before(index.html:718)의 행별 0선을 제거하고, 축 범례~36행~각주를 관통하는 단 하나의 연속 1px 먹색 선을 컨테이너에 절대 위치로 건다. 동시에 .sc-row를 고정폭 라벨 컬럼 grid로 재구성해 모든 행의 0이 같은 x에 오게 하고, 세대수는 막대 끝이 아니라 우측 고정 열에 tabular-nums로 정렬. 부호는 절대값 표기(방향·색이 이미 부호를 인코딩).

**리스크 / 되돌리기:** HTML 구조를 건드리는 유일한 단계라 가장 위험하고 되돌리기도 가장 어렵다 — 반드시 마지막에, 별도 브랜치에서. @media(max-width:400px)의 .sc-row 축소 블록은 '반드시 .sc-val/.sc-tier 정의 뒤에 와야 덮어쓴다'는 실측 기반 주석이 달려 있으므로 선택자 순서를 절대 바꾸지 말 것. 범위를 스코어 블록 내부로 한정 — 페이지 전체 관통은 flex 트랙과 14개 canvas 때문에 불가능하고, 한 군데만 어긋나도 시그니처가 자기파괴적이 된다. 세로쓰기 「0 적정공급」 라벨은 모바일 393px에서 폭을 먹고 정렬이 깨지므로 검증 전에는 붙이지 말 것.

### 8. [선택] 마루부리 표제 서브셋 자체 호스팅

pyftsubset으로 실제 표제 글자만 뽑아 20~40KB woff2를 만들고 /fonts에 자체 호스팅. SemiBold 600 한 벌만. font-display:swap + unicode-range 지정. same-origin이라 sw.js 프리캐시도 가능해진다.

**리스크 / 되돌리기:** 운영 부담이 실질적이다 — 표제 문구를 바꿀 때마다 서브셋을 재생성해야 하고, 빠뜨리면 그 글자만 폴백 폰트로 튄다. 이 부담이 부담스러우면 통째로 건너뛸 것. 1~7단계만으로 이득의 대부분(타이포 부재 40% 중 대부분, 장식 25%, 베이지 25%)이 이미 나온다. FOUT이 하필 히어로 표제에서 터지므로 size-adjust 실측 조정을 반드시 거칠 것.

## 탈락 방향에서 흡수한 아이디어

- 【instrument】 계측 슬러그의 '형용사 금지' 판정 규칙 — 아이브로우를 없애는 방법으로 '더 작게/더 얇게'가 아니라 '수량·단위·기간·기준일·출처 다섯 종만 허용, 형용사가 들어가면 그건 아이브로우이므로 삭제'라는 집행 가능한 판정 규칙을 준 것. 표두 뼈대에 그대로 얹혀 표두 내용물의 채택 기준이 되었다. 이게 없으면 표두도 결국 새로운 아이브로우가 된다.
- 【material·cadastre】 검증 가능한 사실 3종(갱신일·표본수 n=36·출처)의 상시 노출과 '인코딩할 사실이 없는 섹션에는 마커를 달지 않는다'는 규칙. 회의적인 매수자가 가장 먼저 던지는 질문에 묻기 전에 답한다 — 어떤 시각적 변경보다 신뢰에 직결된다. 갱신일 값은 코드가 이미 갖고 있어 구현 비용이 사실상 0이다.
- 【instrument·material】 흰색 배급제 — #fff를 색이 아니라 '재료'로 재정의해 '값이 있는 면'에만 배급하는 규칙. CSS 블록에만 background:#fff가 78회 떠 있는 게 바탕을 때 타 보이게 만드는 진짜 원인이라는 진단이 정확했다. 6단계 카드 해체의 판정 기준으로 채택 — '카드를 줄여라'는 잔소리가 아니라 줄일 수밖에 없는 기준을 준다.
- 【instrument·cadastre】 radius를 스타일이 아니라 데이터 진실로 재정의 — '잰 것은 각지고, 누르는 것만 3px'. 실측으로 확인했다: index.html:716의 .sc-track이 height:14px에 border-radius:8px이라 시그니처 지표의 막대 양 끝이 실제로 말려 값을 왜곡 중이다. 위험 0 + 이득 확정인 유일한 항목이라 3단계로 앞당겼다.
- 【cadastre】 데이터 색의 UI 크롬 전면 추방 — 빨강을 버튼·링크·탭·배지에 절대 쓰지 않아, 화면에 빨강이 보이면 그건 언제나 '공급 부족/상승'이 되게 하는 것. 데이터 색 의미론이 '지켜지는 것'에서 '구조적으로 위반 불가능한 것'으로 격상된다. --accent와 --gold 폐기의 근거가 되었다.
- 【material·instrument·cadastre 공통】 웨이트 예산제 — 800 전면 금지, 700은 지정 3자리만. 세 방향이 독립적으로 같은 결론에 도달했다는 것 자체가 강한 신호다. 다만 material/instrument의 '디스플레이를 300 Light로 크게' 뒤집기는 채택하지 않았다 — 7억을 쓰려는 30~40대에게 '냉정한 계측'이 아니라 '멋부린 라이프스타일'로 읽힐 위험이 절반은 되고, 하필 한글 받침이 가장 잘 뭉개지는 큰 글자·야외 밝기 구간에 리스크를 쓴다.
- 【cadastre】 Chart.js 폰트 재렌더 트랩 — 링크만 넣으면 14개 차트만 맑은 고딕으로 남는다는 코드베이스 고유의 함정. 실측 확인했다(index.html:1466 FONT 상수, :1469 Chart.defaults.font.family, new Chart( 14회, 인스턴스 배열 없음). 1단계 커밋의 필수 구성요소로 편입했다. 이걸 빠뜨리면 리디자인 첫걸음부터 통계 탭이 깨져 보인다.
- 【ledger 킬샷의 자기교정】 숫자를 막대 끝이 아니라 우측 고정 열에 정렬 — 원안이 원부를 인용하면서 원부의 가장 기능적인 규칙을 어긴 부분. 사용자의 실제 행동이 '위아래 행과 비교'이므로 x좌표가 행마다 움직이면 tabular-nums 도입 이득이 상쇄된다. 시그니처 정의에 반영했다.
- 【material】 막대를 '길이 비교'에서 '세는 도구'로 바꾸는 양자화 발상 — 단, 셀=1,000세대라는 거짓 정밀도는 버렸다. index.html:3112의 Math.sqrt(Math.abs(u.tot)/mx)*50 때문에 막대가 제곱근 스케일이라 위치마다 셀당 세대수가 달라져, 셀 텍스처는 '셀 수 있다'고 암시하면서 실제로는 못 세는 상태가 된다 — 균일한 단색 fill보다 오히려 부정직하다. 정직하게 축소해 흡수: repeating-linear-gradient로 굵은 눈금만 얹되, 제곱근 스케일 하에서는 눈금 간격도 비선형이 되므로 '이 눈금은 등간격이 아니다'를 각주에 명시하거나 아예 생략할 것.
