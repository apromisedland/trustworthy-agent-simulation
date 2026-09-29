import json
import sys
from pathlib import Path

from pdf2image import convert_from_path
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
RENDER = ROOT / "render"
POPPLER = Path("C:/Users/28082/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pages = convert_from_path(str(RENDER / "report.pdf"), dpi=135, poppler_path=str(POPPLER))
    for page_number, page in enumerate(pages, start=1):
        page.save(RENDER / f"page-{page_number}.png")
    reader = PdfReader(RENDER / "report.pdf")
    audit = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        audit.append({"page": page_number, "characters": len(text), "start": text[:85], "end": text[-85:]})
    (RENDER / "page_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    print("Rendered PNG pages:", len(pages))


if __name__ == "__main__":
    main()
