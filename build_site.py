"""GitHub Pages용 정적 사이트를 site/ 폴더에 만든다.

    python build_site.py

- site/index.html          web/index.html 복사본
- site/digest/*.md         digest 폴더의 YYYY-MM-DD.md 파일
- site/digest/index.json   날짜 목록 (최신순) — 로컬 서버의 /api/list 역할
"""
import json
import re
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "site"
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "digest").mkdir(parents=True)
    shutil.copy2(BASE / "web" / "index.html", SITE / "index.html")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    files = []
    src = BASE / "digest"
    for f in sorted(src.glob("*.md"), reverse=True) if src.is_dir() else []:
        if NAME_RE.match(f.name):
            shutil.copy2(f, SITE / "digest" / f.name)
            files.append({"name": f.name, "size": f.stat().st_size})
    (SITE / "digest" / "index.json").write_text(
        json.dumps(files, ensure_ascii=False), encoding="utf-8"
    )
    print(f"site/ 생성 완료: 다이제스트 {len(files)}개")


if __name__ == "__main__":
    main()
