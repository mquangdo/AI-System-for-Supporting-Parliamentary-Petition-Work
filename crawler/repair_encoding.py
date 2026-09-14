"""Sửa mojibake encoding cho dữ liệu crawl đã lưu tại chỗ (không cần mạng).

Chạy:  python repair_encoding.py

Quét {ROOT}/data/raw/vbpl/*  và với mỗi thư mục có raw_response.txt:
  - Đọc file, decode UTF-8, áp dụng _repair_mojibake() (đúng thuật toán
    crawler.py dùng trong capture_rsc).
  - Nếu nội dung bị thay đổi (tức trước đó bị rối) thì ghi lại file sạch
    và cập nhật manifest.json: content_hash, raw_chars, encoding_repaired.
Làm tương tự cho luoc_do_raw.txt (entry "luoc_do_full_captured" giữ nguyên).

Dùng chung hàm sửa lỗi với crawler.py nên kết quả luôn khớp với lần crawl sau.
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "crawler"))
from crawler import _repair_mojibake  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "vbpl"


def clean_file(path: Path) -> bool:
    """Sửa encoding cho 1 file tại chỗ; trả True nếu file đã bị thay đổi."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    fixed = _repair_mojibake(text)
    if fixed == text:
        return False
    path.write_text(fixed, encoding="utf-8")
    return True


def main():
    n_raw = n_luoc = n_man = 0
    dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir()) if RAW_DIR.is_dir() else []
    for d in dirs:
        manifest_path = d / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        raw_f = d / "raw_response.txt"
        if raw_f.exists() and clean_file(raw_f):
            n_raw += 1
            if manifest:
                new_text = raw_f.read_text(encoding="utf-8")
                manifest["content_hash"] = (
                    "sha256:" + hashlib.sha256(new_text.encode("utf-8")).hexdigest()
                )
                manifest["raw_chars"] = len(new_text)
                manifest["encoding_repaired"] = True

        luoc_f = d / "luoc_do_raw.txt"
        if luoc_f.exists() and clean_file(luoc_f):
            n_luoc += 1

        if manifest and manifest_path.exists():
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            n_man += 1

    print(f"Đã sửa: {n_raw} raw_response.txt, {n_luoc} luoc_do_raw.txt; "
          f"cập nhật {n_man} manifest.json.")
    print("Xong.")


if __name__ == "__main__":
    main()