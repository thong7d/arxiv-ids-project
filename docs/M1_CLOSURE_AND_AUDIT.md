# Kết thúc M1 có ngoại lệ và audit

Notebook chỉ khởi chạy/giám sát; logic nằm trong script Python. Workflow tự nối
crawl hữu hạn → audit → chốt ngoại lệ cho duy nhất MSSV được chọn, không chạy M2/M3.
Xem [workflow một dải](M1_ONE_OWNER_WORKFLOW.md) cho cách Run all hiện hành.
Phần dưới mô tả lệnh audit thủ công dành cho chẩn đoán/kiểm tra lại.

Mẫu dưới dùng output compact của notebook hiện hành. Nếu dữ liệu Thành/Quang
còn ở namespace runtime của bản cũ, phải xác định đúng config/output trước,
không trỏ nhầm thư mục rồi coi 5.000 record thiếu là ngoại lệ.

## Kết quả và ý nghĩa

- `full_success`: kiểm readback toàn bộ hash, inventory, metadata/version,
  references đầy đủ; giữ nguyên success thật.
- `verified_exception`: phiên bản source bị rút, có bằng chứng đúng arXiv ID,
  version, URL, HTTP 200, banner withdrawn/no PDF, hash và thời điểm kiểm tra.
- `references_unavailable`: chỉ bật khi người vận hành chọn `--freeze-s2-404`;
  cần bằng chứng endpoint S2 đúng paper trả 404, hash/time, không có snapshot dở.
  Metadata và source còn lại vẫn phải đạt kiểm tra. 429/timeout không được nhận.
- `pending`: bất cứ lỗi/checksum/metadata/coverage chưa giải quyết nào khác.

`operational_closed=true` nghĩa đã đủ hồ sơ để dừng hàng đợi. KHÔNG đồng nghĩa
`collection_closed=true` hoặc đã được giảng viên chấp nhận thiếu S2. Khi còn
references_unavailable, `academic_exception_approval_pending=true`; cần trình
bằng chứng cho giảng viên. Không sửa raw/crawl_status.json hay tăng success giả.

## Chạy cho từng thành viên trên Colab CPU

Chạy Setup để mount đúng Drive/nạp source mới; không chạy crawler thứ hai.
Từ Python script hoặc subprocess với PYTHONPATH trỏ tới `<CODE_ROOT>/src`:

```python
import json, subprocess, sys

owner = "23120364"  # Thành: 23120358; Quang: 23120345
config = {
    "runner_id": owner,
    "target_owner_ids": [owner],
    "drive_root": "/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup",
    "network_mode": "independent_utc",
    "one_runtime_per_runner_confirmed": True,
    "personal_s2_key_confirmed": True,
    "compact_output": True,
    "run_label": "main",
}
command = [sys.executable, "-u", "-m", "ids_arxiv.finalize",
           "--config-json", json.dumps(config), "--stop-current",
           "--freeze-s2-404"]
# Nếu có bằng chứng bổ sung: command += ["--extra-evidence", "/tmp/proofs.json"]
# Chạy dài qua detached subprocess có stdout/stderr vào log LOCAL,
# như launcher hiện hành. Không dùng PIPE không được đọc.
subprocess.run(command, check=True)
```

`--stop-current` kiểm tra identity/runtime/process birth time rồi dừng đúng
worker của owner. Nếu bỏ cờ, audit từ chối khi worker còn chạy. Actor có thể khác
owner; output luôn thuộc namespace owner đã chọn. Source bị rút phải thu thập bằng chứng
cho từng phiên bản; không sao chép danh sách của Thông cho Thành/Quang.

File extra-evidence có `student_id` đúng owner và `records` là list/dict bằng
chứng như `verify_withdrawal` trả về. Một lần HTTP 404 chung chung không đủ.

## Output bền vững

Trong `m1-team-v4/<owner>/main/full/<owner>/`:

- `closure-evidence.json`: bằng chứng dùng cho audit;
- `audit-result.json`: audit exact 5000 ID, kết quả từng paper;
- `closure.json`: quyết định dừng, số lượng và điều kiện học thuật còn thiếu.

Progress/log audit ở SSD local `/tmp/ids13-finalize/<owner>/`, không tạo corpus
pilot hay thư mục runtime mới trên Drive. Audit có timeout mỗi paper; lỗi I/O
thành pending, không giả complete. Nếu còn pending, receipt không khóa crawler.
Trong lúc audit chạy, `closure.json` có `audit_in_progress=true` và launcher
cũng bị khóa. Nếu VM bị Google thu hồi, không coi receipt này là đã audit xong:
mount Drive, nạp source rồi chạy lại finalize. Không chạy crawler cạnh tranh.
Audit dùng bốn lane I/O chỉ đọc và không gọi API mạng.

## Chạy lại và mở lại

Sau audit đóng vận hành, launcher từ chối tự chạy lại cả pilot/full/auto, kể cả
Run all. Giữ receipt như bằng chứng; không xóa raw. Nếu có dữ liệu/định danh mới
cần sửa: người vận hành phải lưu bản receipt rồi chủ động gỡ `closure.json`,
chạy recovery có kiểm soát và audit lại. Các số checkpoint crawl có thể vẫn là
4959/5000; đọc closure report để hiểu số ngoại lệ, không đổi chúng thành success.

Chỉ sau khi audit đủ và thống nhất ngoại lệ mới đóng băng đầu vào M2; benchmark,
Book và xác nhận ngoại lệ S2 vẫn là điều kiện riêng để chốt M1 học thuật.
