"""Embeddings: nhúng các chunk (kết quả chunking.py) thành vector.

Đọc file JSON do chunking.py sinh ra (mặc định data/chunks/chunks.json —
danh sách chunk với trường "text" = prefix + nội dung), nhúng bằng
sentence-transformers rồi ghi ra 2 file:
- data/embeddings/vectors.npy    : mảng numpy float32 (n_chunks x dim)
- data/embeddings/embeddings.json: metadata các chunk (không chứa vector)

Thứ tự hàng trong vectors.npy khớp với thứ tự chunks trong embeddings.json
(chia sẻ mảng "chunk_ids" để đối chiếu chính xác).

Pipeline tổng thể:
    postprocess.py  -> data/processed/*.json        (content + metadata)
    chunking.py     -> data/chunks/chunks.json      (chunk theo Điều/gộp target)
    embeddings.py   -> data/embeddings/*.npy + .json (vector 384 chiều)

Chạy:
    python ingest/embeddings.py
    python ingest/embeddings.py --chunks-json data/chunks/chunks.json \
        --out-dir data/embeddings

Lưu ý: lần chạy đầu tiên sẽ tải model embedding (~80 MB) từ Hugging Face.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
DEFAULT_CHUNKS_JSON = ROOT / "data" / "chunks" / "chunks.json"
DEFAULT_OUT_DIR = ROOT / "data" / "embeddings"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_BATCH_SIZE = 64


def load_chunks(chunks_json: Path) -> list[dict]:
    """Đọc file chunks JSON của chunking.py, trả về danh sách chunk."""
    data = json.loads(chunks_json.read_text(encoding="utf-8"))
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("File chunks không có mảng 'chunks'.")
    return chunks


def encode_chunks(chunks: list[dict], model_name: str,
                  batch_size: int) -> np.ndarray:
    """Nhúng trường "text"; trả về mảng numpy (n_chunks x dim)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("[LỖI] Chưa cài sentence-transformers. "
              "Chạy: pip install sentence-transformers")
        sys.exit(1)

    texts = []
    valid = []
    for c in chunks:
        t = c.get("text")
        if not t or not t.strip():
            continue
        texts.append(t)
        valid.append(c)

    if not texts:
        print("[LỖI] Không có chunk nào có trường 'text' để nhúng.")
        sys.exit(1)

    print(f"  Nạp model: {model_name} ...")
    model = SentenceTransformer(model_name)
    print(f"  Nhúng {len(texts)} chunk ...")
    vectors = model.encode(
        texts, batch_size=batch_size, normalize_embeddings=True,
        show_progress_bar=True)
    return np.asarray(vectors, dtype=np.float32)


def save_embeddings(chunks: list[dict], vectors: np.ndarray, out_dir: Path,
                    model_name: str):
    """Ghi vectors ra .npy và metadata JSON (không chứa vector)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    npy_path = out_dir / "vectors.npy"
    np.save(npy_path, vectors)

    chunk_ids = [c["chunk_id"] for c in chunks] if chunks else []
    payload = {
        "model": model_name,
        "embedding_dim": int(vectors.shape[1]),
        "n_chunks": len(vectors),
        "chunk_ids": chunk_ids,
        "chunks": [{k: v for k, v in c.items() if k != "vector"} for c in chunks],
    }
    json_path = out_dir / "embeddings.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    return npy_path, json_path


def main():
    parser = argparse.ArgumentParser(
        description="Nhúng các chunk (từ chunking.py) thành vector 384 chiều."
    )
    parser.add_argument("--chunks-json", default=str(DEFAULT_CHUNKS_JSON),
                        help="File JSON chunks do chunking.py sinh ra.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="Thư mục ghi vectors.npy + embeddings.json.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Tên model embedding sentence-transformers.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Số chunk nhúng mỗi lô.")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    chunks_json = Path(args.chunks_json)
    if not chunks_json.is_file():
        print(f"[LỖI] Không tìm thấy file chunk: {chunks_json}")
        sys.exit(1)

    chunks = load_chunks(chunks_json)
    print(f"Đọc {len(chunks)} chunk từ {chunks_json}")

    vectors = encode_chunks(chunks, args.model, args.batch_size)

    npy_path, json_path = save_embeddings(chunks, vectors,
                                          Path(args.out_dir), args.model)
    print(f"Xong: {vectors.shape[0]} chunk x {vectors.shape[1]} chiều"
          f"\n  -> {npy_path}\n  -> {json_path}")


if __name__ == "__main__":
    main()