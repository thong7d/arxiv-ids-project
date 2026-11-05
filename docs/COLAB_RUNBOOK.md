# Colab M1 — Nhóm 13

> Cập nhật 02/11: lượt v2 dừng trước pilot vì API HTTP 500 tại offset 10.000. Discovery v3 chia theo tuần, tự tách tiếp nếu shard vượt 8.000 kết quả, cache riêng theo khoảng ngày. Campaign hiện hành là `m1-final-v3` và pilot `m1-pilot-v3`. Giữ toàn bộ thư mục/log v2 để audit, không trộn các lần chạy khác thuật toán thành một benchmark cuối.

## Trạng thái và nơi lưu

- Drive được cung cấp: https://drive.google.com/drive/folders/1NnyZolqKw5dIl_NsIW7BFMztqIXdetGI
- Tên thư mục đọc được: `IDS_Nhom13_Corpus_Backup`.
- Notebook: `notebooks/IDS13_M1_Colab.ipynb`.
- Script: `scripts/colab_campaign.py`.
- Secret chỉ đọc trong Colab: `ARXIV_CONTACT_EMAIL`, `SEMANTIC_SCHOLAR_API_KEY`.
- Toàn bộ dữ liệu/benchmark nằm trong Drive, không đưa vào Git.

## Kết nối MCP

Đăng ký MCP chính thức bằng Python 3.13 (tránh dependency Windows chưa có wheel cho Python quá mới):

```powershell
codex mcp add colab -- uvx --python 3.13 git+https://github.com/googlecolab/colab-mcp
```

Restart extension để nạp công cụ mới. Trong phiên chưa reload, `scripts/colab_bridge.py` có thể giữ một client đến MCP chính thức và nhận yêu cầu từ `artifacts/colab/request-*.json`. URL kết nối chứa token tạm, chỉ lưu trong artifact bị ignore. Không chia sẻ URL đó công khai.

Sau khi Google mở trang, Thông đăng nhập, cho phép MCP/mạng cục bộ nếu được hỏi, chọn runtime CPU, cấp quyền đọc hai Secrets và mount Drive. Đăng ký MCP không tự động chứng minh quyền truy cập runtime.

## Trình tự chạy

1. Build source-only bundle: `python scripts/build_colab_bundle.py`. Upload bundle và notebook vào đúng thư mục Drive; không upload `.env`, dữ liệu cá nhân hoặc token.
2. Chạy các cell đọc Secrets, mount Drive và xác minh thư mục đã cung cấp. Bundle cùng file `ids13-code.sha256` được đọc trực tiếp qua Drive mount; không yêu cầu đăng nhập Google API bổ sung. Kiểm tra checksum trước khi giải nén.
3. Cài package, chạy toàn bộ tests; dừng nếu có test lỗi.
4. Chạy `discover`: quét metadata arXiv không lọc category, lọc đúng ranges, xác minh boundaries, lưu manifest và metadata cache. Nếu API thiếu trang, không tạo manifest thành công.
5. Chạy `pilot`: 10 bài mỗi thành viên, thư mục riêng `m1-pilot-v3`. Kiểm tra cả nguồn, references và dates. Gate tự động yêu cầu 30 bài hoàn chỉnh. PDF-only/not-indexed cần audit và lý giải trước khi có override thủ công, không giả định là thành công đầy đủ.
6. Khi gate đạt mới chạy `full`: campaign `m1-final-v3`, nguồn cold-start, không lấy source pilot làm full benchmark. Worker mặc định có ngân sách 9 giờ, dừng mềm ở boundary publication; entrypoint từng stage mặc định tối đa 10 giờ.
7. Nếu Colab ngắt: mở lại notebook, mount Drive, nạp code/Secrets, chạy lại full. Resume chỉ bỏ qua version có checksum đúng và references hoàn chỉnh. Chạy tối đa ba lượt recovery sau lượt đầu; giữ danh sách lỗi còn lại.
8. Chạy validation và summary. Không gọi dữ liệu sample hoặc dữ liệu local là full Colab benchmark.

Notebook có chế độ worker: `colab_install_and_run.py` cài package, chạy tests rồi gọi `colab_autorun.py`. Theo dõi `m1-launch-status.json`, `m1-automation-status.json`, `m1-agent.log`. Worker không bị kết thúc chỉ vì một lệnh MCP hết thời gian chờ, nhưng vẫn chịu giới hạn runtime của Colab. Không mở worker thứ hai khi PID cũ còn chạy.

Nếu `userdata.get()` trả TimeoutException dù Notebook access đã bật, chạy cell đọc Secrets bằng nút Run trực tiếp trong giao diện Colab rồi để agent kiểm tra biến môi trường bằng boolean. Không in giá trị secret và không chuyển secret về máy local.

## Dữ liệu và log

```text
IDS_Nhom13_Corpus_Backup/
├── ids13-code.zip
├── IDS13_M1_Colab.ipynb
├── m1-pilot-v3/raw/
└── m1-final-v3/
    ├── manifests/papers.parquet
    ├── manifests/papers.json
    ├── manifests/discovery/
    ├── raw/<paper>/vN/
    ├── raw/<paper>/crawl_status.json
    ├── benchmark/session-*.json
    ├── benchmark/requests-*.jsonl
    ├── pass-*.json
    └── benchmark_summary.json
```

Mỗi status phân biệt source success, references success, date coverage và publication success. S2 429/timeout không được đổi thành references rỗng hợp lệ. Unknown date giữ null cho đến khi enrich từ arXiv.

### Đối soát ngày 02/11/2026

Discovery theo shard thu được 14.992 ID trong khoảng giao. Đối soát khoảng liên tháng theo ID cuối tháng thực tế quan sát `2508.21825` cho tổng 15.000 ID (5.000/người). Tám ID vắng trong search vẫn nằm trong manifest với `status=search_missing`; phải truy vấn trực tiếp khi crawl, không coi là metadata đã thu được hoặc tự kết luận bài bị xóa.

`scripts/reconcile_manifest.py` chỉ dùng trước full crawl; đã lưu bản sao manifest/sidecar/campaign pilot có hậu tố `.before-gap-audit`, ghi `manifest-gap-migration.json` và xác minh 30 ID pilot không thay đổi. Không sửa manifest của một full campaign đang chạy.

Bản sửa tải source giữ prefix khi đường truyền đứt, yêu cầu HTTP Range có kiểm tra Content-Range/validator. Nếu máy chủ trả 200 thay cho 206 thì ghi lại từ đầu, tuyệt đối không nối trùng prefix. Chỉ xuất source sau khi tải đủ và giải nén an toàn. Retry/delay vẫn thuộc thời gian đo; bản sửa này đang được kiểm chứng trên pilot, chưa phải kết quả benchmark cuối.

Release ghim trong notebook: `fb0283a65ea4d763ea0a3f8be9d239721021390abcaa763b11e364e8dc5adc13`, file `ids13-code-fb0283a65ea4.zip`. Các release mới dùng tên riêng để tránh cache Drive trả cặp ZIP/checksum khác phiên bản. Cell source vô hiệu hóa `CODE_ROOT` cũ trước khi nạp; launch chỉ nhận source đã xác minh. Không ghi đè release đang dùng cho full benchmark.

ETag là validator opaque, không được suy diễn thành checksum body chỉ vì có tiền tố `sha256:` ([RFC 9110 §8.8.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.8.3)). Khi server trả ETag khác theo range, ưu tiên so sánh cùng trường Last-Modified, xác minh Content-Range/kích thước, kiểm tra CRC/trailer gzip và EOF marker của PDF. SHA-256 tự tính được lưu cho source và inventory; đây là kiểm tra toàn vẹn artifact lưu trữ, không phải chứng thực checksum do nhà cung cấp công bố.

HTTP 429 được chờ tối thiểu 60 giây hoặc lâu hơn theo Retry-After. Pilot được resume tối đa ba lượt trong một worker, chờ giữa lượt được đo bằng session riêng; nếu vẫn không đạt gate thì dừng để audit, không đổi lỗi thành success. Full chỉ được mở khi gate đạt; thành công toàn bộ thì chạy validation riêng trước tổng hợp.

## Cách báo benchmark

- Runtime: tổng thời gian đo được của các phiên, bao gồm request, download, xử lý, rate limiting, retry/backoff và ghi checkpoint. Báo riêng thời gian lịch giữa phiên và thao tác thiết lập thủ công.
- RAM: tổng RSS process tree trong phiên; peak lấy max qua phiên, mean có trọng số theo thời gian. RSS có thể tính lặp shared pages; ghi rõ đây là RSS, không tuyên bố PSS.
- Disk: metric `peak_volume_used_bytes` là mức sử dụng volume quan sát, không đồng nhất với corpus size. Tổng corpus size lấy inventory của các version; báo riêng temporary source/download size.
- HTTP: giữ từng attempt và thời gian chờ, không ghi headers/token.
- Khi bị ngắt cứng: file heartbeat là cận dưới thời gian đã đo đến lần ghi cuối; báo khả năng thiếu đoạn ngắn cuối phiên, không tự tạo log.
- Báo coverage lượt đầu và sau recovery theo publication duy nhất, không lấy số attempts làm số bài.

## Điều kiện hoàn thành M1

Manifest đúng ranges và checksum; mỗi assigned ID có record hoặc lỗi giải thích được; mọi version được kiểm tra; không có binary; references/date coverage báo riêng; full benchmark có log Colab; số liệu Book sinh từ artifact đã đo. Lỗi hợp lệ như PDF-only vẫn cần được giữ trong mẫu số corpus.
