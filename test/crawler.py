from playwright.sync_api import sync_playwright


URL = "https://vbpl.vn/van-ban/trung-uong"

KEYWORD = "Kiến nghị"

MATCH_MODE_OPTION = "Chính xác cụm từ trên"

OUTPUT_FILE = "van_ban_55_2022.txt"


def main():
    with sync_playwright() as p:

        # ==========================================
        # 1. MỞ CHROMIUM
        # ==========================================

        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page(
            viewport={
                "width": 1500,
                "height": 900
            }
        )

        # ==========================================
        # 2. MỞ TRANG VBPL
        # ==========================================

        print("Đang mở trang...")

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60_000
        )

        # Chờ giao diện client render xong
        page.wait_for_timeout(2000)

        print("Đã mở:", page.url)

        # ==========================================
        # 3. TÍCH "VĂN BẢN QUY PHẠM PHÁP LUẬT"
        # ==========================================

        print("Đang tìm 'Văn bản quy phạm pháp luật'...")

        document_type = page.get_by_label(
            "Văn bản quy phạm pháp luật",
            exact=True
        )

        document_type.wait_for(state="visible")
        document_type.check()

        print(
            "✓ Đã tích: Văn bản quy phạm pháp luật"
        )

        # Chờ danh sách refetch sau khi lọc
        page.wait_for_timeout(1000)

        # ==========================================
        # 4. CHỌN "TIÊU ĐỀ"
        # ==========================================

        print("Đang chọn 'Tiêu đề'...")

        title_radio = page.get_by_label(
            "Tiêu đề",
            exact=True
        )

        title_radio.wait_for(state="visible")
        title_radio.check()

        print("✓ Đã chọn: Tiêu đề")

        # ==========================================
        # 5. TÌM THANH TÌM KIẾM
        # ==========================================

        search_input = page.locator(
            'input[placeholder="Nhập từ khóa tìm kiếm"]'
        )

        print(
            "Số ô tìm kiếm:",
            search_input.count()
        )

        # ==========================================
        # 6. NHẬP TỪ KHÓA
        # ==========================================

        search_input.fill(KEYWORD)

        print(
            f"✓ Đã nhập từ khóa: {KEYWORD}"
        )

        # ==========================================
        # 7. ĐỔI MATCH-MODE THÀNH
        #    "CHÍNH XÁC CỤM TỪ TRÊN"
        # ==========================================

        print(
            "Đang click vào ô 'Có chứa các từ trên'..."
        )

        match_mode_current = page.locator(
            ".ant-select-selection-item:visible"
        ).filter(
            has_text="Có chứa các từ trên"
        ).first

        match_mode_current.wait_for(state="visible")

        # Bấm vào ô để mở dropdown
        match_mode_current.click()

        # Chờ dropdown mở ra
        page.wait_for_selector(
            ".ant-select-dropdown:visible",
            timeout=5000
        )

        page.wait_for_timeout(300)

        print(
            "Đang chọn option:",
            MATCH_MODE_OPTION
        )

        match_option = page.locator(
            ".ant-select-item-option"
        ).filter(
            has_text=MATCH_MODE_OPTION
        )

        options = page.locator(
            ".ant-select-item-option"
        )

        if match_option.count() == 0:

            print("⚠ Không tìm thấy option, các option có sẵn:")

            for i in range(options.count()):
                print(
                    " -",
                    options.nth(i).inner_text(),
                )

        else:

            match_option.first.click()

            print(
                f"✓ Đã chọn: {MATCH_MODE_OPTION}"
            )

        # ==========================================
        # 8. BẤM NÚT TÌM KIẾM MÀU XANH
        # ==========================================

        print("Đang bấm nút 'Tìm kiếm'...")

        search_button = page.get_by_role(
            "button",
            name="Tìm kiếm",
            exact=True
        ).first

        search_button.click()

        print("✓ Đã bấm nút Tìm kiếm")

        # ==========================================
        # 9. XỬ LÝ LỖI "ĐÃ XẢY RA LỖI" -> BẤM "THỬ LẠI"
        # ==========================================

        retry_btn = page.get_by_role(
            "button",
            name="Thử lại"
        )

        for attempt in range(3):

            # Chờ kết quả tải về (tối đa 10s)
            try:
                page.locator(".ant-list-item").first.wait_for(
                    state="visible",
                    timeout=10_000
                )
                break
            except Exception:
                pass

            # Nếu thấy lỗi "Không thể tải dữ liệu" và nút "Thử lại"
            if retry_btn.count() > 0 and retry_btn.first.is_visible():

                print(
                    f"⚠ Đã xảy ra lỗi, bấm 'Thử lại' (lần {attempt + 1})..."
                )

                retry_btn.first.click()

                page.wait_for_timeout(3000)

        result_items = page.locator(".ant-list-item")

        print(
            "Số kết quả hiển thị:",
            result_items.count()
        )

        print(
            "URL sau khi tìm kiếm:",
            page.url
        )

        if result_items.count() == 0:

            print(
                "❌ Không tải được danh sách văn bản."
            )

            input(
                "\nNhấn Enter để đóng trình duyệt..."
            )

            browser.close()
            return

        # ==========================================
        # 10. CLICK VÀO MỘT MỤC BẤT KỲ
        # ==========================================

        print("Đang tìm mục cần click...")

        # Chờ các thẻ kết quả render đầy đủ (skeleton -> nội dung thật)
        list_loaded = False

        for _ in range(20):

            if result_items.count() > 0:

                try:
                    card_text = result_items.first.inner_text()
                except Exception:
                    card_text = ""

                if card_text.strip():
                    list_loaded = True
                    break

            page.wait_for_timeout(500)

        if not list_loaded:

            print(
                "❌ Danh sách chưa hiển thị nội dung."
            )

            input(
                "\nNhấn Enter để đóng trình duyệt..."
            )

            browser.close()
            return

        # Ưu tiên link đúng văn bản cần tìm
        target_link = page.locator(
            'a[href*="/van-ban/chi-tiet/"]'
        ).filter(
            has_text="Nghị định số 55/2022/NĐ-CP"
        )

        if target_link.count() == 0:

            target_link = page.locator(
                '[class*="DocumentCard_documentTitle"]'
            ).filter(
                has_text="Nghị định số 55/2022/NĐ-CP"
            )

        if target_link.count() > 0:

            item = target_link.first

            print("✓ Tìm thấy: Nghị định số 55/2022/NĐ-CP")

        else:

            # Click vào mục đầu tiên bất kỳ
            first_card = result_items.first

            card_link = first_card.locator(
                'a[href*="/van-ban/chi-tiet/"]'
            )

            if card_link.count() > 0:

                item = card_link.first

            else:

                item = first_card.locator(
                    '[class*="DocumentCard_documentTitle"]'
                ).first

                if item.count() == 0:
                    item = first_card

            print(
                "✓ Click vào mục đầu tiên:",
                item.inner_text().strip()[:80]
            )

        item.scroll_into_view_if_needed()

        print(
            "Href:",
            item.get_attribute("href")
        )

        # ==========================================
        # 11. ĐIỀU HƯỚNG SANG TRANG CHI TIẾT
        # ==========================================

        before_url = page.url

        item.click()

        # Chờ URL chuyển sang trang chi tiết
        # (tối đa 10s), chấp nhận cả trường hợp mở tab mới
        for _ in range(20):

            for pg in page.context.pages:

                if "chi-tiet" in pg.url:

                    if pg != page:
                        page = pg

                    break

            if "chi-tiet" in page.url:
                break

            if page.url != before_url:
                break

            page.wait_for_timeout(500)

        page.wait_for_timeout(2500)

        print(
            "URL trang chi tiết:",
            page.url
        )

        if "chi-tiet" not in page.url:

            # Thử click lần nữa nếu chưa điều hướng
            print("⚠ Chưa điều hướng, click lại...")

            item.click()

            page.wait_for_timeout(3000)

            print(
                "URL trang chi tiết:",
                page.url
            )

        # ==========================================
        # 12. CHỜ TRANG CHI TIẾT RENDER
        #     (nếu lỗi thì bấm "Thử lại")
        # ==========================================

        def get_tab(name):

            tab = page.get_by_role(
                "tab",
                name=name,
                exact=True
            )

            if tab.count() == 0:

                # Fallback theo cấu trúc rc-tabs
                tab = page.locator(
                    '[id^="rc-tabs-"].ant-tabs-tab-btn'
                ).filter(
                    has_text=name
                )

            return tab.first

        content_tab = get_tab("Nội dung")

        loaded = False

        for attempt in range(3):

            try:

                content_tab.wait_for(
                    state="visible",
                    timeout=10_000
                )

                loaded = True
                break

            except Exception:

                retry = page.get_by_role(
                    "button",
                    name="Thử lại"
                )

                if retry.count() > 0 and retry.first.is_visible():

                    print(
                        f"⚠ Trang chi tiết lỗi, bấm 'Thử lại' "
                        f"(lần {attempt + 1})..."
                    )

                    retry.first.click()

                    page.wait_for_timeout(3000)

        if not loaded:

            print(
                "❌ Không tải được trang chi tiết."
            )

            input(
                "\nNhấn Enter để đóng trình duyệt..."
            )

            browser.close()
            return

        title_text = page.locator("h1").inner_text().strip()

        print()
        print("TÊN VĂN BẢN:")
        print(title_text)

        def get_body_text(marker=None, min_len=0):

            text = ""

            for _ in range(20):

                text = page.locator("body").inner_text()

                if text.strip() and len(text.strip()) >= min_len:

                    if marker is None or marker in text:
                        return text

                page.wait_for_timeout(500)

            return text

        print()
        print("Đang đọc tab 'Nội dung'...")

        content_tab.click()

        content_text = get_body_text(min_len=100)

        print(
            "Số ký tự nội dung:",
            len(content_text)
        )

        print()
        print("Đang đọc tab 'Thuộc tính'...")

        attributes_tab = get_tab("Thuộc tính")

        attributes_tab.wait_for(state="visible")
        attributes_tab.click()

        attributes_text = get_body_text(
            marker="Người ký",
            min_len=100
        )

        print(
            "Số ký tự thuộc tính:",
            len(attributes_text)
        )

        # ==========================================
        # 13. GHI RA FILE TXT
        # ==========================================

        print()
        print("Đang ghi file...")

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                "=" * 80
            )
            f.write("\n")
            f.write("TÊN VĂN BẢN\n")
            f.write(
                "=" * 80
            )
            f.write("\n\n")

            f.write(title_text)

            f.write("\n\n")

            # --------------------------------------
            # NỘI DUNG
            # --------------------------------------

            f.write(
                "=" * 80
            )
            f.write("\n")
            f.write("NỘI DUNG\n")
            f.write(
                "=" * 80
            )
            f.write("\n\n")

            f.write(content_text)

            f.write("\n\n\n")

            # --------------------------------------
            # THUỘC TÍNH
            # --------------------------------------

            f.write(
                "=" * 80
            )
            f.write("\n")
            f.write("THUỘC TÍNH\n")
            f.write(
                "=" * 80
            )
            f.write("\n\n")

            f.write(attributes_text)

        print("✓ Đã ghi:", OUTPUT_FILE)

        # Giữ trình duyệt mở để kiểm tra
        input(
            "\nNhấn Enter để đóng trình duyệt..."
        )

        browser.close()


if __name__ == "__main__":
    main()