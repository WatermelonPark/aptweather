# -*- coding: utf-8 -*-
"""GA를 부르는 페이지는 반드시 옵트아웃 스위치를 **로더보다 먼저** 갖는다.

`window['ga-disable-<ID>']`는 gtag 로드 **전에** 설정돼야 먹는 공식 플래그다.
뒤에 두면 조용히 아무 일도 안 일어난다 — 화면도 콘솔도 멀쩡하고 GA에는 계속
기록된다. 게다가 32장 중 9장이 손으로 관리하는 파일이라, 새 페이지를 하나
추가하면서 스니펫을 빠뜨리면 그 페이지만 개발자 트래픽을 다시 담기 시작한다.
사람이 기억으로 막을 일이 아니라 여기서 잠근다(2026-08-15 리뷰).

charset도 같이 본다. 인코딩 프리스캔은 문서 앞 1024바이트만 보는데, 위 스니펫의
한글 주석이 앞에 끼면서 선언이 그 밖으로 밀렸던 적이 있다 — 라이브는 서버
Content-Type이 가려주지만 file://·헤더 없는 정적 서버에서는 한글이 다 깨진다.
"""
import glob
import io
import os

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
LOADER = 'googletagmanager.com/gtag/js'
PRESCAN = 1024


def _pages():
    out = []
    for pat in ('*.html', '*/index.html', 'zone/*/index.html'):
        for p in glob.glob(os.path.join(ROOT, pat)):
            # drafts/·art_raw/는 발행물이 아니다
            if os.sep + 'drafts' + os.sep in p or os.sep + 'art_raw' + os.sep in p:
                continue
            out.append(p)
    return sorted(set(out))


def _ga_pages():
    got = []
    for p in _pages():
        t = io.open(p, encoding='utf-8').read()
        if LOADER in t:
            got.append((os.path.relpath(p, ROOT).replace(os.sep, '/'), t))
    return got


def test_there_are_ga_pages():
    """대상이 0장이면 아래 시험들이 통과해도 아무것도 안 지킨 것이다."""
    assert len(_ga_pages()) >= 30


@pytest.mark.parametrize('rel,html', _ga_pages(), ids=[r for r, _ in _ga_pages()])
def test_optout_runs_before_loader(rel, html):
    i = html.find('ga-disable-')
    assert i >= 0, '%s: GA 옵트아웃 스니펫이 없다' % rel
    assert i < html.find(LOADER), '%s: 옵트아웃이 로더보다 뒤에 있어 안 먹는다' % rel


@pytest.mark.parametrize('rel,html', _ga_pages(), ids=[r for r, _ in _ga_pages()])
def test_charset_inside_prescan_window(rel, html):
    i = html.find('<meta charset')
    assert i >= 0, '%s: charset 선언이 없다' % rel
    b = len(html[:i].encode('utf-8'))
    assert b < PRESCAN, ('%s: charset이 %d바이트째 — 프리스캔(%d) 밖이라 헤더가 없는 '
                         '환경에서 한글이 깨진다' % (rel, b, PRESCAN))
