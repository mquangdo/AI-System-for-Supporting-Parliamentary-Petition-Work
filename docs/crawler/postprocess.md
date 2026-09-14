# Tài liệu: `crawler/postprocess.py`

File này chuyển dữ liệu crawl thô của vbpl.vn (payload RSC dạng Next.js) thành
1 file JSON gọn nhẹ cho từng văn bản, gồm 2 trường: **`content`** (toàn văn
văn bản dạng text thuần) và **`metadata`** (các thuộc tính mô tả văn bản).

---

## 1. Vai trò, đầu vào / đầu ra

| | |
|---|---|
| **Đầu vào** | `data/raw/vbpl/<tên văn bản>/raw_response.txt` (payload RSC) + `manifest.json` (cùng thư mục, nếu có) |
| **Đầu ra** | `data/processed/<tên văn bản>.json` với schema `{"content": ..., "metadata": {...}}` |
| **Cách chạy** | `python crawler/postprocess.py`<br>`python crawler/postprocess.py --raw-dir data/raw/vbpl --out-dir data/processed` |
| **Thư mục bỏ qua** | Thư mục không có `raw_response.txt` (lần crawl trước FAIL, `captured:false`) — đếm vào mục SKIP |

Thư mục `docs/` đặt **cùng cấp với `data/`** (tại root dự án), tức
`C:\Users\ASUS\QA Agent for Petition Work\docs`.

---

## 2. Cấu trúc dữ liệu nguồn (payload RSC)

`raw_response.txt` là payload RSC (React Server Components) của Next.js. Đã xác
minh trên toàn bộ dữ liệu, payload gồm các "frame" chính:

```
0:["$@1",["bjzE7ySRxs-etAuMPh0Vf",null]]     <- frame khởi tạo, tham chiếu "$@1"
2:T<hex>,<html>...</html>                     <- frame text: TOÀN VĂN HTML
1:{...json...}                                <- frame JSON cuối: METADATA
```

- Frame text có tiền tố `T<hex>,`: độ dài ghi ở dạng hex.
- Metadata JSON có `documentContent.content = "$2"` — chính là **tham chiếu**
  trỏ về frame text toàn văn ở trên.
- File lưu trên đĩa dùng dòng mới CRLF (`\r\n`) trong khi độ dài hex của frame
  do server tính không khớp chính xác với kích thước file thật → **không cắt
  theo độ dài hex**, phải cắt theo marker.

### Biến thể toàn văn HTML

- Đại đa số văn bản: toàn văn bắt đầu `<html>` → kết thúc `</html>`.
- Một số văn bản (VD `10-1999-CT-TTg`): payload là fragment chỉ có `<body>`.
- Vì vậy `extract_document_html` ưu tiên cặp `<html>...</html>`, nếu không có thì
  fallback sang `<body>...</body>`.

### Mojibake

Một phần dữ liệu crawl cũ bị lệch encoding ngay trên wire (server gửi chuỗi
UTF-8 bị đọc nhầm thành Windows-1252 rồi encode lại, VD "Đ" → `Ä\x90`).
`postprocess.py` gọi `_repair_mojibake` (tái sử dụng từ `crawler.py`) trên toàn
bộ payload trước khi trích; với text vốn đã sạch thì hàm vô hại (không đổi gì).

---

## 3. Từng hàm — cách hoạt động

### `_load_repair()`
Nạp hàm `_repair_mojibake` từ `crawler/crawler.py` bằng `importlib`.
Lý do không `import crawler` trực tiếp: thư mục tên `crawler` không có
`__init__.py`, dễ xung đột namespace với file `crawler.py` nằm bên trong.
Nạp theo đường dẫn file tường minh để luôn dùng đúng nguồn logic duy nhất.

### `extract_document_html(text)` → `str | None`
Tìm cặp mở/đóng toàn văn theo marker:
1. `text.find("<html>")` và `text.find("</html>", ...)` → cắt từ `<html>` đến
   hết `</html>`. Nếu đủ cả 2 → return.
2. Ngược lại thử `<body>` / `</body>`.
Trả `None` nếu không có cả hai (phòng văn bản lạ không chứa HTML).

### `parse_metadata(text)` → `dict | None`
- Tìm occurrence **cuối** của chuỗi `"1:{"` (`text.rfind("1:{")`) — vì frame
  metadata luôn là frame cuối của payload.
- Dùng `json.JSONDecoder().raw_decode()` để đọc **đúng một** đối tượng JSON từ
  vị trí `{`, bỏ qua phần dư phía sau (VD `\r\n`).
- Nếu không tìm thấy `"1:{"`, fallback quét regex `\b\d+:\{` bất kỳ (phòng server
  đổi số frame).
- Trả `None` nếu parse lỗi hoặc kết quả không phải `dict`.

### `html_to_text(html)` → `str`
Chuyển HTML toàn văn → text thuần giữ cấu trúc dòng bằng BeautifulSoup:
1. Xoá thẻ `script`, `style`, `head`.
2. `<br>` → ký tự xuống dòng.
3. Chèn xuống dòng **sau** mỗi khối `h1..h6`, `p`, `div`, `li`, `tr` để mỗi
   đoạn/điều/khoản/mục nằm 1 dòng riêng.
4. Gộp khoảng trắng (`[ \t\x0b\x0c]+` → 1 space), đổi `&nbsp;` (`\xa0`) thành
   dấu cách, strip từng dòng, lọc dòng rỗng → nối lại bằng `\n`.

### `process_folder(doc_dir, out_dir)` → `{"status": ...}`
Xử lý 1 thư mục văn bản:
1. Không có `raw_response.txt` → trả `{"status": "skip"}`.
2. Đọc `manifest.json` (nếu có) → dùng cho trường `metadata.source`.
3. Đọc file, `_repair_mojibake` → `extract_document_html` → `parse_metadata`.
4. Trích đủ thì ghi `data/processed/<tên>.json` và trả `{"status": "ok"}`.
5. Thất bại (thiếu HTML hoặc thiếu metadata) → `{"status": "fail"}`.

### `main()`
- `argparse`: `--raw-dir` (mặc định `data/raw/vbpl`), `--out-dir` (mặc định
  `data/processed`).
- Ép stdout UTF-8 để in tiếng Việt ổn định trên Windows.
- Lặp mọi thư mục con trong `raw-dir`, gọi `process_folder`, in dòng
  `[OK]`/`[SKIP]`/`[LỖI]` và tổng kết cuối.

---

## 4. Từng TRƯỜNG trong file JSON — xây từ đâu, lấy từ đâu

Nguồn ký hiệu: **RSC** = object JSON trong frame `1:{...}` (metadata của
vbpl.vn); **local** = `manifest.json` trong cùng thư mục văn bản.

| Trường output | Nguồn (key gốc) | Cách xây dựng | Ý nghĩa |
|---|---|---|---|
| `content` | RSC frame text `2:T…<html>…` | `extract_document_html` → `_repair_mojibake` → `html_to_text` | Toàn văn văn bản pháp luật dạng text thuần (đã bỏ thẻ HTML), dùng cho phân tích/QA |
| `metadata.doc_id` | RSC `id` | `str(id)` nếu không `null` | ID nội bộ của văn bản trên vbpl.vn (khóa duy nhất) |
| `metadata.doc_num` | RSC `docNum` | copy nếu có | Số hiệu văn bản (VD: `01/2013/TT-TTCP`) |
| `metadata.title` | RSC `title` | copy nếu có | Tiêu đề đầy đủ của văn bản |
| `metadata.doc_type.name` | RSC `docType.name` | copy nếu có | Loại văn bản (VD: Thông tư, Nghị định, Quyết định) |
| `metadata.doc_type.code` | RSC `docType.code` | copy nếu có | Mã loại văn bản (VD: `TT`, `NĐ`, `QĐ`) |
| `metadata.doc_group` | RSC `docGroup` | copy nếu có | Nhóm văn bản (VD: `VBQPPL`) |
| `metadata.issue_date` | RSC `issueDate` | đổi tên key (vẫn chuỗi ISO `YYYY-MM-DD`) | Ngày ban hành (ngày ký) văn bản |
| `metadata.effective_from` | RSC `effFrom` | đổi tên key | Ngày văn bản bắt đầu có hiệu lực |
| `metadata.effective_to` | RSC `effTo` | đổi tên key (`null` → trường được bỏ qua) | Ngày hết hiệu lực (`null` = còn hiệu lực hoặc chưa xác định) |
| `metadata.publication_date` | RSC `publicDate` | đổi tên key | Ngày đăng công khai/công báo |
| `metadata.eff_status.name` | RSC `effStatus.name` | copy nếu có | Tình trạng hiệu lực bằng chữ (VD: Còn hiệu lực, Hết hiệu lực) |
| `metadata.eff_status.code` | RSC `effStatus.code` | copy nếu có | Mã tình trạng hiệu lực (VD: `CHL`) |
| `metadata.status` | RSC `status` | copy nếu có (VD `"Publish"`) | Trạng thái xuất bản văn bản trên hệ thống |
| `metadata.lang` | RSC `lang` | copy nếu có (VD `"vi"`) | Ngôn ngữ gốc của văn bản |
| `metadata.agency` | RSC `agencyName` | copy nếu có | Cơ quan ban hành (VD: Thanh tra Chính phủ) |
| `metadata.organization.name` | RSC `organization.name` | copy nếu có | Tên tổ chức/cơ quan chủ quản trong hệ thống vbpl.vn |
| `metadata.organization.code` | RSC `organization.code` | copy nếu có | Mã tổ chức (VD: `G20`) |
| `metadata.organization.org_type` | RSC `organization.orgType` | đổi tên key | Kiểu tổ chức do hệ thống phân loại (giữ nguyên từ nguồn, không quy đổi) |
| `metadata.signers[]` | RSC `documentIssues[]` | map từng phần tử: `personName→person_name`, `jobTitleName→job_title`, `jobTitleCode→job_title_code`, `agencyName→agency`, `orderIndex→order_index`; chỉ giữ các key có giá trị | Danh sách người ký: họ tên, chức danh, cơ quan, thứ tự ký (VD: Tổng Thanh tra – Huỳnh Phong Tranh) |
| `metadata.majors[]` | RSC `documentMajors[]` | lấy `.name` mỗi phần tử | Lĩnh vực chuyên ngành mà văn bản điều chỉnh |
| `metadata.fields[]` | RSC `documentFields[]` | lấy `.name` mỗi phần tử | Lĩnh vực phân loại của văn bản (VD: "Chưa phân loại") |
| `metadata.files.original_pdf` | RSC `documentContentFileName` | copy nếu có | Tên file PDF gốc của văn bản (`VanBanGoc_...`) |
| `metadata.files.doc_source` | RSC `documentContentFileDocName` | copy nếu có | Tên file nguồn DOC (bản Word gốc) |
| `metadata.has_translation` | RSC `documentContentEn` | `True` nếu khác rỗng (không xuất nếu `null`) | Văn bản có bản dịch tiếng nước ngoài hay không |
| `metadata.related[]` | RSC `documentRelatedList[]` | map `relatedType→related_type`, `fileTitle→title`, `fileName→file_name` | Danh sách tài liệu liên quan (VD: file HTML nội dung, loại liên kết) |
| `metadata.review.review_status` | RSC `reviewStatus` | đổi tên key | Trạng thái rà soát/số hóa của hệ thống (VD: `RV_DONE`) |
| `metadata.review.view_count` | RSC `viewCount` | đổi tên key | Số lượt xem văn bản trên vbpl.vn |
| `metadata.review.has_content` | RSC `hasContent` | đổi tên key | Hệ thống xác nhận văn bản có nội dung |
| `metadata.review.has_original_pdf` | RSC `hasOriginalPdf` | đổi tên key | Hệ thống xác nhận văn bản có PDF gốc |
| `metadata.source.id` | local `manifest.json: id` | copy | ID văn bản ghi nhận trong manifest (khớp với `doc_id`) |
| `metadata.source.doc_num` | local `doc_num` | copy | Số hiệu ghi nhận tại lúc crawl (bản sao thô) |
| `metadata.source.title` | local `title` | copy | Tiêu đề ghi nhận tại lúc crawl (bản sao thô) |
| `metadata.source.source_url` | local `source_url` | copy | URL chi tiết đã crawl (`https://vbpl.vn/van-ban/chi-tiet/x--{id}`) |
| `metadata.source.crawled_at` | local `crawled_at` | copy | Thời điểm lấy dữ liệu (ISO 8601, UTC) |
| `metadata.source.content_hash` | local `content_hash` | copy | Mã băm sha256 payload thô — dùng đối chiếu tính toàn vẹn giữa các lần crawl |
| `metadata.source.http_status` | local `http_status` | copy | HTTP status của response khi crawl (VD: `200`) |
| `metadata.source.captured` | local `captured` | copy | Đánh dấu lần crawl có bắt được toàn văn hay không (`true`/`false`) |

### Nguyên tắc chung khi build metadata
- **Chỉ thêm trường khi nguồn có giá trị** (`if ... is not None` /
  `if ...`); không ghi các key kiểu `null`/"rỗng".
- `source` chỉ xuất hiện khi file `manifest.json` tồn tại và đọc được.
- Dữ liệu metadata lấy thẳng từ nguồn (không quy đổi, không tính toán thêm) —
  `postprocess.py` chỉ **đổi tên/đánh chỉ số** để gọn và đồng nhất schema.

---

## 5. Ghi chú vận hành

- Thư mục `data/processed` được tạo tự động nếu chưa tồn tại.
- Nếu `process_folder` không trích được cả HTML lẫn metadata, văn bản đó đếm
  vào `FAIL` — cần kiểm tra lại payload thô, không tự ghi JSON cụt.
- `raw` giữ nguyên; `postprocess.py` chỉ đọc, không sửa dữ liệu gốc.