"""Ingest: đẩy vectors + chunks lên Qdrant bằng langchain-qdrant.

Đọc 2 file do embeddings.py sinh ra:
    data/embeddings/vectors.npy      (float32, n_chunks x dim)
    data/embeddings/embeddings.json  (metadata các chunk, sẵn "text")

rồi đẩy lên collection Qdrant. Mặc định tận dụng vector đã tính sẵn
(--reuse-vectors): embedder là một lớp langchain_core Embeddings tra cứu
vector theo đúng chuỗi "text" đã nhúng, đảm bảo vector trong DB khớp chính
xác với embeddings.npy — không phải tính lại model.

Muốn tính lại từ đầu (không cần .npy, chỉ cần embeddings.json), bỏ
--reuse: khi đó dùng SentenceTransformer encode trực tiếp toàn bộ text.

Chạy (yêu cầu Qdrant đã bật, VD: docker compose up -d):
    python ingest/ingest.py                                  # local :6333
    python ingest/ingest.py --collection vpl --recreate      # ghi đè collection
    python ingest/ingest.py --url https://xxx.qdrant.io \
        --api-key <key> --collection vpl --recreate

Mặc định collection phải "fresh": nếu đã tồn tại cần kèm --recreate.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from langchain_core.embeddings import Embeddings

ROOT = Path(__file__).parent.parent
DEFAULT_VECTORS = ROOT / "data" / "embeddings" / "vectors.npy"
DEFAULT_EMBEDDINGS_JSON = ROOT / "data" / "embeddings" / "embeddings.json"
DEFAULT_COLLECTION = "vpl_chunks"
DEFAULT_BATCH_SIZE = 64


class StoredVectorsEmbeddings(Embeddings):
    """langchain Embeddings dùng vector đã tính sẵn (tra theo chuỗi text)."""

    def __init__(self, text_to_vector: dict[str, list[float]]):
        super().__init__()
        self._map = text_to_vector

    def embed_documents(self, texts):
        return [self._lookup(t) for t in texts]

    def embed_query(self, text):
        return self._lookup(text)

    def _lookup(self, text):
        try:
            return self._map[text]
        except KeyError:
            raise KeyError(
                f"Không có vector cho text {text[:60]!r} — "
                "chạy embeddings.py lại hoặc bỏ --reuse-vectors.") from None


class HFFastEmbeddings(Embeddings):
    """langchain Embeddings tính vector theo model (fallback khi không dùng .npy)."""

    def __init__(self, model_name: str, batch_size: int):
        super().__init__()
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._batch_size = batch_size

    def embed_documents(self, texts):
        return [self._vec(t) for t in self._encode(texts, batch_size=len(texts) or 1)]

    def embed_query(self, text):
        return [self._vec(v) for v in self._encode([text])][0]

    def _encode(self, texts, batch_size=None):
        return self._model.encode(
            texts, batch_size=batch_size or self._batch_size,
            normalize_embeddings=True)

    @staticmethod
    def _vec(v):
        return [round(float(x), 6) for x in v]


def load_data(vectors_path: Path, meta_path: Path):
    """Trả về (documents, text_to_vector | None, dim | None)."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    chunks = meta.get("chunks") or []
    if not chunks:
        raise ValueError(f"Không có mảng 'chunks' trong {meta_path}")

    texts = [c.get("text", "") or "" for c in chunks]
    non_empty = sum(1 for t in texts if t.strip())
    if non_empty != len(chunks):
        print(f"  [CẢNH BÁO] {len(chunks) - non_empty} chunk không có 'text'.")

    arr = None
    if vectors_path.is_file():
        arr = np.load(vectors_path)
        if arr.ndim != 2 or arr.shape[0] != len(chunks):
            raise ValueError(
                f"vectors.npy {arr.shape} không khớp {len(chunks)} chunk "
                f"trong embeddings.json.")
        print(f"  Dùng vector sẵn có: {arr.shape[0]} x {arr.shape[1]} (float32)")

    text_to_vector = None
    dim = None
    if arr is not None:
        text_to_vector = {t: [float(x) for x in arr[i]] for i, t in enumerate(texts)}
        dim = int(arr.shape[1])

    docs = []
    from langchain_core.documents import Document
    for c in chunks:
        metadata = {k: v for k, v in c.items() if k != "text"}
        docs.append(Document(page_content=c.get("text", ""), metadata=metadata))
    return docs, text_to_vector, dim


def ensure_recreated(client, collection: str, dim: int):
    from qdrant_client.models import Distance, VectorParams
    if collection_exists(client, collection):
        client.delete_collection(collection)
        print(f"  Xóa collection cũ '{collection}'")
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    print(f"  Tạo collection '{collection}' ({dim} chiều, COSINE)")


def main():
    parser = argparse.ArgumentParser(
        description="Đẩy chunks + vectors lên Qdrant bằng langchain-qdrant."
    )
    parser.add_argument("--vectors", default=str(DEFAULT_VECTORS),
                        help="File vectors.npy (tùy chọn nếu có --reuse).")
    parser.add_argument("--meta", default=str(DEFAULT_EMBEDDINGS_JSON),
                        help="File embeddings.json chứa metadata chunks.")
    parser.add_argument("--url", default="http://localhost:6333",
                        help="Địa chỉ Qdrant REST.")
    parser.add_argument("--api-key", default=None, help="API key Qdrant (nếu có).")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help="Tên collection đích.")
    parser.add_argument("--recreate", action="store_true",
                        help="Xóa và tạo mới collection trước khi đẩy.")
    parser.add_argument("--reuse-vectors", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Dùng vector từ file .npy thay vì tính lại = model.")
    parser.add_argument("--model", default="paraphrase-multilingual-MiniLM-L12-v2",
                        help="Model khi --no-reuse-vectors.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Số điểm upsert mỗi lô.")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    meta_path = Path(args.meta)
    if not meta_path.is_file():
        print(f"[LỖI] Không tìm thấy {meta_path} (chạy ingest/embeddings.py trước).")
        sys.exit(1)
    vectors_path = Path(args.vectors)

    docs, text_to_vector, dim = load_data(vectors_path, meta_path)
    print(f"Đọc {len(docs)} document từ {meta_path}")

    from qdrant_client import QdrantClient

    client = QdrantClient(url=args.url, api_key=args.api_key, timeout=60)
    try:
        client.get_collections()
        print(f"  Kết nối Qdrant OK: {args.url}")
    except Exception as e:
        print(f"[LỖI] Không kết nối được Qdrant {args.url}: {e}")
        print("  Kiểm tra: docker compose up -d (xem docker-compose.yml)")
        sys.exit(1)

    from langchain_qdrant import QdrantVectorStore
    from qdrant_client.models import Distance

    if args.reuse_vectors:
        if text_to_vector is None:
            print("[LỖI] Không tìm thấy vectors.npy để reuse. Bỏ --reuse hoặc "
                  f"chạy embeddings.py tạo {DEFAULT_VECTORS}.")
            sys.exit(1)
        embedder = StoredVectorsEmbeddings(text_to_vector)
        if args.recreate or not collection_exists(client, args.collection):
            ensure_recreated(client, args.collection, dim)
        store = QdrantVectorStore(
            client=client, collection_name=args.collection,
            embedding=embedder,
            distance=Distance.COSINE,
            validate_collection_config=False)
        for i in range(0, len(docs), args.batch_size):
            store.add_documents(docs[i:i + args.batch_size])
            print(f"  Đã upsert {min(i + args.batch_size, len(docs))}/{len(docs)}")
    else:
        embedder = HFFastEmbeddings(args.model, args.batch_size)
        store = QdrantVectorStore.from_documents(
            documents=docs,
            embedding=embedder,
            collection_name=args.collection,
            url=args.url,
            api_key=args.api_key,
            distance=Distance.COSINE,
            timeout=60,
        )
        print(f"  from_documents đã tạo/upsert vào '{args.collection}'")

    count = client.count(args.collection, exact=True).count
    print(f"Hoàn tất: {count} điểm trong collection '{args.collection}' "
          f"tại {args.url}")


def collection_exists(client, collection: str) -> bool:
    try:
        for c in client.get_collections().collections:
            if c.name == collection:
                return True
    except Exception:
        pass
    return False


if __name__ == "__main__":
    main()