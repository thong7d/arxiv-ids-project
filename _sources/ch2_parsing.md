# Chương 2: Phân tích Phân cấp & Chuẩn hóa (Milestone 2 — Parsing & Standardization)

## 2.1. Giải thuật Phân tích Cấu trúc Tài liệu

Pipeline phân tích mã nguồn LaTeX chuyển đổi văn bản thô thành cây phân cấp ngữ nghĩa (`hierarchy.json`):
1. **Phát hiện Luồng Biên dịch Chính (Main Compilation Path):** Xác định file gốc chứa `\documentclass` và `\begin{document}`, lần theo đệ quy các lệnh `\input`, `\include`, phát hiện chu trình (cycle detection) và loại bỏ các file nháp không được biên dịch.
2. **Dựng Cây Phân cấp (Document Hierarchy):**
   - Nút gốc: Document.
   - Nút trung gian: Chapter, Section, Subsection, Paragraph, Itemize list.
   - Nút lá (Smallest Elements): Sentence (câu văn), Block Formula (công thức khối), Figure/Table.
   - Loại trừ phần References; giữ nguyên Acknowledgements và Appendices.
3. **Chuẩn hóa Toán học & Làm sạch:**
   - Chuẩn hóa Inline Math về `$...$`.
   - Chuẩn hóa Block Math về `\begin{equation}...\end{equation}`.
   - Lọc bỏ các thẻ định dạng rác (`\centering`, `[htpb]`, `\midrule`).
4. **Bóc tách BibTeX & Khử Trùng lặp:**
   - Chuyển đổi `\bibitem` thành BibTeX.
   - Khử trùng lặp trích dẫn (hợp nhất các trường, đồng bộ `\cite` key).
   - Khử trùng lặp nội dung toàn văn giữa các phiên bản (`v1`, `v2`, ...).

---

## 2.2. Thống kê & Hiệu năng Phân tích

*(Bảng số liệu và đồ thị phân tích sẽ được cập nhật tự động trong quá trình chạy dữ liệu chính thức).*
