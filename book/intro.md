# Đồ án Nhập môn Khoa học Dữ liệu – Nhóm 13

**Chủ đề:** arXiv Project — Thu thập, Tiền xử lý phân cấp dữ liệu LaTeX & Pipeline Machine Learning Ghép nối Trích dẫn  
**Giảng viên hướng dẫn:** Bộ môn Khoa học Dữ liệu – Khoa CNTT, Trường ĐH Khoa học Tự nhiên, ĐHQG-HCM

---

## 1. Giới thiệu Nhóm và Phạm vi Dữ liệu

| Thành viên | Phân nhóm | Vai trò chính | Dải arXiv ID phân công |
|:---|:---:|:---|:---|
| **Phạm Minh Thông** | Dải 1 | Trưởng nhóm, Crawler, Kiến trúc hệ thống | `2508.17872` → `2509.01046` (5.000 ID) |
| **Nguyễn Tiến Thành** | Dải 2 | Parser, Chuẩn hóa, Khử trùng lặp | `2509.01047` → `2509.06046` (5.000 ID) |
| **Nguyễn Trịnh Quang** | Dải 3 | Gán nhãn, Trích đặc trưng, Mô hình ML | `2509.06047` → `2509.11046` (5.000 ID) |

---

## 2. Mục tiêu Cuốn sách Báo cáo

Cuốn sách này là báo cáo kỹ thuật tổng hợp phục vụ Milestone 1 (Data Crawling) và Milestone 2 (Hierarchical Parsing & Standardization):
- **Chương 1 (Milestone 1):** Phân tích kiến trúc thu thập dữ liệu thô, thống kê kích thước, hiệu quả lọc ảnh nhị phân và benchmark hiệu năng (thời gian, RAM, đĩa cứng) trên môi trường Google Colab CPU.
- **Chương 2 (Milestone 2):** Phân tích giải thuật dựng cây phân cấp tài liệu LaTeX đa file, chuẩn hóa toán học, bóc tách BibTeX và hiệu quả khử trùng lặp 2 cấp độ.

Tất cả bảng số liệu và biểu đồ trong cuốn sách được sinh tự động bằng mã nguồn Python trong quá trình biên dịch (build) sách.
