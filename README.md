# Đồ án Nhập môn Khoa học Dữ liệu – Nhóm 13 (FIT - HCMUS)
**Chủ đề:** arXiv Project — Thu thập mã nguồn LaTeX, Phân tích cú pháp phân cấp và Pipeline Machine Learning Ghép nối trích dẫn

---

## 📌 Tổng quan Pipeline Kiến trúc Hệ thống

Dự án xây dựng một pipeline xử lý dữ liệu học thuật tái lập hoàn chỉnh từ đầu đến cuối:
```text
arXiv ID (15.000 bài)
  └── Crawl toàn bộ phiên bản (v1...vN) qua export.arxiv.org + Lọc ảnh
      └── Thu thập Metadata & References qua Semantic Scholar API
          └── Phân tích cây phân cấp LaTeX (Document Tree Hierarchy)
              └── Chuẩn hóa toán học & Khử trùng lặp 2 cấp độ (Full-text & BibTeX)
                  └── Pipeline ML ghép nối trích dẫn (Entity Resolution, MRR)
                      ├── 7 Bảng Sharded Parquet chuẩn Hugging Face
                      ├── Báo cáo trực quan tương tác Jupyter Book
                      └── Poster thuyết trình khổ A2 dọc
```

---

## ⚙️ Hướng dẫn Cài đặt Môi trường (Windows & Linux/Colab)

### 1. Yêu cầu Tiên quyết
- **Python:** Phiên bản `>= 3.11` (khuyên dùng công cụ `uv` để cài đặt nhanh nhất).
- **Git** đã cài đặt trên máy.

### 2. Thiết lập Môi trường Ảo & Cài đặt Thư viện
```powershell
# Cách 1: Sử dụng uv (Khuyên dùng - tốc độ cài đặt cực nhanh)
uv venv --python 3.11 .venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -e .

# Cách 2: Sử dụng python venv tiêu chuẩn
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### 3. Cấu hình Biến Môi trường
Copy file mẫu `.env.example` thành `.env` và điền các API token cá nhân:
```powershell
cp .env.example .env
```
- `SEMANTIC_SCHOLAR_API_KEY`: API key Semantic Scholar (tùy chọn, nếu chưa có hệ thống tự động chạy chế độ rate limit an toàn 1 req/s).
- `HF_TOKEN`: Hugging Face write token cá nhân để tải dataset.
- `ARXIV_CONTACT_EMAIL`: Email liên hệ trong `User-Agent` tuân thủ quy tắc arXiv API.

---

## 🚀 Hướng dẫn Sử dụng CLI (`ids-arxiv`)

Pipeline hỗ trợ giao diện dòng lệnh độc lập, có cơ chế checkpoint và resume:

```powershell
# 1. Khám phá dải ID, kiểm tra không chồng lấn và sinh manifest
python -m ids_arxiv discover --config configs/members.csv

# 2. Thu thập dữ liệu thô (Milestone 1)
python -m ids_arxiv crawl --manifest data/manifests/papers.parquet --resume

# 3. Phân tích phân cấp & chuẩn hóa LaTeX (Milestone 2)
python -m ids_arxiv parse --input data/raw --output data/processed --resume

# 4. Gán nhãn trích dẫn (Milestone 3)
python -m ids_arxiv label --input data/processed

# 5. Huấn luyện mô hình so khớp & đánh giá MRR (Milestone 3)
python -m ids_arxiv train --config configs/model.yaml

# 6. Kiểm định tính toàn vẹn dữ liệu
python -m ids_arxiv validate --stage raw
python -m ids_arxiv validate --stage processed
python -m ids_arxiv validate --stage hf --student-id 23120364

# 7. Xuất 7 bảng Parquet theo dải ID cá nhân
python -m ids_arxiv export --student-id 23120364 --output exports/
```

---

## 📚 Tài liệu Đặc tả Chi tiết

Toàn bộ tài liệu phân tích kỹ thuật và logic thuật toán được lưu trữ trong thư mục [`docs/`](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/):
- **[PROJECT_OVERVIEW.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/PROJECT_OVERVIEW.md)**: Tổng quan kiến trúc đồ án và luồng xử lý.
- **[MILESTONE_1_CRAWLING.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_1_CRAWLING.md)**: Đặc tả kỹ thuật crawler, version discovery, figure filter và benchmark Colab CPU.
- **[MILESTONE_2_PARSING.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_2_PARSING.md)**: Giải thuật phân tích cú pháp đa file, hierarchy tree và 2 cấp độ khử trùng lặp.
- **[MILESTONE_3_MATCHING_AND_SUBMISSION.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_3_MATCHING_AND_SUBMISSION.md)**: Pipeline ML ghép nối trích dẫn, schema 7 bảng Parquet và Poster.
- **[PLAN.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/PLAN.md)**: Kế hoạch triển khai chi tiết 8 Phase của Nhóm 13.
