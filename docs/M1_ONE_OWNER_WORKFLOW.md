# M1: một phiên, một dải ID

Trong notebook chọn `STUDENT_ID`, sau đó **Run all**. MSSV là chủ dải dữ liệu,
không phải tài khoản Google đang đăng nhập. Email và key S2 đọc từ Secrets của
tài khoản đang chạy, không ghi vào notebook hoặc log. Không dùng chung key S2.

Mỗi runtime chỉ chạy một workflow crawler/audit. Khi chọn MSSV khác, script chỉ
dừng worker workflow cũ có PID, thời điểm sinh và runtime khớp trên **chính máy đó**,
rồi mới chạy dải mới. Không dừng Colab của người khác. Nếu worker cũ không xác minh
được quyền sở hữu, script từ chối chạy đè. Chọn dải đã chốt không dừng dải đang chạy.

Ba máy có thể xử lý **ba dải khác nhau** cùng lúc, dùng lịch UTC hiện có. Mỗi dải
chỉ được giao cho một runtime tại một thời điểm, kể cả khi người khác chạy hộ.
Drive mount không cung cấp khóa phân tán đáng tin cậy: script không cam kết chống
hai máy cùng chọn một MSSV. Đây là điều kiện vận hành cần nhóm tuân thủ.

## Luồng và điều kiện dừng

1. Kiểm thử offline, kiểm tra manifest, Secrets và môi trường CPU.
2. Đọc biên bản chốt: dải đã chốt/đã dừng để xem ngoại lệ không tự cào lại.
3. Tận dụng cache đã kiểm checksum trong corpus cũ, không sửa corpus đầu vào.
4. Cào với tối đa 3 lượt có hoạt động HTTP/timeout mỗi bài. Thời gian chờ lịch UTC
   hay cooldown không bị tính thành một lượt lỗi. Giới hạn này là **lượt pipeline**,
   không phải tổng số request HTTP: một lượt có thể có retry hữu hạn ở HTTP client.
   HTTP 404 đủ điều kiện được chuyển sớm sang audit. Lỗi upload giữ staging để resume;
   không được biến thành ngoại lệ để bỏ mất dữ liệu chưa ghi.
5. Sau khi không còn công việc mạng tự động đến hạn, kiểm tra bằng chứng rút bài
   (tối đa 50 kiểm tra chính thức), rồi audit toàn bộ 5.000 ID. Audit chỉ đọc dữ liệu,
   có 4 lane I/O tách biệt, deadline từng bài và checkpoint Drive mỗi 100 kết quả.
6. Lưu kết quả và dừng rõ ràng: `stopped_with_documented_exceptions` hoặc
   `stopped_for_review`. Không tự quay lại cào vô hạn vì thiếu một vài bài.

Chốt chống chờ dài (đã được nhóm duyệt): khi **đủ 5.000 ID đã có ít nhất một lần
xử lý**, không còn upload/attempt chưa commit, và lần retry gần nhất còn cách hơn
30 phút, lưu `crawl-stop.json` rồi chuyển audit thay vì treo tiếp. Không gửi request
sớm hơn Retry-After, không đánh dấu dữ liệu thiếu là thành công hay chắc chắn mất.
Không áp dụng nếu còn ID chưa xử lý hoặc dữ liệu local chưa ghi xong. Lượt UTC
bình thường nằm trong cửa sổ chờ này. Source và S2 cùng 404 cũng chuyển audit khi
các phần metadata còn lại đủ, không tự hẹn 24 giờ cho cả hai trường hợp.

Mỗi phiên cào giới hạn 9 giờ; hết phiên còn công việc thì báo `needs_resume`, không
giả định những bài chưa xử lý là ngoại lệ. Run all lần nữa để tiếp tục checkpoint.
Lỗi hạ tầng/manifest/Drive vẫn dừng an toàn, cần sửa nguyên nhân trước khi chạy lại.

## Đọc Monitor

- Header chỉ trạng thái tiến trình **local** đã xác minh, có `run_id`.
- Khi audit: hiển thị `đã xét/5000`, bài gần nhất, số đánh giá tái dùng.
- Bảng ba MSSV lấy checkpoint đã lưu. Không suy ra worker máy khác còn sống từ file.
- Bộ đếm corpus cũ ghi rõ **CHƯA audit**, không gán thành kết quả protocol mới.
- Không đọc được checkpoint không đồng nghĩa dữ liệu bằng 0.

Output ổn định: `m1-team-v4/<owner>/main/full/<owner>/`.

- `raw/`: dữ liệu và bằng chứng crawl, không xóa ID lỗi.
- `audit-checkpoint/`: index + các chunk bất biến có checksum, cần giữ để resume.
- `audit-progress.json`: tiến độ audit bền vững, cập nhật mỗi 100 bài và khi xong.
- `audit-result.json`: đủ 5.000 đánh giá, có lý do và phân loại.
- `closure-evidence.json`: bằng chứng source đã kiểm tra.
- `exceptions.json`: các bài không phải `full_success`, kể cả cần xem xét.
- `closure.json`: biên bản chốt; phân biệt đóng vận hành và đầy đủ học thuật.

Checkpoint, bằng chứng và benchmark là đầu ra cần giữ, không phải thư mục tạm.
Staging/test/source giải nén nằm trên SSD local, không tạo corpus pilot riêng trên Drive.

## Resume audit và giới hạn kết luận

Audit đóng băng corpus trước khi xét. Khi runtime bị thu hồi, lần chạy tiếp theo
đọc chunk/checksum, manifest, phiên bản validator và hash commit marker để tái dùng
đánh giá phù hợp. Chunk chưa được index xác nhận không làm tăng tiến độ đã lưu.
Các kết quả `pending` được kiểm tra lại; không dùng timeout làm bằng chứng bài mất.
Nếu sửa tay dữ liệu raw ngoài pipeline mà không thay commit marker, phải chạy audit
`--fresh` bằng script; không dùng cache đánh giá cũ. Không chỉnh raw trong khi audit.

`verified_exception` chỉ khi có bằng chứng đúng bài/phiên bản. `references_unavailable`
chỉ dùng bằng chứng S2 404, không dùng 429/timeout. Thiếu S2 vẫn cần xác nhận học thuật.
Hết ngân sách không chứng minh bài không tồn tại; vẫn là hồ sơ `pending`/cần xem xét.
Không tạo references giả hoặc đổi `download_success` thành true.

Chỉ chuyển sang dải tiếp theo khi thấy trạng thái dừng và có `closure.json` +
`audit-result.json` đầy đủ. Đóng vận hành không tự động hoàn tất Book, benchmark toàn
nhóm trên Colab, hay quyết định ngoại lệ học thuật. Không triển khai M2/M3 trong luồng này.
