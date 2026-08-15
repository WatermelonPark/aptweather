/* 지역 페이지 표 동작 — make_sido_pages.zone_js()가 생성한다. 직접 고치지 말 것. */
(function(){
/* 표의 기본 화면을 맨 아래(미래 분기)로 — 공급을 보러 온 사람이 매번
   28행을 내리게 하지 않는다(2026-08-11 사용자). 과거는 올리면 된다. */
document.querySelectorAll(".ztb-scroll").forEach(function(e){e.scrollTop=e.scrollHeight});
/* 안내 문구는 make_sido_pages.REFNOTE 정본을 그대로 실어 손으로 옮기지 않는다. */
var ZREFNOTE={"un": "미분양은 다 짓고도 팔리지 않아 남아 있는 집입니다(국토교통부 월간 집계). 이미 지어진 재고에 들어 있어 순위 계산에 다시 넣으면 이중계산이라, 참고로만 보여줍니다.", "pm": "인허가는 \"짓겠다\"고 허가받은 단계의 물량으로, 보통 3~4년 뒤 입주로 이어져 이 표의 마지막 분기 너머를 미리 보여줍니다. 월별 들쭉날쭉이 커서 최근 12개월 합으로 묶어 연간 적정물량과 견주고, 실제 착공은 이보다 적어 순위 계산에는 착공만 씁니다."};
document.querySelectorAll(".ztb tfoot tr.zref").forEach(function(tr){
tr.addEventListener("click",function(){
var p=document.getElementById("zrefnote");if(!p)return;
var k=tr.getAttribute("data-ref");
if(!p.hidden&&p.dataset.k===k){p.hidden=true;}
else{p.dataset.k=k;p.textContent=ZREFNOTE[k]||"";p.hidden=false;
/* 탭한 행이 화면 맨 밑이면 설명이 폴드 아래 열린다(모바일) —
   nearest라 이미 보이면 안 움직인다. */
p.scrollIntoView({block:"nearest"});}
document.querySelectorAll(".ztb tfoot .rbtn").forEach(function(b){
var own=b.parentNode.parentNode.getAttribute("data-ref");
b.setAttribute("aria-expanded",(!p.hidden&&own===p.dataset.k)?"true":"false");});});});
})();
