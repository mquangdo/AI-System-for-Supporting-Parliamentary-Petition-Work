"""Chunking: chia toàn văn văn bản pháp luật thành các chunk sẵn sàng nhúng.

Chiến lược "target-size chunking" (xem ingest/chunking_plan.md):
- Đơn vị cơ bản = Điều (hoặc khối preamble / khối theo Chương khi văn bản
  không có Điều).
- Gộp các khối ngắn liền nhau thành 1 chunk tới khi đạt ngưỡng
  target_tokens (mặc định 350 token ≈ 1.200 ký tự), tránh tạo vector lãng phí
  cho các Điều 57-300 ký tự.
- KHÔNG cắt ngang Điều: chỉ những Điều vượt ~1.5x ngưỡng mới chia theo Khoản.
- Tôn trọng biên Chương/Mục: đổi Chương/Mục -> flush chunk (giữ path ngữ cảnh).
- Preamble (Căn cứ..., Hà Nội, ngày...) gộp vào chunk đầu tiên nếu ngắn.

Module thuần chức năng chia chunk (không nhúng embedding); embeddings.py sẽ
gọi hàm chunk_content() của module này.

Chạy:
    python ingest/chunking.py
    python ingest/chunking.py --json-dir data/processed --out data/embeddings/chunks.json
    python ingest/chunking.py --target-tokens 350 --max-tokens 512
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_JSON_DIR = ROOT / "data" / "processed"
DEFAULT_OUT_PATH = ROOT / "data" / "chunks" / "chunks.json"
DEFAULT_MAX_TOKENS = 512
DEFAULT_TARGET_TOKENS = 350

RE_CHAPTER = re.compile(r"^\s*Chương\s+[ivxlcdm0-9]+\b", re.IGNORECASE)
RE_SECTION = re.compile(r"^\s*Mục\s+[ivxlcdm0-9]+\b", re.IGNORECASE)
RE_ARTICLE = re.compile(r"^\s*Điều\s+(\d+[a-z]?)\.?", re.IGNORECASE)
RE_CLAUSE = re.compile(r"^\s*\d+\.\s")


def estimate_tokens(text: str) -> int:
    """Ước lượng số token tiếng Việt (≈ 3.5 ký tự / token)."""
    return max(1, int(len(text) / 3.5))


def build_prefix(meta: dict, path: str) -> str:
    """Prefix ngữ cảnh từ metadata + path, prepend trước nội dung chunk."""
    parts = []
    doc_num = meta.get("doc_num")
    title = meta.get("title")
    if title:
        parts.append(f"[{doc_num or ''}] {title}".strip())
    doc_type = (meta.get("doc_type") or {}).get("name")
    if not doc_type:
        doc_type = meta.get("doc_group")
    if doc_type:
        parts.append(doc_type)
    if meta.get("agency"):
        parts.append(str(meta["agency"]))
    if meta.get("issue_date"):
        parts.append(str(meta["issue_date"]))
    text = " — ".join(parts)
    if path:
        text = f"{text} | {path}" if text else f"[{path}]"
    return text


def atom_size(atom: dict) -> int:
    return sum(len(l) + 1 for l in atom["lines"])


class _Parser:
    """Quét nội dung theo dòng, dựng các khối (atom) theo cấu trúc văn bản."""

    def __init__(self):
        self.atoms: list[dict] = []
        self.buf: list[str] = []
        self.ch_idx = 0
        self.ch_label: str | None = None
        self.sec_label: str | None = None
        self.art_num: str | None = None
        self.art_label: str | None = None
        self.anchored = False
        self.kind = "preamble"

    def _flush(self, final: bool = False):
        if not self.buf:
            return
        self.atoms.append({
            "lines": self.buf,
            "kind": self.kind,
            "ch_idx": self.ch_idx,
            "ch_label": self.ch_label,
            "sec_label": self.sec_label,
            "art_num": self.art_num,
            "art_label": self.art_label,
        })
        self.buf = []

    def feed(self, lines: list[str]):
        for line in lines:
            if RE_CHAPTER.match(line):
                self._flush()
                self.ch_idx += 1
                self.ch_label = line.strip()
                self.sec_label = None
                self.art_num, self.art_label = None, None
                self.anchored = True
                self.kind = "whole"
                self.buf.append(line)
            elif RE_SECTION.match(line):
                self._flush()
                self.sec_label = line.strip()
                self.art_num, self.art_label = None, None
                if not self.anchored:
                    self.anchored = True
                    self.kind = "whole"
                self.buf.append(line)
            elif RE_ARTICLE.match(line):
                self._flush()
                m = RE_ARTICLE.match(line)
                self.art_num = m.group(1)
                self.art_label = line.strip()
                self.anchored = True
                self.kind = "article"
                self.buf.append(line)
            else:
                if not self.buf:
                    if not self.anchored:
                        self.kind = "preamble"
                    self.buf.append(line)
                else:
                    self.buf.append(line)
        self._flush()

    def _article_path(self, art_label: str | None,
                      ch_label: str | None, sec_label: str | None) -> str:
        return " → ".join(p for p in (ch_label, sec_label, art_label) if p)

    def finalize(self, target_chars: int, max_chars: int) -> list[dict]:
        """Chia nhỏ các Điều quá lớn theo Khoản; trả về danh sách atom."""
        out: list[dict] = []
        for at in self.atoms:
            if at["kind"] != "article":
                out.append(at)
                continue
            size = atom_size(at)
            if size <= target_chars * 1.5:
                out.append(at)
                continue
            header, rest = at["lines"][0], at["lines"][1:]
            base_path = self._article_path(at["art_label"], at["ch_label"],
                                           at["sec_label"])
            groups: list[list[str]] = []
            cur: list[str] = []
            for ln in rest:
                if RE_CLAUSE.match(ln):
                    if cur:
                        groups.append(cur)
                    cur = [ln]
                else:
                    cur.append(ln)
            if cur:
                groups.append(cur)

            if not groups or (groups == [rest] if rest else False):
                segments = self._pack(rest, target_chars) if rest else [[]]
                if not segments and not rest:
                    segments = [[]]
                for seg in segments:
                    sub = self._atom_slice(at, header, seg)
                    sub["path"] = base_path
                    out.append(sub)
                continue

            for g in groups:
                m = re.match(r"^\s*(\d+)\.", g[0])
                gpath = f"{base_path} → Khoản {m.group(1)}" if m else base_path
                if atom_size({"lines": [header] + g}) <= max_chars:
                    sub = self._atom_slice(at, header, g)
                    sub["path"] = gpath
                    out.append(sub)
                else:
                    for seg in self._pack([header] + g, max_chars):
                        sub = self._atom_slice(at, None, seg)
                        sub["path"] = gpath
                        out.append(sub)
        return out

    @staticmethod
    def _atom_slice(at: dict, header: str | None, rest: list[str]) -> dict:
        lines = ([header] + rest) if header else rest
        return {
            "lines": lines,
            "kind": "clause" if at["kind"] == "article" else at["kind"],
            "ch_idx": at["ch_idx"],
            "ch_label": at["ch_label"],
            "sec_label": at["sec_label"],
            "art_num": at["art_num"],
            "art_label": at["art_label"],
            "path": None,
        }

    @staticmethod
    def _pack(lines: list[str], budget_chars: int) -> list[list[str]]:
        segs: list[list[str]] = []
        cur: list[str] = []
        cur_chars = 0
        for ln in lines:
            sz = len(ln)
            if cur and cur_chars + sz > budget_chars:
                segs.append(cur)
                cur = []
                cur_chars = 0
            cur.append(ln)
            cur_chars += sz
        if cur:
            segs.append(cur)
        return segs


def chunk_content(content: str, meta: dict, max_tokens: int,
                  target_tokens: int) -> list[dict]:
    """Chia toàn văn 1 văn bản thành các chunk (không kèm embedding).

    Returns:
        Danh sách chunk dict: path, level, chapter_index, articles,
        article_range, content, text (prefix+content), token_estimate.
    """
    lines = [ln for ln in content.split("\n") if ln.strip()]
    target_chars = int(target_tokens * 3.5)
    max_chars = int(max_tokens * 3.5)

    parser = _Parser()
    parser.feed(lines)
    atoms = parser.finalize(target_chars, max_chars)

    chunks: list[dict] = []
    cur: list[dict] = []
    cur_chars = 0

    def flush():
        nonlocal cur, cur_chars
        if not cur:
            return
        chunks.append(_assemble(cur, meta))
        cur = []
        cur_chars = 0

    for at in atoms:
        sz = atom_size(at)
        if cur:
            first = cur[0]
            region_change = (
                first["kind"] != "preamble"
                and first["ch_label"] is not None
                and (first["ch_label"], first["sec_label"])
                != (at["ch_label"], at["sec_label"])
            )
            if region_change or cur_chars + sz > target_chars:
                flush()
        cur.append(at)
        cur_chars += sz
    flush()

    return chunks


def _assemble(group: list[dict], meta: dict) -> dict:
    content = "\n".join(l for at in group for l in at["lines"])

    nums = [at["art_num"] for at in group if at["art_num"]]
    art_range = ""
    if nums:
        numeric = [int(re.match(r"\d+", n).group()) for n in nums]
        if len(set(numeric)) == 1:
            art_range = str(nums[0])
        else:
            art_range = f"{min(numeric)}–{max(numeric)}"

    if len(group) == 1:
        at = group[0]
        path = at.get("path") or " → ".join(
            p for p in (at["ch_label"], at["sec_label"], at["art_label"])
            if p)
        if at["kind"] == "preamble" and not at["ch_label"]:
            path = "Mở đầu"
        level = at["kind"]
        ch_idx = at["ch_idx"]
    else:
        first = group[0]
        region = " → ".join(
            p for p in (first.get("ch_label"), first.get("sec_label")) if p)
        path = f"{region} → Điều {art_range}" if art_range else region
        if first["kind"] == "preamble" and not first["ch_label"]:
            path = f"Mở đầu; {path}" if path else "Mở đầu"
        level = "article-group"
        ch_idx = first["ch_idx"]

    prefix = build_prefix(meta, path)
    text = f"{prefix}\n{content}" if prefix else content
    return {
        "path": path or "Mở đầu",
        "level": level,
        "chapter_index": ch_idx,
        "articles": len(set(nums)),
        "article_range": art_range,
        "content": content,
        "text": text,
        "token_estimate": estimate_tokens(text),
    }


def load_json_files(json_dir: Path) -> list[dict]:
    docs = []
    for f in sorted(json_dir.glob("*.json")):
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  [LỖI] {f.name}: {e}")
    return docs


def main():
    parser = argparse.ArgumentParser(
        description="Chia chunk content trong data/processed theo Điều/gộp "
                    "tới ngưỡng target (không nhúng embedding).")
    parser.add_argument("--json-dir", default=str(DEFAULT_JSON_DIR),
                        help="Thư mục chứa file JSON đầu ra postprocess.")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH),
                        help="File JSON đầu ra danh sách chunk (chưa có vector).")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help="Ngưỡng token cứng tối đa của 1 chunk (cap model).")
    parser.add_argument("--target-tokens", type=int, default=DEFAULT_TARGET_TOKENS,
                        help="Ngưỡng target gộp (token) — càng cao chunk càng ít.")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    json_dir = Path(args.json_dir)
    if not json_dir.is_dir():
        print(f"[LỖI] Không tìm thấy thư mục: {json_dir}")
        sys.exit(1)

    docs = load_json_files(json_dir)
    print(f"Đọc {len(docs)} file JSON từ {json_dir}")

    all_chunks = []
    sizes = []
    skipped = 0
    for d in docs:
        content = d.get("content")
        if not content or not content.strip():
            skipped += 1
            continue
        meta = d.get("metadata") or {}
        doc_id = str(meta.get("doc_id", "")) or d.get("doc_id", "")
        chunks = chunk_content(content, meta, args.max_tokens,
                               args.target_tokens)
        for i, c in enumerate(chunks):
            c["doc_id"] = doc_id
            c["doc_num"] = meta.get("doc_num", "")
            c["title"] = meta.get("title", "")
            c["chunk_id"] = f"{doc_id}-{i:03d}"
            sizes.append(c["token_estimate"])
            all_chunks.append(c)

    if not all_chunks:
        print("Không có chunk nào được tạo.")
        sys.exit(1)

    avg = sum(sizes) / len(sizes)
    print(f"Chia được {len(all_chunks)} chunk từ "
          f"{len(docs) - skipped} văn bản (bỏ {skipped} không có content).")
    print(f"Token/chunk: min={min(sizes)} trung bình={avg:.0f} max={max(sizes)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_tokens": args.target_tokens,
        "max_tokens": args.max_tokens,
        "n_chunks": len(all_chunks),
        "chunks": all_chunks,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"Xong: -> {out_path}")


if __name__ == "__main__":
    main()