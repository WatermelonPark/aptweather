# -*- coding: utf-8 -*-
"""배치 단계 기록(_batch_report.txt)을 **받는 사람의 말**로 된 알림 본문으로 바꾼다.

왜 따로 떼어냈나. 문구 조립을 워크플로 셸에 두면 시험할 방법이 없다. 이 저장소가
반복해서 당한 게 '안 도는 방어선'이라, 사람에게 닿는 마지막 1미터도 시험 가능한
자리에 둔다(tools/tests/test_batch_report.py).

원칙 세 가지 (PM 요청서 2026-09-12).
  1. 첫 줄이 결론, 둘째 줄이 할 일. 기계 안에서 무슨 일이 있었나가 아니라
     '내 사이트는 괜찮은가, 내가 뭘 해야 하나'를 먼저 적는다.
  2. 정상이면 확인된 항목을 나열하지 않는다. 읽을 것이 없어야 정상이다.
  3. 실패는 반대로 **무엇이 안 됐는지 이름을 밝힌다.** '일부 단계 실패'는 알림이 아니다.

⚠️ 멘션(@소유자)은 메일 발송 스위치다. 코멘트 알림은 구독자에게만 가지만 멘션은
   구독과 무관하게 메일이 간다. 그래서 멘션을 항상 붙이면 정상 회차에도 매일 메일이
   가고, 그게 쌓이면 진짜 경보가 묻힌다. 붙이는 경우를 좁게 둔다:
     실패했을 때 · 점검 이상일 때 · 월요일 회차(살아 있다는 신호)
   침묵이 곧 정상을 뜻하게 만드는 것이 목적이다.

⚠️ 단계별 상세를 지우는 대상은 **메일 본문**뿐이다. 실행 로그 링크는 항상 남기고,
   화면 요약(GITHUB_STEP_SUMMARY)에는 원본 기록을 그대로 붙인다 — 세션이 파고들
   입구가 없어지면 안 된다.

사용:
    python tools/format_batch_report.py _batch_report.txt \
        --kst "2026-09-12 21:52" --run-url URL --owner NAME [--weekday 0]
"""
import argparse
import io
import re
import sys

# 상태 표시 → 심각도. 기록의 각 줄은 이 중 하나로 시작한다(rep() 호출부 참조).
BAD = '❌'
WARN = '⚠️'
OK = '✅'
SKIP = '➖'


def _month_day(s):
    """'2026-09-07' → '9월 7일'. 못 읽으면 원문 그대로."""
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s.strip())
    return '%d월 %d일' % (int(m.group(2)), int(m.group(3))) if m else s.strip()


def _year_month(s):
    """'2026-07' / '2026.07' → '2026년 7월'."""
    m = re.match(r'^(\d{4})[-.](\d{2})$', s.strip())
    return '%s년 %d월' % (m.group(1), int(m.group(2))) if m else s.strip()


def _quarter(s):
    """'2026Q2' → '2026년 2분기'."""
    m = re.match(r'^(\d{4})Q([1-4])$', s.strip())
    return '%s년 %s분기' % (m.group(1), m.group(2)) if m else s.strip()


def basis_line(lines):
    """'채택 주간 … / 월간 … / 공급 …' 줄에서 사람이 읽는 기준 시점 문장을 만든다.

    이 값들은 정상일 때 유일하게 쓸모 있는 정보다 — 사이트가 '언제 기준'인지는
    받는 사람이 실제로 확인하고 싶어 하는 것이라, 정상 본문에도 남긴다.
    """
    for ln in lines:
        m = re.search(r'채택\s*주간\s*(\S+)\s*/\s*월간\s*(\S+)\s*/\s*공급\s*(\S+)', ln)
        if not m:
            continue
        wk, mo, sl = m.group(1), m.group(2), m.group(3)
        parts = []
        if wk not in ('-', '--'):
            parts.append('주간 시세 %s' % _month_day(wk))
        if mo not in ('-', '--'):
            parts.append('월간 통계 %s' % _year_month(mo))
        if sl not in ('-', '--'):
            parts.append('공급 %s' % _quarter(sl))
        return (' · '.join(parts) + ' 기준') if parts else ''
    return ''


# 내부 기록 → 받는 사람의 말. 앞에서부터 처음 걸리는 것을 쓴다.
# ⚠️ '무엇이' 안 됐는지가 남아야 한다. 뭉뚱그리면 알림이 아니라 소음이 된다.
PLAIN = (
    (r'러너 0/3 clean.*재시도로 낫지 않는',
     '통계청에서 데이터를 받아오지 못했습니다(3번 시도). 재시도로 낫는 종류가 아니라 '
     '바로 알립니다 — 접속 열쇠 만료나 코드 이상일 수 있습니다.'),
    (r'러너 0/3 clean.*자동 재시도',
     '통계청에서 데이터를 받아오지 못했습니다(3번 시도). 접속이 막힌 것으로 보이며 '
     '35분 뒤 다시 받습니다.'),
    (r'러너 0/3 clean.*소진',
     '통계청에서 데이터를 받아오지 못했습니다(재시도 3회 모두). 이번 회차는 갱신을 '
     '건너뛰고 다음 회차에 다시 받습니다.'),
    (r'산출물 복사 실패',
     '받아온 데이터가 불완전해 반영하지 않았습니다.'),
    (r'테스트 실패',
     '새 코드가 검사를 통과하지 못해 반영을 멈췄습니다. 숫자가 틀어진 데이터가 '
     '사이트에 올라가지 않도록 막은 것이지 고장 난 것이 아닙니다.'),
    (r'테스트 건너뜀',
     '검사 도구를 설치하지 못해 검사를 건너뛰었습니다(설비 문제).'),
    (r'지역페이지 실패', '시도별 공급 페이지를 다시 만들지 못했습니다.'),
    (r'지표페이지 실패', '입주물량·전세가율 페이지를 다시 만들지 못했습니다.'),
    (r'이달의 통계 실패', '이달의 통계 페이지를 다시 만들지 못했습니다.'),
    (r'사이클 리포트 실패', '사이클 리포트를 다시 만들지 못했습니다.'),
    (r'공유카드 실패',
     '공유용 이미지를 다시 만들지 못했습니다. 카카오·블로그에 옛 주차 그림이 '
     '보일 수 있습니다.'),
    (r'공유카드 건너뜀',
     '그림 도구가 없어 공유용 이미지를 건너뛰었습니다(설비 문제).'),
    (r'git add 실패|git commit 실패', '사이트에 반영하는 단계에서 실패했습니다.'),
    (r'푸시 3회 실패',
     '사이트 반영을 3번 시도했으나 실패해 이번 회차 결과가 유실됐습니다. '
     '누군가 같은 줄을 고쳤을 수 있습니다.'),
    (r'IndexNow 실패',
     '검색엔진에 새 내용을 알리지 못했습니다. 데이터는 정상이고 검색 반영만 늦어집니다.'),
    (r'감시가 \d+시간째 안 돌았|감시 실행 이력을 읽지 못',
     '점검 작업이 예정대로 돌지 않았습니다. 데이터가 뒤처져도 알아채지 못할 수 있습니다.'),
    (r'배치가 보고 지점 전에 중단',
     '배치가 도중에 멈춰 어디까지 됐는지 기록이 남지 않았습니다.'),
)


def plain(line):
    """기록 한 줄 → 사람의 말. 대응이 없으면 표시만 떼고 원문을 쓴다."""
    body = line.lstrip(''.join((BAD, WARN, OK, SKIP))).strip()
    for pat, say in PLAIN:
        if re.search(pat, body):
            return say
    return body


def build(raw, kst, run_url, owner, weekday):
    """기록 전문 → (본문, 멘션여부).

    weekday: 0=월 … 6=일. 월요일 회차 한 번은 정상이어도 멘션을 붙여 '살아 있다'를
    알린다. 침묵이 길어지면 사람은 도는지 의심하게 되고, 그건 침묵의 값을 떨어뜨린다.
    """
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    bad = [ln for ln in lines if ln.lstrip().startswith(BAD)]
    warn = [ln for ln in lines if ln.lstrip().startswith(WARN)]
    nothing = any(ln.lstrip().startswith(SKIP) for ln in lines)
    basis = basis_line(lines)

    out = []
    if bad:
        out.append('### ⚠️ 데이터 갱신 중단 · %s' % kst)
        out.append('')
        out.append('**사이트는 정상입니다.** 다만 새 데이터가 반영되지 않아 이전 '
                   '시점 그대로입니다.')
        out.append('')
        out.append('**하실 일: 없습니다.** 세션에서 원인을 확인하고 고칩니다. '
                   '사흘 넘게 이 메일이 계속 오면 그때 알려 주세요.')
        out.append('')
        out.append('**무슨 일인가:**')
        for ln in bad:
            out.append('- %s' % plain(ln))
        for ln in warn:
            out.append('- %s' % plain(ln))
    elif warn:
        out.append('### ⚠️ 데이터 갱신은 됐지만 확인할 것이 있습니다 · %s' % kst)
        out.append('')
        out.append('**사이트는 최신 데이터로 갱신됐습니다.** 곁가지 하나가 '
                   '제대로 되지 않았습니다.')
        out.append('')
        out.append('**하실 일: 없습니다.** 세션에서 확인합니다.')
        out.append('')
        out.append('**무슨 일인가:**')
        for ln in warn:
            out.append('- %s' % plain(ln))
        if basis:
            out.append('')
            out.append(basis)
    else:
        out.append('### ✅ 데이터 갱신 정상 · %s' % kst)
        out.append('')
        if nothing:
            out.append('원천 통계가 그대로라 바뀐 내용이 없습니다. 사이트는 최신 '
                       '상태입니다. 하실 일 없습니다.')
        else:
            out.append('사이트가 최신 데이터로 갱신됐습니다. 하실 일 없습니다.')
        if basis:
            out.append('')
            out.append(basis)

    mention = bool(bad or warn) or weekday == 0
    if mention and weekday == 0 and not (bad or warn):
        out.append('')
        out.append('(월요일 확인 메일입니다. 이상이 있을 때만 메일이 가고, 평소에는 '
                   '조용합니다.)')
    out.append('')
    tail = '[실행 로그](%s)' % run_url
    if mention:
        tail += ' · @%s' % owner
    out.append(tail)
    return '\n'.join(out) + '\n', mention


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('report')
    ap.add_argument('--kst', required=True)
    ap.add_argument('--run-url', required=True)
    ap.add_argument('--owner', required=True)
    ap.add_argument('--weekday', type=int, required=True, help='0=월 … 6=일')
    a = ap.parse_args(argv)
    raw = io.open(a.report, encoding='utf-8', errors='replace').read()
    body, _ = build(raw, a.kst, a.run_url, a.owner, a.weekday)
    sys.stdout.write(body)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    raise SystemExit(main())
