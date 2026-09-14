"""Crawl hàng loạt văn bản pháp luật Trung ương từ vbpl.vn.

Quy trình tổng thể gồm 2 pha:

Pha 1 - Xây worklist (build_worklist):
    Mở trang https://vbpl.vn/van-ban/trung-uong rồi thực hiện đúng chuỗi
    thao tác tìm kiếm như crawler.py:
      1. Tích checkbox "Văn bản quy phạm pháp luật".
      2. Chọn radio tìm theo "Tiêu đề".
      3. Đổi kiểu khớp (match-mode) thành "Chính xác cụm từ trên".
      4. Nhập từ khóa KEYWORD ("Kiến nghị").
      5. Bấm nút "Tìm kiếm", xử lý lỗi "Đã xảy ra lỗi" bằng nút "Thử lại".
    Xong phải gọi nút "Xuất Excel" ở TỪNG trang kết quả để tải về file .xlsx,
    đọc (id, so_hieu, tieu_de) bằng openpyxl rồi ghi tiếp vào worklist
    data/vbpl_document_queue.jsonl (mỗi văn bản 1 dòng JSON, lọc trùng id).
    Pagination bằng nút ".ant-pagination-next"; dừng khi hết trang.

Pha 2 - Crawl từng văn bản (crawl_one):
    Với mỗi văn bản trong worklist, mở URL chi tiết
    https://vbpl.vn/van-ban/chi-tiet/x--{id} và BẮT response RSC của Next.js
    (content-type text/x-component) thay vì đọc DOM:
      - response chứa "documentContent" -> toàn văn, ghi raw_response.txt.
      - response chứa "documentNamesBy"  -> phần "Lược đồ", ghi luoc_do_raw.txt.
    Kèm ghi manifest.json (id, hash sha256, http_status, captured...).
    Dữ liệu lưu vào {ROOT}/data/raw/vbpl/<so-hieu - tieu-de>/.

Lưu ý encoding (đã xử lý triệt để lỗi định dạng tiếng Việt):
    Payload RSC của vbpl.vn gửi về ĐÃ BỊ rối encoding ngay trên wire: text
    tiếng Việt UTF-8 bị đọc nhầm thành Windows-1252 rồi encode lại thành UTF-8
    (VD "QUYẾT ĐỊNH" -> "QUYáº¾T Ä\x90á»ŠNH"). Do đó ngoài việc phải lấy byte
    thô qua response.body() (response.text() của Playwright mặc định giải mã
    theo Windows-1252 khi không có charset), code còn phải gọi _repair_mojibake()
    để khôi phục lại chuỗi tiếng Việt đúng gốc trước khi ghi file.

Lưu ý chống bot (WAF /_fec_sbu):
    vbpl.vn chặn khi trình duyệt headless dùng User-Agent mặc định
    ("HeadlessChrome" là dấu hiệu bot). Giải pháp: vẫn headless=True nhưng phải
    set user_agent là một Chrome thật trong new_context(...).

Cách chạy:
    python crawler/crawl_all.py            # crawl toàn bộ worklist
    python crawler/crawl_all.py 10         # dừng sau 10 văn bản mới (không tính SKIP)
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from playwright.sync_api import sync_playwright

# ROOT = thư mục cha của "crawler" (tức cùng cấp với folder crawler).
# Do file này nằm ở {ROOT}/crawler/crawl_all.py nên parent.parent = {ROOT}.
ROOT = Path(__file__).parent.parent

# Thư mục chứa dữ liệu crawl thô: {ROOT}/data/raw/vbpl/<ten van ban>/...
RAW_DIR = ROOT / "data" / "raw" / "vbpl"

# Trang danh sách văn bản quy phạm pháp luật Trung ương.
LISTING_URL = "https://vbpl.vn/van-ban/trung-uong"

# Từ khóa tìm kiếm theo "Tiêu đề". Để project: văn bản liên quan công tác
# tiếp công dân / khiếu nại / kiến nghị / phản ánh.
KEYWORD = "Kiến nghị"

# Giá trị match-mode cần chọn trong dropdown, khác với giá trị mặc định
# "Có chứa các từ trên" -> chỉ lấy văn bản có ĐÚNG cụm từ khóa.
MATCH_MODE_OPTION = "Chính xác cụm từ trên"

# Worklist: mỗi dòng JSON 1 văn bản {"id", "doc_num", "title"}.
WORKLIST_PATH = ROOT / "data" / "vbpl_document_queue.jsonl"

# Thời gian chờ giữa 2 văn bản (giây) để tránh bị WAF/rate-limit.
DELAY_BETWEEN_DOCS = 4

# Thời gian chờ sau khi sang trang kết quả tiếp theo (giây).
DELAY_BETWEEN_PAGES = 2

# Ký tự không hợp lệ trong tên file/folder trên Windows, dùng để làm sạch
# "so hieu" và "tieu de" khi tạo tên thư mục output.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Ký tự BỊ RỐI đặc trưng (không bao giờ xuất hiện trong tiếng Việt chuẩn).
# Dùng để "phát hiện" payload đã bị mojibake trước khi sửa.
_MOJIBAKE_MARKERS = ("\u00c4", "\u00ba", "\u00be", "\u00bb")  # Ä º ¾ »


def _repair_mojibake(text: str) -> str:
    """Sửa mojibake 1 lớp: UTF-8 bị đọc nhầm thành Windows-1252 rồi encode lại.

    Server vbpl.vn gửi payload RSC (text/x-component) với phần nội dung đã bị
    bóp lệch encoding NGAY TRÊN WIRE: chuỗi tiếng Việt UTF-8 bị đọc nhầm
    thành Windows-1252 rồi encode lại thành UTF-8, nên dù lấy byte thô qua
    response.body() và decode("utf-8") ta vẫn nhận một chuỗi MOJIBAKE
    (VD "Đ" thành "Ä\\x90", "Ế" thành "áº¾", "Độc lập" thành "Ä\\x90á»™c láº­p").

    Cách sửa: encode -NGƯỢC- từng ký tự về chuỗi byte gốc rồi decode UTF-8:
      - byte 0x80-0x9F trong chuỗi mojibake chính là byte gốc (giữ nguyên).
      - ký tự khác: thử encode theo cp1252; không được thì thử latin-1;
        vẫn không được thì bỏ qua (hiếm gặp) để không phá byte.
    Kết quả là chuỗi tiếng Việt đúng gốc ban đầu.

    An toàn: chỉ áp dụng khi text có dấu hiệu rối (chứa ký tự trong
    _MOJIBAKE_MARKERS). Nếu text vốn đã sạch thì trả về nguyên trạng, nên
    gọi vô hại cả khi server sau này gửi payload chuẩn.

    Args:
        text: Chuỗi đã decode UTF-8 từ byte thô của response.

    Returns:
        Chuỗi sạch nếu bị rối, ngược lại giữ nguyên `text`.
    """
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text

    raw = bytearray()
    for ch in text:
        cp = ord(ch)
        if 0x80 <= cp <= 0x9F:  # C1 control: trong mojibake thì chính là byte gốc
            raw.append(cp)
            continue
        try:
            raw += ch.encode("cp1252")
        except UnicodeEncodeError:
            try:
                raw += ch.encode("latin-1")
            except UnicodeEncodeError:
                continue  # ký tự lạ hiếm gặp: bỏ qua thay vì phá mất byte
    return raw.decode("utf-8", errors="replace")


def build_worklist(page, max_pages=100) -> list[dict]:
    """Thực hiện chuỗi tìm kiếm kiểu crawler.py rồi export Excel từng trang.

    Đầu tiên bộ lọc tìm kiếm được cấu hình y hệt crawler.py:
      1. Tích checkbox 'Văn bản quy phạm pháp luật' (lấy mọi loại VBQPPL).
      2. Chọn radio tìm theo 'Tiêu đề' (thay vì 'Toàn văn').
      3. Đổi match-mode -> 'Chính xác cụm từ trên'.
      4. Nhập KEYWORD vào ô tìm kiếm.
      5. Bấm nút 'Tìm kiếm'; nếu server báo 'Đã xảy ra lỗi' thì bấm 'Thử lại'
         (tối đa 3 lần) rồi chờ danh sách render xong.

    Sau khi có kết quả, vòng lặp từng trang KẾT HỢP nút 'Xuất Excel' (tải file
    .xlsx xuống) + pagination '.ant-pagination-next'. Mỗi file Excel đọc bằng
    openpyxl (cột: id | so hieu | tieu de) để ghi vào worklist JSONL.

    Args:
        page: Page Playwright đang dùng (browser đã mở listing_url).
        max_pages: Trần cứng số trang tối đa quét (phòng trường hợp lỗi
            pagination không bao giờ dừng). Mặc định 100.

    Returns:
        List dict các văn bản {"id", "doc_num", "title"} đã gom được
        (đã lọc trùng id qua seen_ids).
    """
    # Mở trang danh sách, chờ mạng ổn định để React render xong giao diện.
    page.goto(LISTING_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2000)

    # ---- Bước tìm kiếm 1: tích "Văn bản quy phạm pháp luật" ----
    # get_by_label + exact=True để tránh dính nhầm nhãn trùng một phần.
    document_type = page.get_by_label(
        "Văn bản quy phạm pháp luật",
        exact=True
    )
    document_type.wait_for(state="visible")
    document_type.check()
    # Sau khi lọc, danh sách refetch; chờ 1s cho ổn định.
    page.wait_for_timeout(1000)

    # ---- Bước tìm kiếm 2: chọn cách tìm theo "Tiêu đề" ----
    title_radio = page.get_by_label(
        "Tiêu đề",
        exact=True
    )
    title_radio.wait_for(state="visible")
    title_radio.check()

    # ---- Bước tìm kiếm 3: nhập từ khóa ----
    # Ô tìm kiếm gần thanh lọc; có nhiều hộp "Nhập từ khóa" trên trang nên
    # chọn theo placeholder chính xác.
    search_input = page.locator(
        'input[placeholder="Nhập từ khóa tìm kiếm"]'
    )
    search_input.fill(KEYWORD)

    # ---- Bước tìm kiếm 4: đổi match-mode thành "Chính xác cụm từ trên" ----
    # Ô hiện tại mặc định hiện nhãn "Có chứa các từ trên" (Ant Design select).
    # :visible lọc đúng ô đang hiển thị (trang có nhân bản selector ẩn/dàn mobile).
    match_mode_current = page.locator(
        ".ant-select-selection-item:visible"
    ).filter(
        has_text="Có chứa các từ trên"
    ).first

    match_mode_current.wait_for(state="visible")
    match_mode_current.click()

    # Chờ dropdown mở ra rồi nhấp chọn option mong muốn.
    page.wait_for_selector(
        ".ant-select-dropdown:visible",
        timeout=5000
    )
    page.wait_for_timeout(300)

    match_option = page.locator(
        ".ant-select-item-option"
    ).filter(
        has_text=MATCH_MODE_OPTION
    )

    if match_option.count() > 0:
        match_option.first.click()
    else:
        print(
            "    [CẢNH BÁO] Không tìm thấy option '"
            + MATCH_MODE_OPTION
            + "' trong dropdown — vẫn tiếp tục với match-mode mặc định."
        )

    # ---- Bước tìm kiếm 5: bấm nút "Tìm kiếm" ----
    # Trang có nút "Tìm kiếm" ở cả header lẫn thanh lọc, nên lấy .first.
    search_button = page.get_by_role(
        "button",
        name="Tìm kiếm",
        exact=True
    ).first
    search_button.click()

    # ---- Bước tìm kiếm 6: chờ kết quả + xử lý lỗi "Thử lại" ----
    # Server đôi khi trả UI lỗi "Đã xảy ra lỗi / Không thể tải dữ liệu" kèm
    # nút "Thử lại". Vòng lặp: chờ .ant-list-item 10s; không thấy thì bấm
    # "Thử lại" và chờ 3s, tối đa 3 lần.
    retry_btn = page.get_by_role(
        "button",
        name="Thử lại"
    )

    for attempt in range(3):
        try:
            page.locator(".ant-list-item").first.wait_for(
                state="visible",
                timeout=10_000
            )
            break
        except Exception:
            pass

        if retry_btn.count() > 0 and retry_btn.first.is_visible():
            print(
                f"    [CẢNH BÁO] Tìm kiếm gặp lỗi 'Không thể tải dữ liệu'"
                f" — bấm 'Thử lại' (lần {attempt + 1}/3)..."
            )
            retry_btn.first.click()
            page.wait_for_timeout(3000)

    # Ant Design render 10 thẻ <li class="ant-list-item"> skeleton RỖNG ngay,
    # sau đó mới điền nội dung. Nếu sang bước "Xuất Excel" khi skeleton rỗng
    # thì Excel export có thể lỗi/thiếu. Nên chờ card đầu tiên có text thật.
    for _ in range(20):
        try:
            if page.locator(".ant-list-item").first.inner_text().strip():
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    # Chờ mạng yên tĩnh nữa; networkidle có thể không bao giờ đạt (có request
    # nền) nên bọc try/except để không crash.
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    # ---- Xuất Excel từng trang + đọc vào worklist ----
    seen_ids = set()  # lọc trùng id giữa các trang (phòng export lặp mục cũ)
    all_docs = []
    # File Excel tải xuống tạm; sẽ bị xóa ở cuối hàm.
    xlsx_path = ROOT / "data" / "_tmp_full_export.xlsx"

    for page_num in range(1, max_pages + 1):
        # Nút "Xuất Excel" trả download; Playwright bắt qua expect_download.
        excel_btn = page.locator("button:has-text('Xuất Excel')").first
        try:
            with page.expect_download(timeout=30000) as dl_info:
                excel_btn.click()
            dl_info.value.save_as(str(xlsx_path))
        except Exception as e:
            print(f"    [LỖI] Trang {page_num}: xuất Excel thất bại — {e}")
            break

        # Đọc sheet: bỏ dòng tiêu đề (min_row=2). Cột giả định:
        # [0]=id, [1]=so hieu, [2]=tieu de.
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        new_count = 0
        for row in rows:
            doc_id = row[0]
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            doc = {"id": doc_id, "doc_num": row[1], "title": row[2]}
            all_docs.append(doc)
            new_count += 1
            # Ghi nối vào worklist để nếu chương trình dừng giữa chừng thì lần
            # chạy sau có worklist sẵn (không phải export lại từ đầu).
            with WORKLIST_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")

        print(f"    Trang {page_num:>3}: thêm {new_count} văn bản (tổng {len(all_docs)})")

        # ---- Sang trang kết quả tiếp theo ----
        next_btn = page.locator(".ant-pagination-next").first
        if next_btn.count() == 0:
            print("    Không tìm thấy nút phân trang tiếp theo — dừng.")
            break
        cls = next_btn.get_attribute("class") or ""
        if "disabled" in cls:
            print("    Đã đến trang cuối — dừng.")
            break

        # .click() bị chặn nếu nút chồng nhau -> dùng evaluate click trực tiếp.
        next_btn.evaluate("el => el.click()")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(DELAY_BETWEEN_PAGES * 1000)

    xlsx_path.unlink(missing_ok=True)
    return all_docs


def crawl_one(page, doc: dict) -> str:
    """Crawl 1 văn bản: bắt 2 response RSC rồi lưu vào thư mục riêng.

    Với văn bản doc (có "id"), hàm tìm/tạo thư mục output:
        {ROOT}/data/raw/vbpl/<so-hieu - tieu-de>/
    trong đó chứa:
        - raw_response.txt : payload RSC chứa "documentContent" (toàn văn).
        - luoc_do_raw.txt   : payload RSC chứa "documentNamesBy" (lược đồ, nếu có).
        - manifest.json     : metadata (id, hash sha256, http_status, captured...).

    Tự chứa đủ cơ chế (tìm thư mục, đặt tên tránh trùng, ghi manifest) nên có
    thể gọi độc lập, không phụ thuộc file nào khác. Có thể chạy lại an toàn:
    - manifest có "captured": true -> trả "SKIP" (đã xong trước đó).
    - manifest "captured": false (lần trước FAIL) -> thử lại, không tính thành công.

    Returns:
        "OK" nếu bắt được cả toàn văn và lược đồ.
        "OK(no-luocdo)" nếu chỉ bắt được toàn văn.
        "SKIP" nếu đã crawl thành công ở lần chạy trước.
        "FAIL" nếu không bắt được response "documentContent".
    """
    import hashlib
    guid = doc["id"]

    def capture_rsc(url: str, match_substr: str) -> dict | None:
        """Mở url, bắt response RSC đầu tiên thỏa (đồng thời):

          1. Cùng URL gốc (bỏ query string). Lọc vậy để tránh bắt nhầm response
             prefetch của link khác, VD Next.js prefetch "/gioi-thieu" khi hover.
          2. content-type thuộc loại RSC: "text/x-component" hoặc "text/plain".
          3. Body (giải mã UTF-8) có chứa match_substr
             ("documentContent" cho toàn văn, "documentNamesBy" cho lược đồ).

        QUAN TRỌNG - encoding: payload RSC của vbpl.vn gửi về đã bị bóp lệch
        NGAY TRÊN WIRE: text tiếng Việt UTF-8 bị đọc nhầm thành Windows-1252 rồi
        encode lại thành UTF-8 (server gửi mojibake sẵn). Nên ta phải:
          1. Lấy byte thô qua response.body() thay vì response.text()
             (response.text() của Playwright mặc định giải mã theo chuẩn MIME
             khi thiếu charset, càng làm mất byte chính xác).
          2. Decode("utf-8"), lỗi thì fallback cp1252.
          3. Gọi _repair_mojibake() để khôi phục tiếng Việt đúng gốc.

        Args:
            url: URL chi tiết văn bản (có thể kèm query "?tabs=luoc-do").
            match_substr: chuỗi ASCII dùng để nhận diện đúng loại payload.

        Returns:
            Dict {"url", "status", "text"} của response đầu tiên khớp, hoặc None.
        """
        captured = {}
        # Cắt bỏ query string để so khớp "cùng URL", tránh bắt nhầm prefetch.
        url_prefix = url.split("?")[0]

        def on_response(response):
            # Đã bắt được rồi thì bỏ qua (chỉ cần response đầu tiên).
            if captured or not response.url.startswith(url_prefix):
                return
            ctype = response.headers.get("content-type", "")
            if "text/x-component" not in ctype and "text/plain" not in ctype:
                return
            try:
                raw = response.body()
            except Exception:
                return

            # Decode UTF-8 trực tiếp từ byte thô rồi sửa mojibake nếu server
            # gửi text đã bị bóp lệch encoding (VBPL gửi mojibake sẵn).
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
            text = _repair_mojibake(text)

            if match_substr in text:
                captured["url"] = response.url
                captured["status"] = response.status
                captured["text"] = text

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
        page.remove_listener("response", on_response)
        return captured or None

    # ---- Đặt tên thư mục output ----
    # Làm sạch ký tự không hợp lệ trên Windows (/, \, :, *, ?, ...).
    # Chú ý: nhiều văn bản CŨ có chung doc_num "Khong so" -> nếu không xử lý
    # trùng tên sẽ ghi đè/SKIP nhầm văn bản khác (từng mất dữ liệu vì lý do này).
    doc_num_safe = _UNSAFE_CHARS.sub("-", (doc.get("doc_num") or "khong-so").strip())
    title_safe = re.sub(r"\s+", " ", _UNSAFE_CHARS.sub("", (doc.get("title") or "").strip())).strip()[:80].rstrip(". ")
    base_name = (f"{doc_num_safe} - {title_safe}" if title_safe else doc_num_safe).rstrip(". ")

    # Nếu tên cơ bản đã tồn tại cho văn bản KHÁC thì thêm "[guid8]" vào sau.
    name = base_name
    suffix_n = 0
    while True:
        out_dir = RAW_DIR / name
        manifest_path = out_dir / "manifest.json"
        if not manifest_path.exists():
            break
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if existing.get("id") == guid:
            break  # đúng văn bản này rồi, không phải va chạm tên
        suffix_n += 1
        name = f"{base_name} [{guid[:8] if guid else 'unknown'}]"
        if suffix_n > 5:  # phòng vòng lặp vô hạn (không thực tế xảy ra)
            out_dir = RAW_DIR / f"{base_name} [{guid}]"
            manifest_path = out_dir / "manifest.json"
            break

    # ---- Bỏ qua nếu đã crawl xong ----
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if existing.get("captured"):
            return "SKIP"
        # captured=false (lần trước FAIL) -> thử lại, không coi là đã xong.

    out_dir.mkdir(parents=True, exist_ok=True)

    # URL chi tiết: Next.js route "/van-ban/chi-tiet/x--{guid}"
    # (khác dạng URL công khai đẹp có slug; slug này nội bộ và ổn định hơn).
    base_url = f"https://vbpl.vn/van-ban/chi-tiet/x--{guid}"

    # ---- Bắt toàn văn (RSC "documentContent") ----
    content = capture_rsc(base_url, "documentContent")
    if not content:
        # Ghi manifest FAIL để lần chạy sau biết chưa xong (sẽ thử lại).
        manifest = {
            "id": guid, "doc_num": doc.get("doc_num"), "title": doc.get("title"),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "source_url": base_url, "captured": False,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return "FAIL"

    (out_dir / "raw_response.txt").write_text(content["text"], encoding="utf-8")

    # ---- Bắt lược đồ (query "?tabs=luoc-do") ----
    time.sleep(2)  # chờ nhẹ, tránh bị WAF nhận diện crawl nhanh
    luocdo = capture_rsc(f"{base_url}?tabs=luoc-do", "documentNamesBy")
    if luocdo:
        (out_dir / "luoc_do_raw.txt").write_text(luocdo["text"], encoding="utf-8")

    # ---- Ghi manifest thành công ----
    # content_hash là sha256 của raw payload, dùng để phát hiện nội dung thay
    # đổi giữa các lần crawl (verify tính toàn vẹn).
    content_hash = hashlib.sha256(content["text"].encode("utf-8")).hexdigest()
    manifest = {
        "id": guid, "doc_num": doc.get("doc_num"), "title": doc.get("title"),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "source_url": base_url,
        "captured_request_url": content["url"],
        "http_status": content["status"],
        "content_hash": f"sha256:{content_hash}",
        "raw_chars": len(content["text"]),
        "captured": True,
        "luoc_do_full_captured": bool(luocdo),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return "OK" if luocdo else "OK(no-luocdo)"


def main():
    """Điều phối toàn bộ: đọc/dựng worklist rồi crawl tuần tự từng văn bản.

    - Nếu worklist (data/vbpl_document_queue.jsonl) đã tồn tại thì đọc thẳng
      (lọc trùng id), KHÔNG build lại -> tiếp tục được từ lần chạy trước.
    - Nếu chưa có thì gọi build_worklist(page) để quét toàn bộ trang kết quả.
    - Nhận đối số dòng lệnh là số văn bản MỚI tối đa (không tính SKIP):
        python crawl_all.py        -> crawl hết
        python crawl_all.py 5      -> dừng sau 5 văn bản mới
    - Báo cáo kết quả theo nhóm: OK / OK(no-luocdo) / SKIP / FAIL.
    """
    # Ép stdout UTF-8: chạy qua pipe/console cũ trên Windows mặc định là
    # cp1252 và sẽ UnicodeEncodeError khi in tiếng Việt.
    sys.stdout.reconfigure(encoding="utf-8")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # vbpl.vn chặn khi headless dùng UA mặc định (chứa "HeadlessChrome").
        # Set UA Chrome thật + giữ headless=True vẫn QUA được WAF /_fec_sbu
        # (bản trước đã chạy ổn). Thêm viewport cho render giống desktop.
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1500, "height": 900},
        ).new_page()

        # ---- Đọc/dựng worklist ----
        if WORKLIST_PATH.exists():
            print(f"[*] Đã có worklist sẵn: {WORKLIST_PATH}")
            docs = [json.loads(line) for line in WORKLIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
            # Lọc trùng id (phòng file worklist bị ghi đè/ghi nối trùng).
            seen = set()
            docs = [d for d in docs if not (d["id"] in seen or seen.add(d["id"]))]
        else:
            print("[*] Chưa có worklist — xây dựng mới bằng cách quét hết các trang kết quả...")
            docs = build_worklist(page)

        print(f"[+] Tổng số văn bản cần crawl: {len(docs)}")

        # ---- Giới hạn số văn bản mới (argv[1]) ----
        max_new = int(sys.argv[1]) if len(sys.argv) > 1 else None
        if max_new:
            print(f"[*] Đã đặt giới hạn: dừng sau {max_new} văn bản mới (không tính SKIP)")

        # ---- Vòng lặp crawl chính ----
        counts = {"OK": 0, "OK(no-luocdo)": 0, "SKIP": 0, "FAIL": 0}
        n_new = 0
        for i, doc in enumerate(docs):
            status = crawl_one(page, doc)
            counts[status] = counts.get(status, 0) + 1
            print(
                f"[{i+1:>4}/{len(docs)}] {status:<14} "
                f"{doc['doc_num']:<18} {doc['title'][:55]}"
            )
            if status != "SKIP":
                n_new += 1
                if max_new and n_new >= max_new:
                    print(f"[*] Đã đạt đủ {max_new} văn bản mới — dừng lại.")
                    break
                # Chờ giữa 2 văn bản để tránh rate-limit/WAF.
                time.sleep(DELAY_BETWEEN_DOCS)

        browser.close()

    # ---- Tổng kết theo nhóm trạng thái ----
    print("\n================= HOÀN TẤT =================")
    print(f"  OK              : {counts['OK']} văn bản (đầy đủ toàn văn + lược đồ)")
    print(f"  OK (no-luocdo)  : {counts['OK(no-luocdo)']} văn bản (toàn văn, thiếu lược đồ)")
    print(f"  SKIP            : {counts['SKIP']} văn bản (đã crawl từ trước)")
    print(f"  FAIL            : {counts['FAIL']} văn bản (lỗi, sẽ thử lại lần chạy sau)")
    print("=============================================")


if __name__ == "__main__":
    main()