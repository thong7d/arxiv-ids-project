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

- **Tổng số ID trong khoảng giao:** 15.000 ID, 5.000 ID/thành viên; đã đối soát manifest ngày 02/11/2026, chưa đồng nghĩa thu thập thành công 15.000 bài.
- **Tỷ lệ thành công thu thập (Success Rate):** Đang cập nhật.
- **Dung lượng trung bình trước và sau khi lọc ảnh:** Đang cập nhật.

Discovery theo các shard ngày thu được metadata của 14.992 ID thuộc khoảng giao. Khi đối soát khoảng liên tháng với ID cuối tháng 08 thực tế quan sát là `2508.21825`, có 8 ID chưa xuất hiện trong kết quả tìm kiếm. Những ID này vẫn được giữ trong manifest với trạng thái `search_missing` để truy vấn trực tiếp và tính vào mẫu số coverage. Chưa có đủ bằng chứng để kết luận chúng không tồn tại hay đã bị rút.

Danh sách thiếu trong search: `2508.18211`, `2508.18272`, `2509.06957`, `2509.06958`, `2509.07983`, `2509.07984`, `2509.10457`, `2509.10458`. Bản manifest trước đối soát và biên bản `manifest-gap-migration.json` được giữ trên Drive; mẫu pilot 30 bài không thay đổi. Các số liệu này là kết quả discovery, không phải kết quả full benchmark.

---

## 1.3. Đánh giá Hiệu năng trên Google Colab CPU

Benchmark cuối đo toàn bộ corpus của nhóm trên Colab CPU, bao gồm delay, retry và backoff. Được chia nhiều phiên có log và checkpoint. Tổng runtime cộng thời gian thực thi từng phiên; báo riêng thời gian lịch giữa phiên. Peak RAM lấy lớn nhất, average RAM có trọng số theo thời gian. Sample chỉ dùng pilot, không thay thế full benchmark.

- **Tổng thời gian chạy:** Đang cập nhật.
- **Thời gian xử lý trung bình mỗi bài báo:** Đang cập nhật.
- **Bộ nhớ RAM tiêu thụ tối đa (Peak RAM):** Đang cập nhật.
