import argparse
import concurrent.futures
import json
import re
import sys
import urllib.request
from pathlib import Path

from lxml import html


ROOT = Path(__file__).resolve().parent


def fetch_source(spec):
    source_id, url = spec.split("=", 1)
    output = ROOT / "sources"
    output.mkdir(exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ResearchReview/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            content = response.read()
            final_url = response.url
        tree = html.fromstring(content)
        for element in tree.xpath("//script|//style|//nav|//footer"):
            element.drop_tree()
        text_content = re.sub(r"[ \t]+", " ", tree.text_content())
        text_content = re.sub(r"\n\s*\n", "\n\n", text_content).strip()
        metadata = {"id": source_id, "url": url, "final_url": final_url,
                    "title": tree.xpath("string(//title)"), "accessed": "2026-09-28",
                    "citation_meta": tree.xpath("//meta[starts-with(@name,'citation_')]/@content")}
        (output / f"{source_id}.html").write_bytes(content)
        (output / f"{source_id}.txt").write_text(text_content, encoding="utf-8")
        (output / f"{source_id}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        abstracts = tree.xpath("//*[contains(concat(' ',normalize-space(@class),' '),' abstract ')]")
        abstract = re.sub(r"\s+", " ", abstracts[0].text_content()).strip() if abstracts else text_content[:3500]
        return {**metadata, "abstract": abstract}
    except Exception as error:
        return {"id": source_id, "url": url, "error": str(error)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+")
    arguments = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(fetch_source, arguments.sources):
            result.pop("citation_meta", None)
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
