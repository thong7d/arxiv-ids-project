# MILESTONE 2: PHÂN TÍCH CÚ PHÁP PHÂN CẤP VÀ CHUẨN HÓA DỮ LIỆU
**(HIERARCHICAL PARSING AND STANDARDIZATION)**
**Tài liệu đặc tả chi tiết & Hướng dẫn kỹ thuật thực hiện**

---

## 1. MỤC TIÊU VÀ NHIỆM VỤ CỦA MILESTONE 2

Chuyển đổi dữ liệu thô (mã nguồn LaTeX của M1) thành cấu trúc dữ liệu bán cấu trúc có phân cấp, được làm sạch, chuẩn hóa và khử trùng lặp:
1. **Multi-file Gathering:** Xác định luồng biên dịch chính (main compilation path) và dựng cây nhúng file qua `\input`, `\include`. Bỏ qua file rác không được biên dịch.
2. **Hierarchy Construction:** Xây dựng cây phân cấp tài liệu (Document Tree Hierarchy) cho từng phiên bản (`v1`, `v2`, ...).
3. **Phân cấp phần tử:**
   - Nút gốc: Tài liệu (Document).
   - Nút trung gian: Chương (Chapter), Mục (Section), Tiểu mục (Subsection), Đoạn văn (Paragraph), Danh sách (`itemize`/`enumerate`).
   - Nút lá (Smallest Elements): Câu văn (Sentence), Công thức khối (Block Formula), Hình ảnh/Bảng biểu (Figure/Table).
   - **Bỏ qua phần Tài liệu tham khảo** (`\bibliography`, `thebibliography`).
   - **Bắt buộc giữ lại Lời cảm ơn (Acknowledgements) và Phụ lục (Appendices).**
4. **Chuẩn hóa & Làm sạch (Standardization & Cleanup):**
   - Loại bỏ các lệnh định dạng thừa (`\centering`, `\midrule`, `[htpb]`, ...).
   - Chuẩn hóa toán học: Inline math về dạng `$...$`, Block math về dạng `\begin{equation}...\end{equation}`.
   - Bóc tách và chuyển đổi `\bibitem` thành cấu trúc chuẩn BibTeX.
5. **Khử trùng lặp 2 cấp độ (Two-level Deduplication):**
   - **Cấp độ trích dẫn (References):** Gộp các citation key trùng lặp, đồng bộ lại lệnh `\cite{}` trong văn bản, hợp nhất thông tin các trường (Field Unionization).
   - **Cấp độ nội dung (Full-text Content):** Gán cùng 1 ID cho các phần tử có nội dung trùng khớp hoàn toàn qua các phiên bản (thực hiện sau khi đã làm sạch text).
6. **Đầu ra mỗi bài báo:** Tạo 2 tệp `hierarchy.json` và `refs.bib`.
7. **Báo cáo Jupyter Book:** Biên soạn Chương 2 của sách chung.

---

## 2. QUY TRÌNH XỬ LÝ (PIPELINE ARCHITECTURE)

```mermaid
flowchart TD
    SrcDir[Thư mục mã nguồn bài báo /vX/] --> FindMain[1. Quét tìm Main TeX: có documentclass & begin document]
    FindMain --> ResolveInputs[2. Đệ quy resolve \input và \include]
    ResolveInputs --> ParseAST[3. Phân tích cấu trúc phân cấp: Sec/Subsec/Par/Items]
    
    subgraph Leaf Extraction & Normalization
        ParseAST --> SplitSentences[Tách câu kết thúc bằng dấu chấm .]
        ParseAST --> ExtractMath[Chuẩn hóa toán: Inline $...$ & Block equation]
        ParseAST --> ExtractFigures[Bóc tách Figures và Tables]
        ParseAST --> StripNoise[Lọc bỏ lệnh định dạng không mang ngữ nghĩa]
    end

    subgraph References & BibTeX Pipeline
        SrcDir --> ParseBib[4. Bóc tách file .bib và khối thebibliography]
        ParseBib --> BibitemToBibtex[Regex convert \bibitem -> BibTeX]
        BibitemToBibtex --> MergeBib[5. Deduplicate References: Merge keys & Union fields]
        MergeBib --> UpdateCiteKeys[Đồng bộ lại \cite{key} trong nội dung cây phân cấp]
    end

    StripFigures & StripNoise & UpdateCiteKeys --> DedupText[6. Full-text Deduplication xuyên các phiên bản v1, v2]
    DedupText --> GenHierarchy[Xuất file hierarchy.json]
    MergeBib --> GenBib[Xuất file refs.bib]
```

---

## 3. CHI TIẾT CÁC QUY TẮC PHÂN TÍCH CÚ PHÁP (PARSING RULES)

### 3.1. Tìm kiếm file chính (Main Compilation Path)
- Nhiều bài báo tách thành nhiều file: `main.tex`, `intro.tex`, `methods.tex`, `macros.tex`.
- **Dấu hiệu nhận biết file gốc:** Chứa thẻ `\documentclass{...}` và khối `\begin{document}...\end{document}`.
- Lần theo các lệnh:
  - `\input{filename}` (có hoặc không có đuôi `.tex`).
  - `\include{filename}`.
  - `\subfile{filename}`.
- **Quy tắc:** Chỉ nạp các file nằm trong cây gọi của file chính. Các file nháp mồ côi (orphan `.tex` files) trong thư mục tuyệt đối không được đưa vào cây phân tích.

### 3.2. Cấu trúc cây phân cấp (Hierarchy Tree Levels)
1. **Gốc (Root):** Toàn bộ tài liệu (`root-document-id`).
2. **Cấp 1 / 2:** Các chương/mục lớn (`\chapter`, `\section`).
3. **Cấp sâu hơn:** `\subsection`, `\subsubsection`, `\paragraph`.
4. **Môi trường danh sách liệt kê (`itemize`, `enumerate`):**
   - Khối `\begin{itemize}` đóng vai trò là phần tử cha (higher component).
   - Mỗi điểm liệt kê `\item` là một phần tử con ở cấp tiếp theo.

### 3.3. Quy định về nút lá (Smallest Leaf Elements)
Các nút tận cùng của cây phân cấp bắt buộc phải là 1 trong 3 loại:
1. **Câu văn (Sentences):** Văn bản thông thường được phân tách thành từng câu bởi dấu chấm kết thúc câu (`.`), có tính đến việc tránh tách nhầm tại các chữ viết tắt phổ biến (như `e.g.`, `i.e.`, `et al.`, `Fig.`, `Eq.`).
2. **Công thức toán dạng khối (Block Formulas):** Toàn bộ nội dung nằm trong `\begin{equation}...\end{equation}`, `\begin{align}...\end{align}`, `\begin{gather}...\end{gather}`, hoặc cặp `$$...$$`.
3. **Hình ảnh và Bảng biểu (Figures & Tables):** Toàn bộ khối `\begin{figure}...\end{figure}` và `\begin{table}...\end{table}`. (Đề bài quy định rõ: Table cũng được xem là một dạng Figure ở bước này).

### 3.4. Danh mục loại trừ và bắt buộc bao gồm (Exclusions & Inclusions)
- ❌ **LOẠI TRỪ:** Phần Tài liệu tham khảo (`\begin{thebibliography}...\end{thebibliography}` hoặc lệnh gọi `\bibliography{...}`) **KHÔNG** được đưa vào cây phân cấp `hierarchy.json`. Phần này được xử lý độc lập sang file `refs.bib`.
- ✅ **BẮT BUỘC BAO GỒM:** Lời cảm ơn (Acknowledgements) và Phụ lục (Appendices) — kể cả khi chúng được đặt bằng lệnh không đánh số `\section*{Acknowledgements}` hoặc `\appendix`.

---

## 4. CHUẨN HÓA VÀ LÀM SẠCH (STANDARDIZATION)

### 4.1. Dọn dẹp mã LaTeX (LaTeX Cleanup)
Loại bỏ triệt để các thẻ điều khiển định dạng giao diện không mang ý nghĩa ngữ nghĩa nội dung:
- Căn lề và khoảng cách: `\centering`, `\raggedright`, `\vspace{...}`, `\hspace{...}`, `\newpage`, `\clearpage`.
- Tham số bố cục: `[htpb]`, `[!t]`, `[width=\linewidth]`.
- Đường kẻ bảng: `\toprule`, `\midrule`, `\bottomrule`, `\hline`.
- Trang trí font không cần thiết khi trích xuất text thuần (giữ lại ngữ nghĩa text bên trong nếu có).

### 4.2. Chuẩn hóa công thức toán (Math Normalization)
- **Inline Math (toán nội dòng):** Tất cả các cách viết khác nhau (như `\( x+y \)` hoặc `\ensuremath{x+y}`) phải được chuyển đổi đồng nhất về dạng:
  ```latex
  $x+y$
  ```
- **Block Math (toán dạng khối):** Tất cả các cách viết dạng khối (`$$...$$`, `\[...\]`, `align`, `gather`) phải được chuyển đổi đồng nhất về định dạng chuẩn:
  ```latex
  \begin{equation}
  ...
  \end{equation}
  ```

### 4.3. Chuyển đổi `\bibitem` thành BibTeX
- Nếu bài báo không có sẵn file `.bib` mà định nghĩa trích dẫn bằng khối `\bibitem{key} Author, "Title", Year...` trong file `.tex`:
  - Dùng Regular Expressions để bóc tách: Citation Key, Tác giả, Tiêu đề bài báo, Năm xuất bản, Tạp chí/Hội nghị.
  - Chuyển đổi thành cấu trúc BibTeX chuẩn:
    ```bibtex
    @article{key,
      author = {Author Name},
      title = {Title of Paper},
      year = {2021},
      journal = {Journal Name}
    }
    ```

---

## 5. CƠ CHẾ KHỬ TRÙNG LẶP 2 CẤP ĐỘ (TWO-LEVEL DEDUPLICATION)

### 5.1. Cấp độ 1: Khử trùng lặp Trích dẫn (Reference Deduplication)
- **Bối cảnh:** Giữa các phiên bản (`v1`, `v2`, ...) hoặc bên trong cùng một phiên bản, có thể có nhiều mục trích dẫn trỏ đến cùng một tài liệu gốc nhưng mang key khác nhau (ví dụ: `vaswani2017attention` và `attention_nips`).
- **Xử lý:**
  1. Phát hiện trùng lặp dựa trên so khớp tiêu đề (`title`) và tác giả (`author`).
  2. Chọn ra **MỘT** citation key duy nhất đại diện.
  3. Cập nhật lại toàn bộ các lệnh trích dẫn trong văn bản (ví dụ: đổi `\cite{attention_nips}` thành `\cite{vaswani2017attention}`).
  4. **Hợp nhất trường dữ liệu (Field Unionization):** Nếu entry A có `year, journal` nhưng thiếu `doi`, còn entry B có `doi`, entry đại diện cuối cùng phải chứa hợp tất cả các trường: `author, title, year, journal, doi`. Tuyệt đối không chọn 1 bản ghi và vứt bỏ bản ghi kia.

### 5.2. Cấp độ 2: Khử trùng lặp Nội dung Toàn văn (Full-text Content Deduplication)
- **Bối cảnh:** Khi một bài báo cập nhật từ `v1` lên `v2`, đa số các câu văn hoặc đoạn văn không hề thay đổi.
- **Xử lý:**
  1. Việc so khớp nội dung (Full-text match) phải được thực hiện **SAU KHI ĐÃ LÀM SẠCH (after cleanup)** để loại bỏ sai lệch do khoảng trắng hoặc định dạng.
  2. Nếu một phần tử văn bản (leaf sentence hoặc component) ở `v2` giống hệt nội dung ở `v1`, phần tử này được gán **cùng một ID duy nhất** trong từ điển `elements`.
  3. Cây `hierarchy` của từng phiên bản sẽ trỏ đến cùng `element_id` này, loại bỏ hoàn toàn sự dư thừa dữ liệu.

---

## 6. ĐẶC TẢ ĐỊNH DẠNG ĐẦU RA CỦA MILESTONE 2

Mỗi bài báo trong corpus tạo ra 2 tệp đầu ra thay thế cho thư mục mã nguồn thô:

### 6.1. Tệp `hierarchy.json`
```json
{
  "elements": {
    "2310-12345-sec-1": "Introduction",
    "2310-12345-sent-1": "Deep learning has revolutionized artificial intelligence.",
    "2310-12345-eq-1": "\\begin{equation}\nE = mc^2\n\\end{equation}"
  },
  "hierarchy": {
    "1": {
      "2310-12345-sec-1": "2310-12345-root",
      "2310-12345-sent-1": "2310-12345-sec-1",
      "2310-12345-eq-1": "2310-12345-sec-1"
    },
    "2": {
      "2310-12345-sec-1": "2310-12345-root",
      "2310-12345-sent-1": "2310-12345-sec-1",
      "2310-12345-sent-new": "2310-12345-sec-1"
    }
  }
}
```

> **Quy ước đặt tên ID (`element_id`):**
> ID của phần tử bắt buộc phải chứa tiền tố là ID bài báo (`arXiv ID` hoặc `Semantic Scholar ID`) để phân biệt giữa các bài báo khác nhau, phần đuôi thể hiện tính định danh duy nhất bên trong bài báo (ví dụ: `2310-12345-elem-0042`).

### 6.2. Tệp `refs.bib`
Chứa toàn bộ các mục BibTeX đã được hợp nhất, dọn sạch và khử trùng lặp của bài báo đó:
```bibtex
@article{2310-12345-vaswani2017attention,
  author = {Ashish Vaswani and Noam Shazeer and Niki Parmar},
  title = {Attention Is All You Need},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  volume = {30}
}
```

---

## 7. YÊU CẦU BÁO CÁO JUPYTER BOOK CHO MILESTONE 2

Biên soạn thêm **Chương 2** vào cùng Jupyter Book đã nộp ở Milestone 1.

### 7.1. Trình bày Giải thuật & Kỹ thuật
- Cơ chế phát hiện luồng biên dịch chính và giải quyết cây liên kết đa file.
- Logic phân tích cây phân cấp từ mã nguồn LaTeX.
- Quy trình làm sạch, chuẩn hóa toán học và bóc tách `\bibitem`.
- Giải thuật khử trùng lặp 2 cấp độ.

### 7.2. Báo cáo Thống kê Xử lý
- Tỷ lệ phân tích cú pháp thành công trên toàn bộ kho bài báo.
- Số lượng phần tử trung bình của cây tài liệu trên mỗi bài.
- Tổng số phần tử văn bản trước và sau khi khử trùng lặp (tính tỷ lệ giảm thiểu % redundancy).
- Số lượng mục trích dẫn BibTeX trước và sau khi khử trùng lặp.

### 7.3. Phân tích Hiệu năng (Google Colab CPU)
- Thời gian chạy đo đạc từ đầu đến cuối (End-to-end Wall Time).
- Thời gian xử lý trung bình trên 1 bài báo (giây/bài).
- Bộ nhớ RAM tiêu thụ tối đa (Peak RAM).
- Kích thước lưu trữ dữ liệu đầu ra (`hierarchy.json` và `refs.bib`).

---

## 8. TIÊU CHÍ ĐÁNH GIÁ (GRADING RUBRIC)
- **Hierarchical Parser:** Độ chính xác trong phát hiện file chính, dựng cấu trúc cây chuẩn theo từng cấp bậc.
- **Standardization & Deduplication:** Làm sạch triệt để mã LaTeX, chuẩn hóa toán học, khử trùng lặp chính xác cả ở cấp trích dẫn (đồng bộ `\cite`) và cấp toàn văn.
- **Parser's Performance:** Tối ưu tốc độ xử lý, tiết kiệm RAM trên Colab CPU.
- **Code Quality & Reproducibility:** Code viết theo module, clean code, dễ bảo trì.
- **Report (Jupyter Book):** Báo cáo trực quan, biểu đồ sinh tự động khi build, lập luận chặt chẽ.
