# Repair M1 có mục tiêu

Đây là thao tác **chủ động sau khi xem audit**, không được tự chạy lại chỉ vì
Run all. Notebook vẫn chỉ chọn một MSSV; không mở thêm crawler cho cùng dải.

- Đọc audit đủ 5.000 ID và kiểm tra lại manifest gốc, owner, protocol.
- Lưu `repair-plan.json` với hash audit và danh sách **pending**, ưu tiên lỗi
  metadata trước references; giữ nguyên bài đạt và ngoại lệ đã xác minh.
- `repair-progress.json` ghi nhận lượt thử trước khi gửi mạng. Mỗi bài tối đa
  một lượt xử lý bổ sung; timeout không tự mua lại lượt thử. Giữ Retry-After,
  cooldown và lịch UTC. Tổng ngân sách 60 phút tính từ lần chạy đầu, không reset
  khi resume. Chưa tới lượt hoặc chưa hết cooldown thì để lại cần xem xét.
- Staging nằm trên SSD. Kiểm tra commit marker trước khi sửa; bản Drive chỉ được
  cập nhật qua commit có kiểm tra checksum. Payload chưa upload phải được xử lý
  trước audit; nếu mất runtime chứa payload thì dừng để kiểm tra.
- Sau lượt sửa hữu hạn, audit lại pending và tái dùng kết quả đã đạt. Kết quả
  thiếu dữ liệu vẫn là pending, không phải thành công hoặc bằng chứng rút bài.
- Lưu kế hoạch đã hoàn thành; không tự tạo chiến dịch repair mới khi chạy lại.

CLI triển khai có kiểm soát dùng `python -m ids_arxiv.repair start --config-json ...`.
Không chạy CLI này khi runtime khác đang xử lý cùng owner. Không xóa receipt,
audit hoặc ledger để ép crawler chạy lại. Việc mở chiến dịch tiếp theo cần quyết
định riêng dựa trên kết quả, không lặp vô hạn.
