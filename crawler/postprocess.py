"""Post-process dữ liệu crawl thô -> file JSON gọn nhẹ cho mỗi văn bản.

Đọc payload RSC (raw_response.txt) trong data/raw/vbpl/<ten van ban>/ và ghi
ra data/processed/<ten van ban>.json với schema:

    {
      "content":  "<toàn văn văn bản dạng text thuần (đã bỏ thẻ HTML)>",
      "metadata": { ... các trường metadata lấy từ payload RSC + manifest.json ... }
    }

Chạy:
    python crawler/postprocess.py
    python crawler/postprocess.py --raw-dir data/raw/vbpl --out-dir data/processed

Ghi chú kỹ thuật:
- Cấu trúc RSC đã xác minh trên toàn bộ dữ liệu: payload có dạng nhiều frame,
  trong đó frame text "2:T<hex>," chứa toàn văn HTML (bắt đầu bằng <html> hoặc
  <body> tùy văn bản, kết thúc </html>/</body>) và frame "1:{...}" là metadata.
- KHÔNG cắt theo độ dài hex của frame: server đếm theo ký tự/byte khác với file
  lưu (file dùng CRLF) nên con số đó lệch; phải cắt theo marker <html>|<body>.
- Nguồn dữ liệu có thể bị mojibake (server gửi lệch encoding). Hàm
  _repair_mojibake() import từ crawler.py sẽ tự khôi phục; với text sạch thì
  không đổi gì nên gọi vô hại.
- Thư mục không có raw_response.txt (lần crawl trước FAIL, captured:false)
  được bỏ qua và đếm riêng.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "vbpl"
DEFAULT_OUT_DIR = ROOT / "data" / "processed"

# Nạp _repair_mojibake trực tiếp từ file crawler.py (không import package để
# tránh xung đột namespace vì thư mục "crawler" cũng tên là crawler).
def _load_repair():
    spec = importlib.util.spec_from_file_location(
        "crawler_module", ROOT / "crawler" / "crawler.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._repair_mojibake


_repair_mojibake = _load_repair()


def extract_document_html(text: str) -> str | None:
    """Lấy đoạn HTML toàn văn từ payload RSC.

    Tìm cặp mở/đóng theo marker: prefer <html>...</html>, fallback
    <body>...</body> (một số văn bản gửi dưới dạng fragment body-only).
    Trả None nếu không tìm thấy cả hai.

    Returns:
        Chuỗi HTML (đóng cả thẻ đóng), hoặc None.
    """
    html_start = text.find("<html>")
    html_end = text.find("</html>", html_start if html_start >= 0 else 0)
    if html_start >= 0 and html_end >= 0:
        return text[html_start:html_end + len("</html>")]

    body_start = text.find("<body>")
    body_end = text.find("</body>", body_start if body_start >= 0 else 0)
    if body_start >= 0 and body_end >= 0:
        return text[body_start:body_end + len("</body>")]

    return None


def parse_metadata(text: str) -> dict | None:
    """Parse frame metadata "1:{...}" (frame cuối của payload RSC).

    Hàm tìm occurrences CUỐI cùng của "1:{" rồi dùng json.JSONDecoder.raw_decode
    để đọc đúng một đối tượng JSON (bỏ qua phần dư phía sau như \r\n).

    Returns:
        Dict metadata nếu parse được, ngược lại None.
    """
    idx = text.rfind("1:{")
    if idx < 0:
        # Fallback: tìm frame "N:{" bất kỳ gần cuối (phòng thay đổi id frame).
        for m in re.finditer(r"\b\d+:\{", text):
            idx = m.start() + len(re.match(r"\d+", text[m.start():]).group(0)) + 1
    if idx < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[idx + 2:])
    except (ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def html_to_text(html: str) -> str:
    """Chuyển HTML toàn văn -> text thuần giữ cấu trúc dòng.

    - Bỏ thẻ script/style/head.
    - <br> -> xuống dòng; mỗi khối <p>/<div>/<tr>/<li>/h1..h6 thêm xuống dòng
      sau khiến các đoạn văn bản tách dòng riêng.
    - Gộp khoảng trắng, bỏ dòng rỗng, chuyển &nbsp; (\xa0) thành dấu cách.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p",
                              "div", "li", "tr"]):
        tag.insert_after("\n")

    lines = []
    for raw in soup.get_text("\n").split("\n"):
        line = re.sub(r"[ \t\x0b\x0c]+", " ", raw).replace("\u00a0", " ").strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def build_metadata(rsc: dict, manifest: dict | None) -> dict:
    """Map metadata từ object RSC + manifest.json thành dict gọn."""
    meta: dict = {}

    if rsc.get("id") is not None:
        meta["doc_id"] = str(rsc["id"])
    if rsc.get("docNum"):
        meta["doc_num"] = rsc["docNum"]
    if rsc.get("title"):
        meta["title"] = rsc["title"]

    dt = rsc.get("docType") or {}
    if dt.get("name"):
        meta["doc_type"] = {"name": dt.get("name"), "code": dt.get("code")}
    if rsc.get("docGroup"):
        meta["doc_group"] = rsc["docGroup"]

    for out_key, rsc_key in (
        ("issue_date", "issueDate"),
        ("effective_from", "effFrom"),
        ("effective_to", "effTo"),
        ("publication_date", "publicDate"),
    ):
        if rsc.get(rsc_key):
            meta[out_key] = rsc[rsc_key]

    es = rsc.get("effStatus") or {}
    if es.get("name"):
        meta["eff_status"] = {"name": es.get("name"), "code": es.get("code")}
    if rsc.get("status"):
        meta["status"] = rsc["status"]
    if rsc.get("lang"):
        meta["lang"] = rsc["lang"]
    if rsc.get("agencyName"):
        meta["agency"] = rsc["agencyName"]

    org = rsc.get("organization") or {}
    if org.get("name"):
        meta["organization"] = {
            "name": org.get("name"),
            "code": org.get("code"),
            "org_type": org.get("orgType"),
        }

    signers = []
    for s in (rsc.get("documentIssues") or []):
        entry = {}
        if s.get("personName"):
            entry["person_name"] = s["personName"]
        if s.get("jobTitleName"):
            entry["job_title"] = s["jobTitleName"]
        if s.get("jobTitleCode"):
            entry["job_title_code"] = s["jobTitleCode"]
        if s.get("agencyName"):
            entry["agency"] = s["agencyName"]
        if s.get("orderIndex") is not None:
            entry["order_index"] = s["orderIndex"]
        if entry:
            signers.append(entry)
    if signers:
        meta["signers"] = signers

    majors = [m.get("name") for m in (rsc.get("documentMajors") or []) if m.get("name")]
    if majors:
        meta["majors"] = majors
    fields = [f.get("name") for f in (rsc.get("documentFields") or []) if f.get("name")]
    if fields:
        meta["fields"] = fields

    if rsc.get("documentContentFileName") or rsc.get("documentContentFileDocName"):
        meta["files"] = {
            "original_pdf": rsc.get("documentContentFileName"),
            "doc_source": rsc.get("documentContentFileDocName"),
        }
    if rsc.get("documentContentEn"):
        meta["has_translation"] = True

    related = []
    for r in (rsc.get("documentRelatedList") or []):
        entry = {}
        if r.get("relatedType"):
            entry["related_type"] = r["relatedType"]
        if r.get("fileTitle"):
            entry["title"] = r["fileTitle"]
        if r.get("fileName"):
            entry["file_name"] = r["fileName"]
        if entry:
            related.append(entry)
    if related:
        meta["related"] = related

    review = {}
    for out_key, rsc_key in (
        ("review_status", "reviewStatus"),
        ("view_count", "viewCount"),
        ("has_content", "hasContent"),
        ("has_original_pdf", "hasOriginalPdf"),
    ):
        if rsc.get(rsc_key) is not None:
            review[out_key] = rsc[rsc_key]
    if review:
        meta["review"] = review

    # Thông tin nguồn crawl từ manifest.json (nếu có).
    source = {}
    if manifest:
        for key in ("id", "doc_num", "title", "source_url", "crawled_at",
                    "content_hash", "http_status", "captured"):
            if manifest.get(key) is not None:
                source[key] = manifest[key]
    if source:
        meta["source"] = source

    return meta


def process_folder(doc_dir: Path, out_dir: Path):
    """Xử lý 1 thư mục văn bản; trả về dict {"status", "path"}."""
    raw_path = doc_dir / "raw_response.txt"
    if not raw_path.exists():
        return {"status": "skip", "path": None}

    manifest = None
    manifest_path = doc_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = None

    text = raw_path.read_text(encoding="utf-8", errors="replace")
    text = _repair_mojibake(text)

    html = extract_document_html(text)
    if html is None:
        return {"status": "fail", "path": None}

    rsc = parse_metadata(text)
    if rsc is None:
        return {"status": "fail", "path": None}

    result = {
        "content": html_to_text(html),
        "metadata": build_metadata(rsc, manifest),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (doc_dir.name + ".json")
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"status": "ok", "path": out_path}


def main():
    parser = argparse.ArgumentParser(
        description="Post-process raw RSC payload -> JSON (content + metadata)."
    )
    parser.add_argument(
        "--raw-dir", default=str(DEFAULT_RAW_DIR),
        help="Thư mục chứa các thư mục văn bản thô (mặc định data/raw/vbpl).",
    )
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR),
        help="Thư mục ghi file .json đầu ra (mặc định data/processed).",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)

    if not raw_dir.is_dir():
        print(f"[LỖI] Không tìm thấy thư mục: {raw_dir}")
        sys.exit(1)

    counts = {"ok": 0, "skip": 0, "fail": 0}
    for doc_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        res = process_folder(doc_dir, out_dir)
        counts[res["status"]] += 1
        if res["status"] == "ok":
            print(f"  [OK]   {res['path'].name}")
        elif res["status"] == "skip":
            print(f"  [SKIP] {doc_dir.name[:70]} ... (không có raw_response.txt)")
        else:
            print(f"  [LỖI]  {doc_dir.name[:70]} (không trích được content/metadata)")

    print(f"\nXong: {counts['ok']} OK, {counts['skip']} bỏ qua, "
          f"{counts['fail']} lỗi.")
    print(f"Đầu ra: {out_dir}")


if __name__ == "__main__":
    main()