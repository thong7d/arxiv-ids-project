# Chương 1: Thu thập Dữ liệu (Milestone 1 — Data Crawling)

## 1.1. Kiến trúc Hệ thống Thu thập Dữ liệu

Hệ thống thu thập mã nguồn toàn văn của các bài báo arXiv được thiết kế tập trung, hỗ trợ checkpoint và tự phục hồi (resume):
- **API Etiquette:** Sử dụng mirror `https://export.arxiv.org/src/{arxiv_id}v{version}`, đảm bảo thời gian chờ tối thiểu 3 giây giữa các request liên tiếp, kết nối đơn (single connection) và đính kèm `User-Agent` chứa thông tin liên hệ.
- **Xử lý Đa phiên bản:** Phát hiện và tải tuần tự tất cả các phiên bản (`v1` đến `vN`) của mỗi bài báo.
- **Tối ưu hóa Dung lượng (Figure Stripping):** Toàn bộ file ảnh/binary (`.png`, `.jpg`, `.pdf`, `.eps`) được xóa ngay sau khi giải nén, chỉ giữ lại mã nguồn văn bản (`.tex`, `.bib`) và giữ nguyên cấu trúc môi trường `figure` trong mã LaTeX.
- **Thu thập Trích dẫn:** Sử dụng Semantic Scholar API để lấy siêu dữ liệu trích dẫn và liên kết với mã định danh arXiv ngoại vi.

---

## 1.2. Thống kê Dữ liệu Thu thập

*(Bảng số liệu và đồ thị phân tích sẽ được cập nhật tự động trong quá trình chạy dữ liệu chính thức).*

- **Tổng số bài báo được cấp:** 15.000 bài (chia đều 3 thành viên).
- **Tỷ lệ thành công thu thập (Success Rate):** Đang cập nhật.
- **Dung lượng trung bình trước và sau khi lọc ảnh:** Đang cập nhật.

---

## 1.3. Đánh giá Hiệu năng trên Google Colab CPU

- **Tổng thời gian chạy:** Đang cập nhật.
- **Thời gian xử lý trung bình mỗi bài báo:** Đang cập nhật.
- **Bộ nhớ RAM tiêu thụ tối đa (Peak RAM):** Đang cập nhật.
