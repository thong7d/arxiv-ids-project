# HƯỚNG DẪN CHI TIẾT DÀNH CHO THÀNH VIÊN NHÓM 13
**(TỪ THIẾT LẬP BAN ĐẦU ĐẾN HOÀN THÀNH PHASE 2 — CRAWLING)**

Tài liệu này hướng dẫn chi tiết từng bước cho **Nguyễn Tiến Thành** và **Nguyễn Trịnh Quang** (hoặc bất kỳ thành viên nào tham gia dự án) từ lúc clone repository đến khi chạy hoàn thành Phase 2 (thu thập dữ liệu thô và kiểm định dữ liệu).

---

## 📌 PHẦN 1: DẢI ID BÀI BÁO VÀ PHÂN CÔNG TRÁCH NHIỆM

Theo phân công trên Google Sheet và cấu hình tại `configs/members.csv`:

| Thành viên | MSSV | Dải arXiv ID phân công | Vai trò chính |
|:---|:---:|:---|:---|
| **Phạm Minh Thông** | 23120364 | `2508.17872` → `2509.01046` | Lead, Crawler, Benchmark, Jupyter Book deploy |
| **Nguyễn Tiến Thành** | 23120358 | `2509.01047` → `2509.06046` | Owner Parser M2, Chuẩn hóa, Khử trùng lặp |
| **Nguyễn Trịnh Quang** | 23120345 | `2509.06047` → `2509.11046` | Owner Labeling M3, Trích đặc trưng, Mô hình ML |

> **Nguyên tắc cốt lõi:**
> 1. Dùng chung 1 codebase duy nhất tại repo: `thong7d/arxiv-ids-project`.
> 2. Dữ liệu thô và dữ liệu Parquet tuyệt đối **KHÔNG commit lên Git** (đã được cấu hình tự động trong `.gitignore`).
> 3. Cuối kỳ, mỗi bạn sẽ xuất 7 bảng Parquet **chỉ chứa các bài báo trong dải ID của riêng mình** để nộp lên Hugging Face cá nhân.

---

## 🛠️ PHẦN 2: THIẾT LẬP MÔI TRƯỜNG TỪ ĐẦU (STEP-BY-STEP)

### Bước 2.1: Clone repository và tạo nhánh làm việc riêng
Mở PowerShell hoặc Terminal trên máy tính của bạn:

```powershell
# 1. Clone repository
git clone https://github.com/thong7d/arxiv-ids-project.git
cd arxiv-ids-project

# 2. Tạo nhánh tính năng riêng theo phân công
# Nếu là Thành:
git checkout -b feature/m2-parsing

# Nếu là Quang:
git checkout -b feature/m3-matching
```

---

### Bước 2.2: Cài đặt Python 3.11 và môi trường ảo (.venv)

Khuyên dùng công cụ **`uv`** (cực nhanh, tự động cài Python 3.11 nếu máy chưa có):

```powershell
# Cách 1: Sử dụng uv (Khuyên dùng)
uv venv --python 3.11 .venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -e .

# Cách 2: Sử dụng python venv thông thường (yêu cầu máy có sẵn Python >= 3.11)
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

---

### Bước 2.3: Thiết lập API Key & Biến môi trường
Copy file `.env.example` thành `.env` trên máy cá nhân:
```powershell
copy .env.example .env
```
Mở file `.env` và điền:
- `SEMANTIC_SCHOLAR_API_KEY`: Đăng ký tài khoản và lấy key miễn phí tại [Semantic Scholar API](https://www.semanticscholar.org/product/api) để có tốc độ ổn định 1 req/giây không bị giới hạn IP. *(Nếu chưa được cấp key ngay, hệ thống vẫn chạy bình thường ở chế độ anonymous an toàn).*
- `HF_TOKEN`: Vào [Hugging Face Settings -> Tokens](https://huggingface.co/settings/tokens) tạo 1 Write Token để sẵn sàng upload dataset cá nhân ở Phase 7.
- `ARXIV_CONTACT_EMAIL`: Điền email sinh viên của bạn.

---

### Bước 2.4: Chạy kiểm thử xác nhận môi trường hoạt động tốt
Chạy lệnh sau để đảm bảo 100% schemas và tests nền tảng đã chạy sạch:
```powershell
pytest tests/
```
**Kỳ vọng:** Terminal báo xanh `19 passed`!

---

## 🔍 PHẦN 3: KHÁM PHÁ DẢI ID & SINH MANIFEST (PHASE 1)

Để nạp dải ID của 3 thành viên, kiểm tra chống overlap và sinh danh sách công việc:

```powershell
python -m ids_arxiv discover
```
**Kết quả:**
- Hiển thị bảng dải ID của Thông, Thành, Quang.
- Tạo file manifest tổng hợp `data/manifests/papers.parquet` với hơn 11.000 bài báo được phân bổ rõ ràng theo `owner_student_id`.

---

## 📥 PHẦN 4: CHẠY THU THẬP DỮ LIỆU (PHASE 2 — CRAWLING)

Hệ thống crawler đã được tích hợp sẵn các tiêu chuẩn kỹ thuật:
- **Nghi thức arXiv API an toàn:** Tự động giãn cách 3 giây giữa các request, không lo bị chặn IP.
- **Tự động tải đa phiên bản:** Tải trọn vẹn `v1, v2, ...` qua mirror `export.arxiv.org`.
- **Tự động lọc ảnh nhị phân (Figure Stripping):** Sau khi giải nén, tự động xóa sạch các file `.png, .jpg, .pdf, .eps`, giúp giảm **95% - 98% dung lượng đĩa** mà vẫn giữ nguyên mã nguồn LaTeX `figure`.
- **Checkpoint & Resume:** Nếu đang chạy mà bị mất mạng hoặc tắt máy, bạn chỉ cần gõ lại lệnh; hệ thống sẽ bỏ qua các bài đã xong và chạy tiếp tục.

### 4.1. Chạy thử nghiệm Pilot 10 bài theo dải cá nhân (Khuyên làm trước)
Mỗi thành viên gõ đúng lệnh theo MSSV của mình để cào thử 10 bài đầu tiên trong dải được cấp:

- **Nếu bạn là Thông (23120364):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120364 --pilot --output data/raw --resume
  ```
- **Nếu bạn là Thành (23120358):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120358 --pilot --output data/raw --resume
  ```
- **Nếu bạn là Quang (23120345):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120345 --pilot --output data/raw --resume
  ```

*(Hoặc nếu muốn chạy thử nghiệm đại diện cho cả 3 thành viên: `python -m ids_arxiv crawl --pilot` sẽ tự động lấy 10 bài của mỗi người = 30 bài).*

### 4.2. Chạy thu thập dữ liệu đầy đủ cho dải cá nhân
Khi đã quen thuộc với cấu trúc dữ liệu và muốn cào toàn bộ dải bài được giao:

- **Dành cho Thông (3.175 bài: `2508.17872` → `2509.01046`):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120364 --output data/raw --resume
  ```
- **Dành cho Thành (5.000 bài: `2509.01047` → `2509.06046`):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120358 --output data/raw --resume
  ```
- **Dành cho Quang (5.000 bài: `2509.06047` → `2509.11046`):**
  ```powershell
  python -m ids_arxiv crawl --student-id 23120345 --output data/raw --resume
  ```

> 💡 **Mẹo tăng tốc & không tốn tài nguyên máy cá nhân:** Bạn có thể chạy lệnh trên trên Google Colab CPU bằng cách clone repo vào Colab, kết nối Google Drive và chạy ngầm qua đêm. Cơ chế resume sẽ tự động tải tiếp nếu session bị ngắt.

### 4.3. Cấu trúc thư mục dữ liệu sau khi cào xong
Mỗi bài báo sẽ nằm trong một thư mục chuẩn tại `data/raw/<yymm-id>/`:
```text
data/raw/
└── 2508-17872/
    ├── v1/
    │   ├── main.tex
    │   ├── ref.bib
    │   └── IEEEtran.cls
    ├── metadata.json       # Tiêu đề, tác giả, ngày submit, ngày sửa đổi
    ├── references.json     # Trích dẫn ngoài lấy từ Semantic Scholar API
    └── crawl_status.json   # Trạng thái tải, kích thước trước/sau lọc ảnh
```

---

## ✅ PHẦN 5: KIỂM ĐỊNH TÍNH TOÀN VẸN DỮ LIỆU (DATA VALIDATION)

Sau khi chạy xong crawler (dù là chạy pilot hay chạy full), bạn bắt buộc phải chạy lệnh kiểm định để đảm bảo dữ liệu tuân thủ 100% quy định của giảng viên:

```powershell
python -m ids_arxiv validate --stage raw --path data/raw
```

**Tiêu chuẩn đạt:**
- [x] Tất cả các thư mục bài báo đều báo `[OK] <id>: valid`.
- [x] Không có bất kỳ file ảnh nhị phân nào còn sót lại trong các thư mục `v1/`, `v2/`.
- [x] File `metadata.json` và `references.json` đúng chuẩn schema Pydantic.

---

## 🎯 PHẦN 6: CÔNG VIỆC TIẾP THEO CHO TỪNG THÀNH VIÊN

Sau khi đã hoàn thành các bước trên và có dữ liệu thô:

### Dành cho Thành (Phụ trách Phase 3 — Milestone 2: Parsing):
- Mở xem cấu trúc bài báo mẫu tại [tests/fixtures/synthetic_paper/](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/tests/fixtures/synthetic_paper/).
- Nhiệm vụ tiếp theo: Xây dựng module parser tại `src/ids_arxiv/parser/` để:
  1. Đệ quy tìm file TeX chính (`\documentclass`), lần theo `\input` và `\include`.
  2. Bóc tách cây phân cấp tài liệu (`hierarchy.json`) và bóc tách `\bibitem` thành BibTeX (`refs.bib`).
  3. Khử trùng lặp nội dung toàn văn giữa các phiên bản.

### Dành cho Quang (Phụ trách Phase 5 — Milestone 3: Labeling & ML):
- Nhiệm vụ tiếp theo:
  1. Chọn ra **6 bài báo** trong dải ID của mình (5 bài chính thức + 1 dự phòng) có chứa trích dẫn để gán nhãn thủ công (Manual Labeling) $\ge 20$ cặp khớp chuẩn.
  2. Thiết kế các luật gán nhãn tự động bằng heuristic/regex ($\ge 10\%$ số bài báo).
  3. Chuẩn bị đặc tả các nhóm đặc trưng (title similarity, author match, year diff) cho mô hình xếp hạng Top-5 ứng viên.

### Dành cho Thông (Lead):
- Chạy mở rộng crawler cho dải ID và đo đạc benchmark (thời gian, RAM) trên Google Colab CPU để đưa số liệu vào Chương 1 của [book/ch1_crawling.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/book/ch1_crawling.md).
