# MASTER CHECKLIST VÀ HƯỚNG DẪN THỰC THI ĐỒ ÁN
**(ACTIONABLE ROADMAP & SUBMISSION CHECKLIST)**

---

## 1. PHÂN CÔNG TRÁCH NHIỆM: CÁ NHÂN VS NHÓM

| Hạng mục | Trách nhiệm | Chi tiết thực hiện |
|:---|:---|:---|
| **Dải arXiv ID** | **Cá nhân** | Mỗi bạn thực hiện thu thập và xử lý đúng khoảng ID được giao tại cột H - K trên sheet đăng ký. |
| **Kho mã nguồn chung** | **Nhóm** | Duy nhất 1 repository GitHub chung cho cả nhóm. Từng thành viên commit code tích lũy theo thời gian. |
| **Báo cáo Jupyter Book** | **Nhóm** | Duy nhất 1 repository riêng build ra GitHub Pages (`github.io`). **Đại diện nhóm** nộp link lên Moodle. |
| **Hugging Face Dataset** | **Cá nhân** | **Từng cá nhân tự upload dữ liệu của mình** lên tài khoản Hugging Face cá nhân và tự dán link nộp lên Moodle. |
| **Poster báo cáo** | **Nhóm** | File PowerPoint (`<ID nhóm>.pptx`) khổ A2 dọc. **Đại diện nhóm** nộp lên Moodle. Cả nhóm cùng in ấn và thuyết trình. |

---

## 2. CHECKLIST CHI TIẾT TỪNG MILESTONE

### Milestone 1: Data Crawling
- [ ] Kiểm tra chính xác dải arXiv ID được phân công trên Sheet đăng ký.
- [ ] Thiết lập môi trường Python (`requirements.txt`: `arxiv>=2.1.0`, `requests`, `pandas`, `sickle`, `tqdm`, ...).
- [ ] Cài đặt hàm thu thập metadata từ arXiv API hoặc OAI-PMH.
- [ ] Cài đặt hàm tải file nén nguồn từ endpoint `https://export.arxiv.org/src/{arxiv_id}`:
  - [ ] Bắt buộc duyệt qua tất cả các phiên bản `v1`, `v2`, ... (mặc định `v1` nếu nộp 1 lần).
  - [ ] Đặt giãn cách tối thiểu 3 giây giữa các request liên tiếp (`time.sleep(3)`).
  - [ ] Đính kèm header `User-Agent` rõ ràng.
  - [ ] Tuyệt đối **KHÔNG** cào trực tiếp từ domain `arxiv.org`.
- [ ] Cài đặt giải nén và **bộ lọc xóa toàn bộ file ảnh** (`.png`, `.jpg`, `.pdf`, `.eps`, ...); giữ nguyên mã LaTeX `figure`.
- [ ] Cài đặt truy vấn Semantic Scholar API để lấy danh sách trích dẫn và mã arXiv ID ngoại vi.
  - [ ] Xử lý rate limit (1 req/giây, mã lỗi 429 backoff).
  - [ ] Xử lý mã arXiv cũ trước 2007 (`archive/YYMMNNN`).
- [ ] Tổ chức lưu trữ cục bộ theo chuẩn thư mục `yymm-id/` chứa `metadata.json` và `references.json`.
- [ ] Chạy đo đạc benchmark (thời gian chạy, đỉnh RAM, dung lượng đĩa) trên Google Colab CPU.
- [ ] Xây dựng Chương 1 của Jupyter Book với bảng biểu và đồ thị sinh động bằng code khi build.

### Milestone 2: Hierarchical Parsing & Standardization
- [ ] Cài đặt module phát hiện file TeX gốc (`main.tex` chứa `\documentclass` và `\begin{document}`).
- [ ] Đệ quy nạp toàn bộ các file con được gọi qua `\input`, `\include`, `\subfile`; bỏ qua file rác.
- [ ] Dựng cây phân cấp tài liệu (Document $\rightarrow$ Sections $\rightarrow$ Subsections $\rightarrow$ Paragraphs $\rightarrow$ Items).
- [ ] Bóc tách nút lá đạt 3 dạng chuẩn:
  - [ ] Câu văn thông thường (Sentence) kết thúc bằng dấu chấm (loại trừ từ viết tắt).
  - [ ] Khối công thức toán học (Block Formula: `equation`, `align`, `$$...$$`).
  - [ ] Khối hình ảnh và bảng biểu (Figure & Table).
- [ ] Loại bỏ khối References (`thebibliography`, `bibliography`) khỏi cây phân cấp.
- [ ] Giữ lại đầy đủ Lời cảm ơn (Acknowledgements) và Phụ lục (Appendices).
- [ ] Làm sạch định dạng LaTeX dư thừa (`\centering`, `[htpb]`, `\midrule`, ...).
- [ ] Chuẩn hóa toán học: Inline về `$...$`, Block về `\begin{equation}...\end{equation}`.
- [ ] Bóc tách `\bibitem` thành cấu trúc BibTeX chuẩn bằng Regex.
- [ ] Thực hiện Khử trùng lặp Cấp 1 (Reference Deduplication): hợp nhất các citation key trùng lặp, đồng bộ lại lệnh `\cite{}` trong cây phân cấp, hợp nhất tất cả các trường dữ liệu.
- [ ] Thực hiện Khử trùng lặp Cấp 2 (Full-text Content Deduplication): so khớp chuỗi toàn văn sau khi làm sạch xuyên suốt các phiên bản `v1`, `v2`, ... để gán chung một ID phần tử duy nhất.
- [ ] Xuất ra 2 file chuẩn cho mỗi bài báo: `hierarchy.json` và `refs.bib`.
- [ ] Đo đạc benchmark trên Colab CPU và viết tiếp Chương 2 vào Jupyter Book.
- [ ] Đại diện nhóm nộp link GitHub Pages của Jupyter Book lên Moodle.

### Milestone 3: Machine Learning Pipeline, Dataset & Poster
- [ ] Tiền xử lý và làm sạch chuỗi (lowercasing, stop-words, normalize author names).
- [ ] Sinh không gian ứng viên $m \times n$ cặp ghép cho từng bài báo.
- [ ] Xây dựng Ground Truth:
  - [ ] Gán nhãn thủ công $\ge 5$ bài báo, tổng $\ge 20$ cặp khớp chuẩn.
  - [ ] Gán nhãn tự động bằng heuristics/regex cho $\ge 10\%$ số bài báo còn lại.
- [ ] Trích xuất đặc trưng (Feature Engineering):
  - [ ] Đặc trưng tương đồng tiêu đề (Levenshtein, Jaro-Winkler, Jaccard, TF-IDF cosine).
  - [ ] Đặc trưng tác giả (trùng tác giả 1, Jaccard danh sách tác giả).
  - [ ] Đặc trưng thời gian (khoảng cách năm, trùng năm).
  - [ ] Đặc trưng phân cấp tài liệu (vị trí xuất hiện của citation trong cây M2).
  - [ ] Vẽ đồ thị phân tích và viết lý giải cho từng đặc trưng.
- [ ] Chia tập Train / Valid / Test theo ĐƠN VỊ BÀI BÁO (Test: 1 manual + 1 auto; Valid: 1 manual + 1 auto; Train: các bài còn lại).
- [ ] Huấn luyện mô hình xếp hạng, dự đoán Top-5 ứng viên (`cand_1` đến `cand_5`).
- [ ] Đánh giá mô hình bằng độ đo Mean Reciprocal Rank (MRR).
- [ ] Chuyển đổi toàn bộ dữ liệu dự án thành 7 bảng Parquet:
  - [ ] `papers.parquet`
  - [ ] `elements.parquet`
  - [ ] `element_parents.parquet`
  - [ ] `bibtex_entries.parquet`
  - [ ] `paper_references.parquet`
  - [ ] `predictions.parquet`
  - [ ] `sources.parquet`
- [ ] Soạn thảo file `README.md` với YAML Dataset Card cho Hugging Face repo.
- [ ] **Mỗi cá nhân upload dataset cá nhân lên Hugging Face và dán link public vào Moodle.**
- [ ] Thiết kế poster 1 trang trên PowerPoint:
  - [ ] Kích thước chuẩn: **Portrait A2 (42.0 cm $\times$ 59.4 cm)**.
  - [ ] Đặt tên file: `<ID nhóm>.pptx`.
  - [ ] Đại diện nhóm nộp file PPTX lên Moodle.
- [ ] In poster khổ A2 và chuẩn bị nội dung thuyết trình tại buổi Poster Session.

---

## 3. KIẾN TRÚC MÃ NGUỒN ĐỀ XUẤT TRONG REPO CHUNG

Nhằm thuận tiện cho việc lập trình cặp (pair programming) và chia module trong nhóm, cấu trúc thư mục code nên được bố trí như sau:

```text
Prj/
├── docs/                       # Toàn bộ tài liệu context và hướng dẫn
│   ├── PROJECT_OVERVIEW.md
│   ├── MILESTONE_1_CRAWLING.md
│   ├── MILESTONE_2_PARSING.md
│   ├── MILESTONE_3_MATCHING_AND_SUBMISSION.md
│   └── CHECKLIST_AND_DELIVERABLES.md
├── src/                        # Thư mục mã nguồn chính (sẽ commit lên group-repo)
│   ├── crawling/               # Module M1: Crawling & Semantic Scholar
│   │   ├── arxiv_scraper.py
│   │   ├── s2_client.py
│   │   └── figure_filter.py
│   ├── parsing/                # Module M2: LaTeX parsing, hierarchy, normalization
│   │   ├── tex_extractor.py
│   │   ├── hierarchy_builder.py
│   │   ├── cleaner.py
│   │   └── deduplicator.py
│   ├── matching/               # Module M3: ML Pipeline ghép nối trích dẫn
│   │   ├── labeling.py
│   │   ├── feature_engineering.py
│   │   ├── models.py
│   │   └── evaluation.py
│   ├── export/                 # Module đóng gói 7 bảng Parquet & HF upload
│   │   └── parquet_builder.py
│   └── utils/                  # Các hàm tiện ích dùng chung
│       └── benchmark.py
├── data/                       # Dữ liệu cục bộ (Thư mục này được đưa vào .gitignore)
│   ├── raw/                    # Dữ liệu M1
│   ├── processed/              # Dữ liệu M2
│   └── parquet/                # Dữ liệu M3
├── notebooks/                  # Notebooks phục vụ thử nghiệm và Colab CPU benchmark
│   ├── m1_crawling_demo.ipynb
│   ├── m2_parsing_demo.ipynb
│   └── m3_matching_experiments.ipynb
├── .gitignore                  # Bỏ qua data/, __pycache__/, .env
├── requirements.txt            # Danh sách thư viện cần thiết
└── README.md                   # Hướng dẫn cài đặt và chạy hệ thống
```
