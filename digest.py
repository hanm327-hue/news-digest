"""GeekNews RSS 다이제스트 생성기.

피드의 제목/요약만 읽어 관심 주제(AI 에이전트, 업무 자동화, 클로드)에 맞는 글을
최대 5건 골라 digest/YYYY-MM-DD.md 로 저장한다. 기사 본문 페이지는 열지 않는다.
요약은 Claude API(anthropic 패키지 + ANTHROPIC_API_KEY)가 있으면 Claude가 새로 쓰고,
없으면 피드 텍스트를 줄여 쓰는 기본 방식으로 동작한다. 그 외에는 표준 라이브러리만 쓴다.
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

FEED_URL = "https://news.hada.io/rss/news"
MAX_ITEMS = 5
MIN_SCORE = 2  # 주제별 최소 점수
BASE_DIR = Path(__file__).resolve().parent

# 주제별 키워드 (소문자 비교)
TOPICS = {
    "AI 에이전트": ["에이전트", "agent", "agentic", "mcp"],
    "업무 자동화": ["자동화", "automation", "automate", "워크플로", "workflow", "rpa", "n8n", "zapier"],
    "클로드": ["클로드", "claude", "anthropic", "앤트로픽"],
}

ATOM = "{http://www.w3.org/2005/Atom}"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "rss-digest/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    # RSS 2.0
    for it in root.iter("item"):
        items.append({
            "title": clean(it.findtext("title")),
            "summary": clean(it.findtext("description")),
            "link": (it.findtext("link") or "").strip(),
        })
    # Atom
    for en in root.iter(f"{ATOM}entry"):
        link_el = en.find(f"{ATOM}link[@rel='alternate']")
        if link_el is None:
            link_el = en.find(f"{ATOM}link")
        items.append({
            "title": clean(en.findtext(f"{ATOM}title")),
            "summary": clean(en.findtext(f"{ATOM}summary") or en.findtext(f"{ATOM}content")),
            "link": link_el.get("href", "").strip() if link_el is not None else "",
        })
    return items


def match_topics(item: dict) -> tuple[int, list[str]]:
    title = item["title"].lower()
    body = item["summary"].lower()
    score, hits = 0, []
    for topic, kws in TOPICS.items():
        # 제목 등장은 2점, 본문은 등장 횟수만큼 1점 (지나가는 언급 1회는 걸러짐)
        t = sum(2 for k in kws if k in title) + sum(body.count(k) for k in kws)
        if t < MIN_SCORE:
            continue
        score += t
        if t:
            hits.append(topic)
    return score, hits


def shorten(sentence: str, limit: int = 70) -> str:
    sentence = sentence.strip().rstrip(".")
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",·:;") + "…"


def two_sentences(item: dict, topics: list[str]) -> str:
    """피드 요약을 압축해 두 문장으로 재구성한다 (원문을 길게 옮기지 않음)."""
    parts = [p for p in re.split(r"(?<=[.!?。])\s+|\s*[•·▪-]\s+", item["summary"]) if len(p.strip()) > 5]
    first = shorten(parts[0]) if parts else shorten(item["title"])
    if len(parts) > 1:
        second = shorten(parts[1])
    else:
        second = f"{', '.join(topics)} 관점에서 참고할 만한 소식"
    return f"{first}. {second}."


MODEL = "claude-opus-5-5"
LLM_PROMPT = """다음은 기술 뉴스 피드에서 고른 기사들의 제목과 피드 요약이다.
이 정보만 사용해서 한국어로 다이제스트를 만들어라.

- three_lines: 오늘 기사 전체를 아우르는 요약 문장 정확히 3개.
- summaries: 기사마다 하나씩, 입력 순서 그대로, 각각 정확히 두 문장.
- 원문 문장을 길게 그대로 옮기지 말고 자신의 말로 다시 써라.
- 피드에 없는 사실을 지어내지 마라.

다른 설명 없이 아래 형태의 JSON 객체 하나만 출력하라:
{{"three_lines": ["...", "...", "..."], "summaries": ["...", ...]}}

기사 목록:
{articles}"""


def llm_rewrite(selected: list[dict]) -> dict | None:
    """Claude API로 세 줄 요약과 기사별 두 문장 요약을 새로 쓴다.

    SDK가 없거나, 인증 정보가 없거나, 호출이 실패하면 None을 돌려주고
    호출한 쪽은 피드 텍스트를 줄이는 기본 방식으로 넘어간다.
    """
    try:
        import anthropic
    except ImportError:
        print("안내: anthropic 패키지가 없어 기본 요약을 사용합니다 (pip install anthropic).")
        return None

    articles = "\n\n".join(
        f"[{i}] 제목: {s['title']}\n피드 요약: {s['summary']}"
        for i, s in enumerate(selected, 1)
    )
    try:
        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": LLM_PROMPT.format(articles=articles)}],
        )
    except anthropic.AuthenticationError:
        print("안내: Claude API 인증 정보가 없어 기본 요약을 사용합니다 (ANTHROPIC_API_KEY 설정 필요).")
        return None
    except anthropic.APIStatusError as e:
        print(f"안내: Claude API 오류({e.status_code})로 기본 요약을 사용합니다.")
        return None
    except anthropic.APIConnectionError:
        print("안내: Claude API에 연결하지 못해 기본 요약을 사용합니다.")
        return None
    except Exception as e:  # 인증 정보 자체가 없을 때 등
        print(f"안내: Claude API를 쓸 수 없어 기본 요약을 사용합니다 ({type(e).__name__}).")
        return None

    if response.stop_reason != "end_turn":
        print(f"안내: Claude 응답이 완료되지 않아({response.stop_reason}) 기본 요약을 사용합니다.")
        return None
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    if (
        not isinstance(data, dict)
        or len(data.get("three_lines", [])) != 3
        or len(data.get("summaries", [])) != len(selected)
    ):
        print("안내: Claude 응답 형식이 맞지 않아 기본 요약을 사용합니다.")
        return None
    return data


def build(selected: list[dict], use_llm: bool = True) -> str:
    if not selected:
        return "해당 없음\n"
    today = date.today().isoformat()
    llm = llm_rewrite(selected) if use_llm else None
    lines = [f"# {today} 관심 기사 다이제스트", "", "## 오늘의 세 줄 요약", ""]
    if llm:
        three = [t.strip() for t in llm["three_lines"]]
    else:
        counts = {t: sum(1 for s in selected if t in s["topics"]) for t in TOPICS}
        topic_line = ", ".join(f"{t} {n}건" for t, n in counts.items() if n)
        three = [f"관심 주제 관련 글 {len(selected)}건 선정 ({topic_line})."]
        three += [f"주목: {s['title']}" for s in selected[:2]]
        while len(three) < 3:
            three.append("그 외 관련 글은 없음.")
    lines += [f"{i}. {t}" for i, t in enumerate(three, 1)]
    lines += ["", "## 기사별 요약", ""]
    for i, s in enumerate(selected):
        summary = llm["summaries"][i].strip() if llm else two_sentences(s, s["topics"])
        lines += [
            f"### {s['title']}",
            "",
            summary,
            "",
            f"- 원문: {s['link']}",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    items = parse(fetch(FEED_URL))
    scored = []
    for idx, it in enumerate(items):
        score, hits = match_topics(it)
        if score:
            scored.append((score, idx, {**it, "topics": hits}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = [s for _, _, s in scored[:MAX_ITEMS]]

    out_dir = BASE_DIR / "digest"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{date.today().isoformat()}.md"
    out.write_text(build(selected), encoding="utf-8")  # 같은 날짜 파일은 덮어씀
    print(f"저장: {out} / 선정 기사 {len(selected)}건 (피드 전체 {len(items)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
