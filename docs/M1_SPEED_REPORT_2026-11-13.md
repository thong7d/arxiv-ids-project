# Đo tốc độ M1 — chỉ dải 23120364

## Điều kiện và tính trung thực của phép đo

Colab CPU, đúng notebook `IDS13_M1_Colab.ipynb`, chỉ owner `23120364`.
Source release: `888c08fbd8ea15536ef8e252a3eadb7576f41b12545beb2ae542816006d9a797`.
102/102 test offline đạt trên Colab; local 100 đạt và 2 test POSIX bỏ qua.
Các phép thử không đại diện cold benchmark đủ 15.000 ID của nhóm.

Không gọi trạng thái pending/429/metadata thiếu là đã xong. Không so speedup
trực tiếp protocol 3 và 4: protocol 4 còn cần toàn bộ references và metadata
từng version mà output cũ chưa có đầy đủ. Không ngoại suy ETA từ lượt retry/cache.

## Baseline quan sát được

21:07 ngày 13/11/2026 (UTC+7), worker cũ có 4.355/5.000 success theo protocol 3.
Trước khi chuyển worker khoảng 21:22: 4.452 success, source 4.828,
references 4.488, còn 548 pending. Baseline không bị xóa/ghi đè.

Log HTTP tại khoảng 21:08 (có giới hạn đọc 8 MB cuối file):

| Dịch vụ | Request | 200 | 429 | HTTP mean (s) | p50 (s) | p95 (s) |
|---|---:|---:|---:|---:|---:|---:|
| S2 | 1.402 | 608 | 792 | 0,147 | 0,115 | 0,277 |
| arXiv metadata | 2.701 | 2.644 | 47 | 1,014 | 0,235 | 2,500 |
| OAI | 899 | 899 | 0 | 0,153 | 0,152 | 0,217 |
| source | 1.475 | 1.444 | 0 | 0,439 | 0,378 | 1,046 |

Ngoài các mã trong bảng còn có 404/503/timeout. HTTP source của code streaming
cũ có thể chưa tính hết thời gian đọc body. Bảng không phải latency một paper.
S2 có khoảng 56,5% request 429: tăng concurrency không đồng nghĩa tăng throughput.

## Bản mới và phép đo đang chạy

Run `c4496363dc2f44b98630aad263b5727f`, bắt đầu 21:22:40; một worker,
`independent_utc`, probe 5 bài dùng chính thư mục full. Người dùng xác nhận
hai crawler còn lại dùng cùng lịch UTC. Không bật exclusive khi ba người cùng chạy.

Đến 21:28: source 5/5, references 5/5, chưa đủ metadata theo version nên
success 0/5. Đây là chờ lượt arXiv của Thông, không phải treo kernel.
Mẫu 13 lượt: mean 0,98 s/lượt, p50 0,46 s, p95 2,90 s; Drive commit
mean 0,208 s, p95 0,253 s. Metadata được defer và source lấy từ cache, vì vậy
không được diễn giải các số này là tốc độ tải mới hoặc tốc độ hoàn tất paper.

Phép đo mỗi lượt gồm cache/import → batch metadata dùng chung → prefetch →
worker → commit → checkpoint. Worker tách metadata, source, S2, ngày references,
validation. `worker/*` là phần bên trong `paper_worker`, không cộng hai lần.
Tổng benchmark còn bao gồm startup/queue idle/retry/delay; latency lượt không
bao gồm startup và khoảng nghỉ ngoài lượt. Journal có kind `paper_attempt`
để phân biệt với HTTP và có cờ cache_hit/success.

## Các tối ưu đã triển khai

- Giữ source cũ đã kiểm inventory/hash; chỉ lấy `.tex`/`.bib`, không tải lại vô ích.
- Batch metadata/version chính xác; không chép metadata phiên bản mới sang bản cũ.
- Tái sử dụng submission date đã xác minh trong references cũ khi lấy lại snapshot S2 đầy đủ.
- SSD local cho staging/state; Drive ghi transaction, marker sau cùng và kiểm readback.
- Dọn scratch JSON/backup transaction sau khi xác nhận; giữ bản khôi phục nếu lỗi,
  không quét xóa lịch sử người dùng. Giữ log benchmark/checkpoint làm bằng chứng.
- Probe/full cùng output; namespace ổn định qua resume, catalog một entry/runner/owner.
- Notebook chỉ ba code cell, script Python giữ logic; Run all không launch trùng.

## Chưa thể kết luận

Chưa có cold benchmark đủ nhóm, thử có kiểm soát đủ lớn giữa các phương án
S2/transport, hoặc bằng chứng đã đạt tốc độ tối đa. API quota, 429, số version và
độ lớn source vẫn ràng buộc thời gian. Không dùng VPN/IP rotation để vượt giới hạn.

## Cập nhật thử nghiệm và bản bàn giao (sau 21:43)

Source bàn giao: `179d7935569cb4e6832ee0b2dd6f496b1ea757d4542f309c77aa5407cabb5c0f`.
103 test đạt trên Colab CPU qua luồng Run all; local 101 đạt, 2 test POSIX bỏ qua.
Notebook đang kết nối được rút còn 1 markdown + 3 code cell; nội dung chẩn đoán
cũ được lưu ở artifacts workspace, không tạo notebook/bản sao mới trên Drive.
Một ZIP phát triển do phiên này tạo được cập nhật tại cùng file ID, không sinh
nhiều ZIP thử nghiệm trên Drive. Không đụng các release/corpus lịch sử khác.

Probe 5 ID đã đạt, tự mở full 5.000. Trước thử S2 lúc 21:36: 33 full success,
374 source success, 377 ID đã xét; đây là số protocol 4, không cộng vào 4.452
success protocol 3 của baseline. Bộ đếm thử/retry không phải số paper duy nhất.

Thử S2 có kiểm soát, tạm dừng đúng worker Thông; dùng cùng quota/backoff cá nhân:

| Phương án | Kết quả |
|---|---|
| batch 2 paper | 1 request HTTP 429, 0 publication hoàn chỉnh; không bật mặc định |
| references page size 1.000 | HTTP 200, 19 references, body 12.611 byte, HTTP 0,188 s |
| references page size 100 | HTTP 200, cùng 19 references/body hash, HTTP 0,193 s |

Trang 100 chịu thêm 1,757 s chờ limiter do chạy sau, vì vậy không so trực tiếp
wall-time hai lượt để kết luận size 100 chậm gấp nhiều lần. Hai HTTP latency gần
nhau trên một paper nhỏ không chứng minh size nào tối ưu cho toàn tập; giữ 1.000
và pagination đầy đủ. Không bật nhiều luồng S2 hoặc bỏ backoff từ phép thử này.

Sau đo, worker mới PID `161754`, run `60e6cbe4472d429a945272c422becf6a`
đã khởi chạy và resume đúng 5.000 ID, cùng thư mục full. Tách ledger probe/full
ngăn probe đọc nhầm checkpoint 5.000 rows; regression test kiểm tra full index
không bị probe ghi đè. Các payload JSON giống hash không upload/backup lại;
lượt cache không tái sử dụng timing của attempt trước. Bản này tiếp tục cào nền.

21:48:04: 40/5.000 full success, 687 source success và 55 references success.
Mẫu gần nhất 378 lượt: mean 0,53 s, p50 0,34 s, p95 1,40 s/lượt. Cache/import
mean 0,105 s; Drive commit 0,222 s; checkpoint 0,044 s. Mẫu này trộn phục hồi
cache và retry; arXiv đang ngoài lượt nên không dùng thời gian metadata được
defer (0,007 s) làm HTTP latency. Không lấy 5.000 × p50 để dự đoán hoàn tất.

21:49:51: worker RUNNING, source 838, references 55, full success 40;
không có trường lỗi checkpoint/control trong trạng thái hiện tại. Kiểm tra năm
paper probe không còn `.incoming-*`, `.previous-*`, `.tmp` hay `.upload`.
Đây là kiểm tra có giới hạn, không tuyên bố đã quét toàn bộ lịch sử Drive.

21:51:05: 40 full success, 926 source success, 55 references success, worker
vẫn RUNNING. Mẫu 394 lượt gần nhất: mean 0,51 s, p50 0,35 s, p95 1,29 s;
cache/import mean 0,120 s, commit 0,279 s, checkpoint 0,047 s. Không diễn giải
0,006 s của khâu references đang defer thành độ trễ tải references thành công.
Notebook cuối đã trả về Monitor thường, không còn cell thử S2/stop worker.
