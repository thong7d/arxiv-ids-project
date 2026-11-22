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
4. **Bóc tách BibTeX đa tầng & Khử Trùng lặp (Colab CPU-only):**
   - **Tầng 1 (`.bib` gốc):** Bóc tách trực tiếp từ các tệp `.bib` trong thư mục phiên bản.
   - **Tầng 2 (`\bibitem` & `.bbl`):** Chuyển đổi các khối `\begin{thebibliography}...\bibitem` trong `.tex` (và tệp `.bbl` nếu có) sang cấu trúc BibTeX chuẩn bằng Regex/Parser trên CPU.
   - **Tầng 3 (References viết tay không dùng `\bibitem`/`.bib`):** Với các bài tác giả tự gõ mục tài liệu tham khảo thủ công (ví dụ `\section*{References}` kèm danh sách `\item` hoặc đoạn văn thường), parser áp dụng bộ quy tắc heuristic nhận diện vùng References cuối bài để tách từng mục trích dẫn và ghi nhận thống kê thực nghiệm vào báo cáo.
   - **Khử trùng lặp 2 cấp độ:** Hợp nhất các citation key trùng lặp, đồng bộ lệnh `\cite{}` trong cây phân cấp, và khử trùng lặp nội dung toàn văn giữa các phiên bản (`v1`, `v2`, ...).
5. **Bảo toàn bản ghi phiên bản rỗng (HTTP 404 & PDF-only):**
   - Các phiên bản không có mã nguồn LaTeX (do lỗi `HTTP 404` trên `/src/<id>v<n>` hoặc bản nộp chỉ có PDF) vẫn được giữ nguyên khóa phiên bản với ánh xạ rỗng (`"2": {}`) trong `hierarchy.json` và ghi rõ trạng thái tại `version_states`, bảo đảm không làm mất dấu lịch sử phiên bản thực tế của bài báo.

---

## 2.2. Thống kê & Hiệu năng Phân tích

*(Bảng số liệu và đồ thị phân tích sẽ được cập nhật tự động trong quá trình chạy dữ liệu chính thức).*
