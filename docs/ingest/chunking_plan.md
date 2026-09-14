# Kế hoạch chia chunk cho embedding văn bản pháp luật

## 1. Nguồn dữ liệu
- 52 file JSON tại `data/processed/*.json` (kết quả postprocess).
- Dùng trường `content` (toàn văn text thuần) + `metadata` (doc_num, title, doc_type, agency, issue_date, ...).

## 2. Số liệu thực tế quyết định chiến lược
- 26/52 văn bản có cấu trúc `Chương`, 26/52 không có Chương.
- Chương rất lớn, vượt ngưỡng token của model nhỏ:
  | Văn bản | Chương lớn nhất | Ký tự (~token) |
  |---|---|---|
  | 06/2026/TT-BTP | Chương IV | 33.960 (~10.000) |
  | 116/2025/UBTVQH15 | Chương III | 24.526 |
  | 28/2020/TT-BCA | Chương II | 41.000+ |
- Điều vừa phải: trung vị ~900–1.400 ký tự; chỉ ~5–10 Điều vượt ngưỡng 512 token (~1.500 ký tự).
- ⇒ Chunk "1 Điều" phù hợp model nhỏ; Chương giữ làm đường dẫn ngữ cảnh.

## 3. Chiến lược: hierarchical — chunk theo Điều, path theo Chương/Mục
- Đơn vị nhúng = **1 Điều** (header + khoản/điểm).
- Mỗi chunk có **path ngữ cảnh**: `Chương X → Mục Y → Điều Z`.
- Mỗi chunk có **prefix metadata**: `[doc_num] title — loại | cơ quan | ngày | <path>`.

## 4. Thuật toán chia (theo dòng, dùng regex)
1. Duyệt `content` theo dòng.
2. Nhận dạng:
   - `^\s*Chương\s+[IVX0-9]` → mở đoạn Chương (chapter_index tăng, kể cả khi số bị lặp do lỗi nguồn).
   - `^\s*Mục\s+[IVX0-9]` → mở đoạn Mục.
   - `^\s*Điều\s+\d+[a-z]?` → biên chunk Điều.
3. Gom dòng từ header Điều đến trước Điều kế → 1 chunk.
4. Chunk > max_tokens → chia theo dòng khoản (`^\s*\d+\.`), mỗi con giữ header Điều + "Khoản x".
5. Không có Điều:
   - Ngắn ≤ max_tokens → 1 chunk cả văn bản.
   - Dài → cắt theo ranh dòng, mỗi phần ~max_tokens.
6. Ước lượng token: `len(text) / 3.5` (tiếng Việt); `max_tokens` mặc định 512, cấu hình qua `--max-tokens`.

## 5. Output mỗi chunk
- `doc_id`, `doc_num`, `title`, `chunk_id` (`<doc_id>-<index>`)
- `path` (`Chương X → Mục Y → Điều Z`), `level` (`article` / `clause` / `whole`)
- `content` (nội dung gốc), `text` (prefix + content trước khi nhúng), `token_estimate`
- `vector` (384 chiều, L2-normalized, model sentence-transformers nhỏ)

## 6. Quy mô
- ~1.000–1.200 chunk × 384 chiều ≈ vài MB; chạy CPU vài chục giây.

## 7. Các trường hợp biên
- Lỗi đánh số nguồn (Chương III lặp 2 lần) → vẫn mở đoạn mới, dùng chapter_index để giữ thứ tự.
- Văn bản sửa đổi ("Điều 5a") → regex cho phép hậu tố chữ.
- Preamble (QUỐC HỘI/Chính phủ, Căn cứ..., Hà Nội, ngày...) đứng trước Chương I → gom thành chunk mở đầu riêng.

## 8. Cách chạy (sẽ viết ở bước tiếp theo)
- Script `ingest/chunk_and_embed.py`: đọc JSON → chia chunk → nhúng qua sentence-transformers → `data/embeddings/chunks.json`.