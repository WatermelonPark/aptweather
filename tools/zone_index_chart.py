# -*- coding: utf-8 -*-
"""zone_index.json -> 생활권별 지수 곡선 소형 다중 차트(HTML, 인라인 SVG)."""
import io, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'cache', 'zone_index.json')
OUT = os.path.join(HERE, 'cache', 'zone_index.html')

W, H = 300, 110
PAD_L, PAD_R, PAD_T, PAD_B = 30, 6, 10, 16


def spark(months, vals, troughs):
    if not vals:
        return ''
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)

    def X(i):
        return PAD_L + (W - PAD_L - PAD_R) * (i / max(1, n - 1))

    def Y(v):
        return PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / rng)

    pts = ' '.join('%.1f,%.1f' % (X(i), Y(v)) for i, v in enumerate(vals))
    s = ['<polyline fill="none" stroke="#2563eb" stroke-width="1.4" points="%s"/>' % pts]
    idx = {m: i for i, m in enumerate(months)}
    for t in troughs:
        i = idx.get(t['m'])
        if i is None:
            continue
        col = '#9ca3af' if t.get('unconf') else '#dc2626'
        s.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>' % (X(i), Y(vals[i]), col))
        s.append('<text x="%.1f" y="%.1f" font-size="8" fill="%s" text-anchor="middle">%s</text>'
                 % (X(i), min(H - 4, Y(vals[i]) + 11), col, t['m'][2:4] + "'" + t['m'][5:7]))
    # y축 라벨(최저/최고)
    s.append('<text x="2" y="%.1f" font-size="8" fill="#888">%.0f</text>' % (Y(hi) + 3, hi))
    s.append('<text x="2" y="%.1f" font-size="8" fill="#888">%.0f</text>' % (Y(lo) + 3, lo))
    # x축 연도 눈금
    for i, m in enumerate(months):
        if m.endswith('-01') and int(m[:4]) % 5 == 0:
            s.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#e5e7eb"/>' % (X(i), PAD_T, X(i), H - PAD_B))
            s.append('<text x="%.1f" y="%d" font-size="8" fill="#888" text-anchor="middle">%s</text>'
                     % (X(i), H - 4, m[:4]))
    return '<svg viewBox="0 0 %d %d" width="100%%">%s</svg>' % (W, H, ''.join(s))


def main():
    rep = json.load(io.open(SRC, encoding='utf-8'))
    zs = rep['maega']['zones']
    order = sorted(zs, key=lambda z: -(zs[z]['vals'][-1] if zs[z]['vals'] else 0))
    cards, rows = [], []
    for z in order:
        d = zs[z]
        if not d['vals']:
            continue
        cur = d['vals'][-1]
        tr = d['troughs']
        conf = [t for t in tr if not t.get('unconf')]
        last = conf[-1] if conf else None
        gain = ((cur / last['v'] - 1) * 100) if last else None
        mem = ', '.join(m['nm'].split('>')[-1] for m in d['members'])
        cards.append(
            '<div class="c"><h3>%s <span class="n">%s</span></h3>%s<div class="m">%s</div></div>'
            % (z, ('저점 %s 이후 %+.0f%%' % (last['m'], gain)) if last else '저점 없음',
               spark(d['months'], d['vals'], tr), mem))
        rows.append('<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td class="r">%s</td></tr>'
                    % (z, len(d['members']),
                       ' · '.join('%s(-%.0f%%)%s' % (t['m'], t['dd'], '?' if t.get('unconf') else '') for t in tr) or '—',
                       last['m'] if last else '—',
                       ('%+.0f%%' % gain) if gain is not None else '—'))
    html = """<!doctype html><meta charset="utf-8"><title>생활권 아파트 매매지수 곡선</title>
<style>body{font:13px/1.5 system-ui,'Malgun Gothic',sans-serif;margin:20px;color:#111}
h1{font-size:19px}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.c{border:1px solid #e5e7eb;border-radius:6px;padding:8px}
.c h3{margin:0 0 2px;font-size:13px}.c .n{font-weight:400;color:#dc2626;font-size:11px}
.m{color:#888;font-size:10px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table{border-collapse:collapse;margin:18px 0;font-size:12px}
td,th{border-bottom:1px solid #eee;padding:4px 10px;text-align:left}.r{text-align:right}
p.note{color:#666;font-size:12px;max-width:900px}
.v{background:#f8fafc;border-left:3px solid #2563eb;padding:10px 14px;margin:14px 0;max-width:900px;font-size:12px}
.v ul{margin:6px 0 6px 18px;padding:0}</style>
<h1>생활권별 아파트 매매지수 곡선 (R-ONE A_2024_00045, 2003-11~)</h1>
<p class="note">시군구 지수를 생활권 멤버별 <b>누적 준공 세대(HUB)</b>로 가중평균했다.
빨간 점 = <b>확정 저점</b>(중심 &plusmn;12개월 최소 &amp; 직전 고점 대비 3%% 이상 하락). 회색 점 = 최근 12개월 이내라 아직 확정 불가(더 내려갈 수 있음).
저점은 기준표 모형에서 &quot;재고 소진 시점 + 약 1년&quot;에 대응한다 &mdash; 존별 적정물량 역산의 기준점.</p>
<div class="v"><b>공급 &rarr; 가격 검증 (tools/zone_index_xcheck3.py)</b><br>
시점별 전국 평균을 빼고(=전국 공통 사이클 제거) 남은 존별 편차만으로 물었다:
공급이 유난히 많았던 존은 그 뒤 가격이 덜 올랐는가?
<ul>
<li><b>전 구간에서는 신호가 안 잡힌다</b> &mdash; r = &minus;0.089, 순열검정 p = 0.09.
2013&middot;2023년에 44개 존 중 각각 19&middot;23곳이 <i>동시에</i> 저점을 찍는다. 금리&middot;정책이 압도한다.</li>
<li><b>금리 급변 구간을 빼면 살아난다.</b> 예측창(2년) 안에서 기준금리가 크게 움직인 관측을
단계적으로 버리면 상관이 단조로 강해진다: &minus;0.089 &rarr; &minus;0.120(잔잔한 50%%, p=0.039)
&rarr; &minus;0.178(잔잔한 30%%, p=0.022). 주담대금리로 갈라도 같은 방향.</li>
<li>소급 8~16분기 &times; 향후 4~16분기 <b>12개 조합 전부 음(&minus;)</b>, 9개가 p&lt;0.05(나머지도 0.05~0.055).
시계가 길수록 강해진다(향후 4년 r = &minus;0.19).</li>
<li>존을 하나씩 빼도 r = &minus;0.076 ~ &minus;0.139로 유지 &mdash; 특정 존이 끄는 게 아니다.
기간을 반으로 갈라도 전반 &minus;0.088 / 후반 &minus;0.146으로 양쪽 다 성립.</li>
<li>크기: 금리가 잔잔할 때 공급 최저 25%% 존이 최고 25%% 존보다 향후 2년 <b>+2.2%%p</b> 더 오른다.</li>
</ul>
<b>함의:</b> 생활권 단위 공급&rarr;가격 관계는 <b>실재하되 금리에 가려져 있다</b>.
따라서 적정물량 캘리브레이션은 (a) 저점 1~2개를 역산하는 방식이 아니라
<b>금리 잔잔한 구간 전체를 써서 존별 적정물량을 직접 적합</b>하는 방식이어야 하고,
(b) 금리 급변기를 학습에서 빼야 한다. 순열검정은 존 라벨을 통째로 섞는 방식이라
존별 자기상관과 시간구조를 보존한다.<br>
<span style="color:#888">한계: 금리 잔잔 구간만 쓰면 표본이 절반(약 30분기)으로 줄고,
&quot;잔잔함&quot;의 컷오프는 사후 선택이다. 방어 근거는 8개 컷오프 &times; 2개 금리지표에서
모두 단조라는 점이지 특정 컷이 아니다.</span></div>
<table><tr><th>생활권</th><th>시군구</th><th>저점(하락폭)</th><th>최근 저점</th><th>현재까지</th></tr>%s</table>
<div class="g">%s</div>""" % (''.join(rows), ''.join(cards))
    io.open(OUT, 'w', encoding='utf-8').write(html)
    print('saved', OUT)


if __name__ == '__main__':
    main()
