# Hệ thống QA Hỗ trợ Công tác Giám sát Kiến nghị

AI agentic RAG trả lời câu hỏi về **văn bản pháp luật Việt Nam** (luật, nghị định, thông tư, quyết định…) với **trích dẫn số hiệu văn bản / điều / khoản**, phục vụ nghiệp vụ Thanh tra / giám sát kiến nghị.

## Tính năng

- **Agentic RAG** theo pattern TimeNet — 1 workflow duy nhất, 3 node:
  `orchestrator` (chỉ quyết định hướng) → `retrieve` (tra cứu) → `summarize` (tổng hợp).
- **Multi-turn** dựa trên cơ chế built-in của LangGraph (`add_messages` + checkpointer `MemorySaver` theo `thread_id`).
- **Tool-calling với allowlist per-node** — mỗi node chỉ dùng đúng tools được khai báo.
- Truy vấn **Qdrant** (vector 384-d, MiniLM multilingual) kèm filter số hiệu văn bản (`doc_ref`), dedup theo `chunk_id`.
- Từ chối trả lời khi thiếu cơ sở pháp lý (không bịa văn bản).

## Kiến trúc tổng quan

```
agents/
  config.py        # Settings + registry per-provider LLM từ .env
  llm.py           # get_llm() dispatcher (groq / nvidia)
  embeddings.py    # get_embeddings() -> HuggingFaceEmbeddings (cache 1 lần)
  prompts.py       # ORCHESTRATOR_PROMPT + SUMMARY_PROMPT + QUERY_REWRITER_PROMPT
  state.py         # LegalQAState (Pydantic) + Analysis
  utils.py         # hạ tầng + pipeline tra cứu (rewrite, retrieve, cache LLM/Qdrant)
  tools.py         # TOOL thật + registry TOOLS + get_tools() allowlist
  workflow.py      # graph 3 node + run_workflow() + CLI `python -m agents.workflow`
  visualize.py     # in sơ đồ Mermaid/ASCII + lưu docs/graphs
```

```
START ──▶ orchestrator_node ──(action=search)──▶ retrieve_node ──▶ summarize_node
             ▲                                        │                   │
             └────────────────────────────────────────┘                   │
             └──(action=answer)───────────────────────────────────────────▶ END
```

Chi tiết: `docs/agents/main_agent_rag.md` | Thiết kế hệ thống dài hạn: `docs/system/DESIGN.md`.

## Cài đặt

Yêu cầu: **Python ≥ 3.12**, [uv](https://docs.astral.sh/uv/) (khuyên dùng) hoặc pip, **Docker** (cho Qdrant).

```bash
# 1. Clone + cài phụ thuộc
uv sync                                  # hoặc: pip install -e .

# 2. Sao chép cấu hình và điền key
cp .env.example .env
#   - LLM_PROVIDER=groq (hoặc nvidia)
#   - điền GROQ_API_KEY + GROQ_MODEL  (hoặc NVIDIA_API_KEY + NVIDIA_MODEL)

# 3. Khởi động Qdrant
docker compose up -d
```

## Chuẩn bị dữ liệu

1. **Crawl văn bản pháp luật** → `data/raw` (tham khảo `test/crawler.py`, `docs/crawler/postprocess.md`).
2. **Ingest** → tạo collection `vpl_chunks` trong Qdrant với embedding **MiniLM 384-d, COSINE** (phải khớp `EMBEDDING_MODEL` trong `.env`).

Đã có sẵn collection `vpl_chunks` (~1104 điểm) và dữ liệu xử lý trong `data/`, `qdrant_data/` (đều nằm trong `.gitignore`).

## Chạy

```bash
# Chat tương tác (multi-turn, cùng thread_id trong 1 tiến trình)
python -m agents.workflow

# Trong code
from agents.workflow import run_workflow
answer, messages = run_workflow("Nghị định nào quy định về xử phạt vi phạm hành chính môi trường?", thread_id="demo")

# Vẽ sơ đồ graph
python -m agents.visualize --outdir docs/graphs
```

### Test

```bash
python test/test_llm.py                 # test registry + dispatcher LLM (không gọi API)
python test/test_llm.py --live          # kèm invoke thật (cần key + model trong .env)
python test/main_test.py                # test workflow: cấu trúc graph + multi-turn live
```

> Chạy bằng `python -m agents.<module>` (không có `.py`) để các import dạng `agents.*` hoạt động.

## Cấu hình chính (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LLM_PROVIDER` | `nvidia` | Provider mặc định (`groq` / `nvidia`) |
| `GROQ_API_KEY` / `GROQ_MODEL` | (trống) | Provider Groq |
| `NVIDIA_API_KEY` / `NVIDIA_MODEL` | (trống) | Provider NVIDIA |
| `QDRANT_URL` | `http://localhost:6333` | Địa chỉ Qdrant |
| `QDRANT_COLLECTION` | `vpl_chunks` | Collection đã ingest |
| `EMBEDDING_MODEL` | MiniLM L12 v2 384-d | Embedding query — phải khớp index |
| `RETRIEVE_TOP_K` | `6` | Số chunk trả về mỗi lần tra cứu |

## Mở rộng

- **Thêm tool**: viết pipeline trong `agents/utils.py`, khai báo tool + đăng ký `TOOLS` trong `agents/tools.py`, rồi liệt kê tên tool trong allowlist của node.
- **Thêm node**: hàm module-level nhận/trả `LegalQAState`, đăng ký trong `workflow()`.
- **Lưu trữ lâu dài**: đổi `MemorySaver` → `SqliteSaver` (hoặc PostgreSQL) cho checkpointer.

## Lưu ý

- Mỗi tiến trình chỉ tạo **1 embedder / 1 Qdrant store / 1 LLM rewrite** (cache singleton) — không khởi tạo lại mỗi lượt hỏi.
- Model NVIDIA `openai/gpt-oss-120b` không còn hoạt động (EOL); ưu tiên dùng Groq.
- Đánh giá & kế hoạch mở rộng (Neo4j, hybrid search, báo cáo giám sát): xem `docs/system/DESIGN.md`.