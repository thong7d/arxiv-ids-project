# M1: ba Colab độc lập, dùng chung source và Drive

Phiên bản mới: protocol 4. Không có server/coordinator xuyên Colab, không cần URL
dịch vụ. Coordinator trong mỗi runtime vẫn quản lý process, checkpoint và retry.
Notebook chung: `notebooks/IDS13_M1_Colab.ipynb`.

Định danh HTTP: User-Agent chứa MSSV người chạy và email từ Secrets của chính
tài khoản Colab đó; S2 đọc key cá nhân từ `SEMANTIC_SCHOLAR_API_KEY`.
Ba tài khoản dùng cùng tên Secret nhưng giá trị riêng; không đặt key/email lên
Drive. arXiv API công khai không cần key hay đăng nhập arXiv riêng. Đổi email/
User-Agent không tạo quota mới và không bảo đảm hết 429; vẫn giữ lịch UTC,
giới hạn chung, backoff/Retry-After. Mỗi MSSV chỉ có một runtime đang chạy.

## Cập nhật giao diện Run all (13/11, phiên tối)

Notebook hiện có **3 code cell**: (1) chọn MSSV + setup/source/dependencies,
(2) tự test/preflight/khởi chạy, (3) bảng tiến độ và độ trễ. Chỉ chọn MSSV rồi
Run all; lần đầu vẫn phải chấp thuận quyền Google Secrets/Drive. Không có cờ
START_PILOT/START_FULL cần bật thủ công. Script `ids_arxiv.colab_app` tự probe
5 ID đầu, đạt thì mở đủ 5.000 ID. Chưa đạt thì giữ probe/retry, không giả báo đạt.

Output Run all ổn định tại `m1-team-v4/<runner>/main/full/<owner>/`; không tạo
corpus pilot riêng và không sinh thêm thư mục cho mỗi lần resume. Điều kiện bắt
buộc vẫn là một runtime/runner. Hai runner giúp cùng owner vẫn có namespace riêng.
Các mục hướng dẫn pilot/full từng cell và namespace runtime ở dưới mô tả giao
diện cũ/CLI nâng cao, không phải thao tác bắt buộc của notebook mới.

Ledger probe/full tách biệt (hậu tố `-probe` cho checkpoint/summary probe), dù
cùng corpus raw. Điều này ngăn resume từ full 5.000 rows làm probe đọc nhầm
toàn dải hoặc ghi đè checkpoint full. Các ledger/log này phục vụ khôi phục,
không phải corpus pilot trùng lặp.

Monitor đọc local, không quét toàn Drive. Có mean/p50/p95 mỗi lượt xử lý và các
khâu cache/import, metadata batch dùng chung, worker, ghi Drive, checkpoint; phần
worker tách metadata/source/S2/ngày reference/validation. `worker/*` là phân rã
của `paper_worker`, không cộng hai lần. Cache/retry được tách khỏi lượt có công
việc. Tốc độ tăng ròng bài đã đạt khác tốc độ số lượt thử; không suy ETA từ mẫu
nhỏ hoặc lấy warm resume làm cold benchmark. Chi phí queue idle/startup còn nằm
trong tổng runtime benchmark dù không thuộc độ trễ một lượt paper.

File tạm nằm trên SSD local và được đóng/dọn sau sử dụng. Backup của chính
transaction commit được dọn sau marker readback thành công; nếu commit lỗi giữ
bản khôi phục cần thiết. Không tự quét/xóa corpus hay backup lịch sử do người
khác tạo. Checkpoint, raw data, source release và log benchmark là dữ liệu bền
vững cần giữ, không phải file tạm.

## 1. Chuẩn bị một lần

Thông chia sẻ thư mục Drive cho Thành/Quang với quyền Editor. Mỗi người thêm
shortcut thư mục đó vào My Drive. Nếu tên/path khác, điền `DRIVE_ROOT_OVERRIDE`.
Mỗi người lưu **key S2 riêng** và email liên hệ của mình trong Colab Secrets:
`SEMANTIC_SCHOLAR_API_KEY`, `ARXIV_CONTACT_EMAIL`; bật Notebook access.
Không chép key vào source, output, chat hoặc GitHub.

Mỗi người dùng một bản copy của cùng notebook, runtime **CPU**, cùng SHA release.
Một MSSV người vận hành chỉ có một runtime hoạt động. Không dùng tiện ích giả
lập hoạt động hoặc hứa giữ Colab sống vô hạn.

## 2. Cấu hình

| Người chạy | `RUNNER_ID` | `TARGET_OWNER_IDS` mặc định |
|---|---|---|
| Thông | `23120364` | để `[]`: dải Thông |
| Thành | `23120358` | để `[]`: dải Thành |
| Quang | `23120345` | để `[]`: dải Quang |

Muốn Thành cào giúp Thông và Quang: giữ `RUNNER_ID="23120358"`, đặt
`TARGET_OWNER_IDS=["23120364", "23120345"]`. Không đổi danh tính người chạy thành
Thông/Quang. Chủ dữ liệu luôn lấy từ manifest, không lấy từ tài khoản vận hành.

## 3. Độc lập nhưng vẫn tuân thủ giới hạn mạng

`NETWORK_MODE="independent_utc"` là mặc định. Request arXiv/OAI/source luân phiên
theo UTC: phút 00–10/30–40 cho Thông; 10–20/40–50 cho Thành; 20–30/50–60 cho Quang.
Mỗi biên có đệm 10 giây. Máy Colab phải có đồng hồ UTC đúng. Kết nối chạy trong
process có watchdog và được đóng trước cuối lượt; giới hạn 3 giây vẫn áp dụng.
Việc này dựa vào lịch và danh tính cố định, không cần các Colab liên lạc với nhau.

S2 dùng key cá nhân, limiter/backoff riêng. Xử lý local, cache, kiểm tra và upload
không phải chờ lượt arXiv. Ba runtime độc lập **không có nghĩa** được vượt quota
toàn nhóm hoặc bảo đảm không bao giờ gặp 429/timeout.

`NETWORK_MODE="exclusive"` chỉ dùng khi đã xác nhận các crawler khác dừng. Chế
độ này không chờ lượt người khác. Benchmark cuối của cả nhóm nên dùng chế độ
này trên Colab CPU, chọn đủ ba owner; dữ liệu nhiều phiên phải giữ log riêng.
Không lấy tốc độ cache/resume hoặc cộng thời gian chạy song song làm cold benchmark.

## 4. Thứ tự chạy

1. Config: chọn runner, target, xác nhận một runtime/runner và key riêng.
2. Setup: CPU, đọc Secrets, mount Drive.
3. Source: xác minh SHA và giải nén release bất biến.
4. Dependencies + Offline tests: dừng nếu test không đạt.
5. Preflight: xác minh manifest, đúng 5.000 ID/owner và môi trường.
6. Pilot: bật `START_PILOT=True` một lần; Monitor đến khi kết thúc và đạt.
7. Full: bật `START_FULL=True` một lần; theo dõi Monitor. Pilot không tự mở full.
8. Audit: sau khi worker full dừng, chạy audit đủ 5.000 ID mỗi owner, đọc Report.

Các nút launch tự trả về False; bấm lại không tạo worker thứ hai. Muốn dừng,
copy chính xác `run_id` từ Monitor vào ô Stop. Không dùng Stop/Interrupt kernel
để thay cho dừng worker có kiểm soát. Agent cũng dùng đúng các cell này.

## 5. Output và resume

```text
Drive/
  m1-final-v3/                         # baseline cũ: chỉ đọc
  m1-team-v4/
    <runner>/<runtime>/<run_label>/
      pilot/<owner>/...
      full/<owner>/raw/<paper>/...
      full/<owner>/audit-result.json
    catalog/*.json
```

Dải khác nhau vốn không ghi cùng paper; namespace runner/runtime còn bảo vệ cả
trường hợp hai người cùng chọn một owner để hỗ trợ. Bản full của runtime cũ được
tìm qua catalog và nhập như cache chỉ đọc. Cache protocol 3 giữ lại source có hash
hợp lệ nhưng phải bổ sung snapshot S2 đầy đủ và metadata từng version. Chỉ copy
`.tex`/`.bib` nguyên byte; không đổi nội dung figure, không xóa corpus baseline.

Khi VM mới: chạy lại Setup → Source → Tests → Preflight → Pilot → Full với cùng
runner/target/run_label. Namespace runtime mới không đè runtime cũ; cache được
kiểm tra và copy, không coi cờ success cũ là bằng chứng đầy đủ. Có thể bổ sung
`CACHE_DIRS` nếu nguồn cache nằm ngoài catalog. Copy/kiểm hash Drive vẫn tốn thời
gian và được tính vào runtime; không được quảng cáo là resume miễn phí.

Không restart khi đang có staging chưa upload hoặc lỗi mirror. Nếu Google thu
hồi VM đột ngột, phần chưa mirror có thể mất; phần đã commit trên Drive giữ được.

## 6. Điều kiện hoàn tất và giới hạn hiện tại

Worker thoát hoặc thử đủ 5.000 ID chưa đồng nghĩa hoàn tất. Chỉ audit exact
manifest, hash/inventory, metadata từng version, toàn bộ snapshot S2 và ngày thật
mới cho phép chốt. Ngoại lệ nguồn bị rút phải có bằng chứng và không tính thành
tải thành công; 429/timeout còn là pending. Bản ghi S2 toàn publication không
được mô tả sai thành dữ liệu lịch sử riêng của từng revision.

Giữ toàn bộ references trong `references_all.json`; `references.json` là view
arXiv để làm M3. Không trộn các snapshot đang dở. M2/M3 và publisher vẫn là công
việc tiếp theo: notebook này **không** tuyên bố đã hoàn thiện parser/model hay
đã xuất bản dataset. Bộ nộp cuối có sáu bảng; xem `SPEC_AUDIT_2026-11-13.md`.

Hướng dẫn song song trước phiên bản này đã được lưu tại
`artifacts/notebook-backups-20261113/` trên workspace, không phải code để chạy tiếp.
