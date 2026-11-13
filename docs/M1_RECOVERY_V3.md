# M1 — bản phục hồi và tối ưu ngày 13/11/2026

## Phạm vi và trạng thái triển khai

**Phạm vi vận hành hiện hành:** chạy riêng 5.000 ID của 23120364 trước; chưa
triển khai mới cho Thành/Quang. Xem [biên bản cập nhật](M1_RELEASE_2026-11-13.md).
15.000 ID vẫn là phạm vi cuối cùng của môn học, không phải phạm vi worker hiện tại.

Bản này sửa launcher, monitor, coordinator, checkpoint, I/O Drive và cách lấy
ngày metadata/reference. Không thay đổi phạm vi 15.000 ID, không bỏ phiên bản,
không xóa corpus cũ, không triển khai M2/M3. Tốc độ tăng thực tế phải được đo
trên Colab; test offline không chứng minh mức tăng throughput hay chất lượng
của toàn bộ corpus hiện tại.

Ở bước chuẩn bị trước đó Thành/Quang còn cào riêng; sau đó đã xác nhận dừng.
Trong giai đoạn thử riêng Thông, **không khởi chạy thêm hai dải kia đồng thời**.
Mỗi runtime có limiter riêng, không có khóa/quota phân tán giữa ba Colab.
Một API key S2 dùng chung vẫn chia sẻ quota dù các tài khoản Colab khác nhau.

## Nguyên nhân đã xác minh

- Monitor cũ nhìn PID/thư mục `/proc`, nên zombie/PID được tái sử dụng hoặc
  PID ở runtime khác có thể bị báo xanh sai.
- Worker cùng process group/session với kernel. Stop/Interrupt cell có thể
  gửi SIGINT tới worker; log và xác nhận của Thông phù hợp với tình huống này.
- Kiểm tra cache và copy trên Drive FUSE không nằm trọn trong timeout bài.
- Resume quét lại hàng nghìn bài đã cào. Ghi JSON/fsync mỗi giây trên Drive
  và append log request làm tăng I/O nhỏ.
- S2 429/retry chặn luồng source; chạy ba Colab không tự làm quota tăng ba lần.
- Ngày publication của S2 không phải ngày submission arXiv. Không thể lấy ngày
  phiên bản cuối để điền cho các phiên bản trung gian bị thiếu.

## Những thay đổi trong mã

1. `runtime.launch_detached`: session riêng, stdin DEVNULL, log và heartbeat
   cục bộ, chặn worker trùng theo runtime + PID + thời điểm tạo process.
   Monitor hữu hạn, phân biệt RUNNING/WAITING/STALLED/STOPPED/UNKNOWN; không có
   cell giả lập hoạt động để hứa giữ Colab sống vô hạn.
2. Coordinator dùng process I/O và process xử lý paper độc lập. Cache/stage/
   commit có deadline 120 giây; xử lý paper 900 giây. Quá hạn thì recycle
   service, lưu công việc chờ sửa, không giết kernel hoặc worker khác.
   Đây là giới hạn cho *task*, không bảo đảm SIGKILL giải phóng ngay một process
   kẹt kernel D-state. Log lỗi và staging được giữ lại.
3. SQLite nằm trên ổ local; snapshot gắn checksum manifest + owner + protocol.
   Bài v3 đã commit không bị quét source lại ở mỗi resume. Dữ liệu legacy chỉ
   được xếp hàng audit, không tự đổi nhãn thành đã đạt chuẩn mới. Có thể suy
   ra prefix cũ từ summary/log để làm phần chưa cào trước, audit sau.
4. Xử lý local → copy source sạch → kiểm SHA-256 ở đích → ghi marker cuối.
   Upload lỗi không xóa staging. Thay thế source/metadata có bản backup ẩn.
   Không xóa backup tự động; cần quản lý dung lượng trước khi dọn thủ công.
5. S2 batch tối đa 20 paper/lượt prefetch, một lane chạy nền; chỉ dùng cache
   batch khi số reference thực nhận khớp `referenceCount`. Thiếu/truncated
   dùng endpoint phân trang. 429 có cooldown và next-retry, không giữ luồng
   source ngủ hết cửa sổ retry. Limiter chia sẻ giữa process **cùng runtime**.
6. Cache ngày arXiv dùng provenance và truy vấn các ID thiếu theo batch 100.
   Ngày phiên bản qua OAI hoặc versioned Atom, không nội suy. Ngày S2 giữ
   riêng `publication_date`; thiếu ngày arXiv vẫn là incomplete để sửa tiếp.
7. Benchmark lấy mẫu RAM cây process mỗi giây ở local, mirror theo đợt khoảng
   60 giây, request log là các chunk bất biến. Lỗi mirror giữ journal local.
   Retry/delay vẫn nằm trong elapsed time. Summary tách worker-seconds và
   hợp thời gian wall-clock của các phiên hoàn tất; không cộng thời gian song
   song rồi gọi đó là thời gian lịch. Session khác protocol phải phân tích riêng.

## Quy trình chuyển phiên bản an toàn

1. Thống nhất giờ chuyển với Thành/Quang. Không dùng Stop trong notebook cũ
   khi chưa biết process group. Cho phiên hiện tại kết thúc/checkpoint hoặc
   yêu cầu đúng chủ phiên dừng có kiểm soát; xác nhận cả ba không còn gửi API.
2. Giữ nguyên thư mục corpus, manifest, bằng chứng discovery và benchmark cũ.
   Không reset hoặc đánh dấu hàng loạt success. Bundle mới mang tên checksum
   riêng, không ghi đè source mà worker cũ đang dùng.
3. Trong **chính `IDS13_M1_Colab.ipynb`**, chạy source mới, kiểm thử offline,
   rồi chạy pilot thật 30 bài (10/người) có điều phối quota. Chỉ cho full tiếp
   tục nếu pilot và kiểm tra dữ liệu đạt; không dùng kết quả offline thay pilot.
4. Chọn `STUDENT_ID=None` cho một coordinator chung (khuyến nghị), hoặc một
   owner duy nhất cho lượt phục hồi có điều phối. Chỉ bật xác nhận network
   khi đã kiểm tra không còn crawler cạnh tranh quota. Không bật Run all.
5. Monitor chỉ đọc trạng thái/log local. Nếu STALLED, xem stage/deadline và log;
   không launch thêm. Nút dừng có xác nhận gọi stop theo process identity.
6. Khi hết phiên, đối chiếu summary, snapshot và log benchmark đã mirror lên
   Drive. Local staging chưa upload sẽ mất nếu runtime bị xóa; vì vậy không
   restart runtime khi còn `upload_pending`/`mirror_error`. Chưa có cơ chế
   bảo đảm giữ dữ liệu local qua việc Google thu hồi VM đột ngột.
7. Chạy strict validation cuối trên đủ manifest và gộp báo cáo cả nhóm.
   `success_count` mới có thể thấp hơn cũ do tiêu chí ngày/hash nghiêm hơn;
   điều đó không có nghĩa source cũ bị mất. Kiểm tra cả các trường hợp PDF-only,
   S2 not-indexed/404 và thiếu revision date, ghi lý do thực tế, không biến lỗi
   thành reference rỗng thành công.

Lệnh pilot (chỉ sau khi nhóm đã điều phối):

```bash
python scripts/colab_campaign.py pilot --root /content/drive/MyDrive/IDS_Nhom13_Corpus_Backup --coordinated-network
```

Launcher notebook gọi `colab_autorun.py` trực tiếp với `PYTHONPATH` tới bundle
mới, không pip editable/install đè vào môi trường worker cũ. Bootstrap cài
dependencies trên runtime mới là bước riêng trước khi chạy test.

## Giới hạn và hướng tiếp theo có điều kiện

- Chưa có con số tăng tốc xác minh production; đo pilot/đoạn mới bằng cùng
  protocol, không dùng cache-hit làm tốc độ tải mới. Không cam kết ETA cố định.
- Nếu Drive tiếp tục timeout: cần kiểm tra dung lượng/quota/tình trạng mount;
  không thể chữa mọi lỗi hạ tầng bằng thêm thread. Dừng nếu local spool gần đầy.
- Bulk arXiv/S3, S2 dataset snapshot, máy chủ/Colab trả phí có thể hữu ích khi
  đã kiểm tra coverage, tất cả version, license, giá và ngân sách; chưa kích hoạt.
- Không triển khai đổi IP/VPN để né rate limit. Tăng concurrency chỉ sau khi
  có ngân sách request/quyền truy cập phù hợp và đo được lợi ích.
- Release test phải gồm chạy Linux/Colab đối với cách ly SIGINT; test Windows
  sẽ skip phần này. Kiểm thử giả lập không thay thế một lượt pilot API thật.

Tài liệu nền: [Python subprocess](https://docs.python.org/3.13/library/subprocess.html),
[arXiv API terms](https://info.arxiv.org/help/api/tou.html),
[Semantic Scholar API tutorial](https://webflow.semanticscholar.org/product/api/tutorial).
