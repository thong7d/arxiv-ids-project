# Chuẩn bị báo cáo M1, không chạy lại crawler

Chương 1 là MyST notebook Markdown: bảng và biểu đồ được sinh bằng Python **khi
build**, không chèn ảnh chụp Monitor. Collector chỉ đọc dữ liệu, không sửa raw,
không bắt đầu/dừng crawler và không chạy M2/M3. Chương 2 được giữ nguyên.

## 1. Thu thập snapshot tổng hợp

Dùng source mới trong repository (bundle crawler đang chạy có thể chưa chứa module
báo cáo mới). Đừng thay source của worker đang chạy chỉ để lấy báo cáo.

Trên Colab đã mount Drive, hoặc máy có bản sao đầy đủ các thư mục tương ứng:

```bash
python scripts/collect_m1_report.py \
  --drive-root /content/drive/MyDrive/IDS_Nhom13_Corpus_Backup \
  --output /content/m1-report-snapshot.json
```

Mặc định chỉ đọc audit và bộ đếm, để không quét nhiều log trong lúc crawler đang
chịu tải Drive. Sau khi các worker đã checkpoint, thêm `--include-benchmarks
--include-events` để đối soát session và ID có log. Input lỗi hoặc timeout được ghi
rõ, không suy ra không có dữ liệu. Audit sai manifest/owner/counters bị từ chối.

Snapshot chỉ có aggregate, timestamp và checksum, không có API key, toàn văn hay
danh sách references. Giữ snapshot ở `artifacts/m1-report/snapshot.json` local (bị
gitignore), hoặc chỉ định đường dẫn bằng `IDS_M1_REPORT_SNAPSHOT`. Raw corpus và
audit đầy đủ không được đưa vào repository code.

Thêm `--include-marker-statistics` chỉ **sau khi corpus đã đóng băng và có audit
đã chốt vận hành**. Collector đọc marker theo batch 50 ID, kiểm thay đổi marker
với hash audit khi có; đây không phải audit lại toàn bộ source bytes. Bản audit
lịch sử chưa có marker hash dựa vào điều kiện corpus đứng yên. Không chạy bước
quét 5.000 marker này cùng lúc crawler đang chịu tải Drive.

Kích thước trước/sau dùng cùng cohort publication có đủ số đo tất cả version;
PDF-only không có số đo archive giải nén tương đương nên bị loại khỏi cohort đó,
không gán 0. References rỗng hợp lệ được tính là 0, còn lỗi/thiếu snapshot là N/A.
Tổng byte TeX/Bib từ marker không phải dung lượng toàn thư mục (chưa gồm JSON,
log, checkpoint và overhead filesystem). Các mẫu số/cohort đều được lưu riêng.

## 2. Build local, chưa publish

Cấu hình `_config.yml`/`_toc.yml` hiện dùng Jupyter Book 1/Sphinx. Không dùng tùy ý
Jupyter Book 2 cho định dạng này. Tạo môi trường báo cáo riêng, không đổi `.venv`
crawler hoặc runtime Colab:

```powershell
uv venv artifacts/book-build-env --python 3.11
uv pip install --python artifacts/book-build-env/Scripts/python.exe -r requirements-book.txt
$env:IDS_M1_REPORT_SNAPSHOT = (Resolve-Path artifacts/m1-report/snapshot.json).Path
artifacts/book-build-env/Scripts/jupyter-book.exe build book --all --warningiserror --keep-going
```

Mở `book/_build/html/ch1_crawling.html` và kiểm bảng/biểu đồ. Không có snapshot thì
sách chỉ hiện cảnh báo bản chuẩn bị, không dùng demo để giả lập số liệu thật.
Lỗi snapshot khiến build lỗi; không bỏ qua lỗi thực thi notebook.

## 3. Diễn giải đúng phạm vi

- Success = `full_success` sau audit, mẫu số toàn bộ ID được giao.
- Ngoại lệ source/S2 và pending không phải tải thành công.
- Dải chưa audit: 5.000 ID chưa đánh giá, tỉ lệ N/A; không dùng success cũ thay thế.
- Snapshot audit được tính lại từ từng assessment và gắn SHA. Collector thống kê
  không tự tái kiểm toàn bộ hash raw; corpus cần giữ đứng yên sau audit.
- Session/log trùng được đối soát, không nhân đôi số đo hay số ID.
- Tổng worker-seconds không phải wall-clock hệ thống song song. Hợp interval chỉ
  bao gồm các phiên đã kết thúc, không tự bao gồm khoảng nghỉ/discovery.
- RAM trung bình có trọng số thời gian. Peak một worker không là peak tổng nhóm.
- Không đủ bằng chứng end-to-end/CPU/discovery/coverage thì benchmark chưa final.
- Chưa tổng hợp kích thước corpus/references thì để thiếu rõ ràng, không gán 0.

## 4. Gate trước bản cuối

Cả ba dải cần có audit đủ ID và hồ sơ ngoại lệ; bổ sung thống kê source trước/sau
lọc, references, storage và toàn bộ benchmark. `initial_bytes` của archive là byte
giải nén trước lọc, không phải compressed transfer; PDF-only cần cohort riêng.
Đối chiếu yêu cầu hosting Book riêng với code repo. Hiện hai URL nhóm cung cấp là
`github.com/thong7d/arxiv-ids-project` và `thong7d.github.io/arxiv-ids-project/`;
phiên chuẩn bị không đổi link, không tạo repo và không publish. Chuyển snapshot
aggregate sang repo Book như thế nào sẽ được chốt trước khi xuất bản.

Nguồn: [đề M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/),
[MyST notebooks v1](https://jupyter-book.readthedocs.io/v1/file-types/myst-notebooks.html).
