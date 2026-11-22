---
jupytext:
  text_representation:
    extension: .md
    format_name: myst
kernelspec:
  display_name: Python 3
  language: python
  name: python3
---

# Chương 1: Thu thập dữ liệu — Milestone 1

## 1.1. Phạm vi và tình trạng báo cáo

Báo cáo phân biệt dữ liệu đã thu được, kết quả đã kiểm định và ngoại lệ chưa thu
được. Không cộng ngoại lệ vào số tải thành công. Dải chưa có audit đầy đủ để tỉ lệ
đạt là **N/A**, không suy ra bằng 0 hay lấy cờ success của crawler cũ.

Nhóm được giao ba dải, tổng cộng 15.000 ID. Manifest discovery đã xác minh là đầu
vào chung; ID tìm kiếm không trả về vẫn được giữ để đối soát, không tự loại khỏi
mẫu số. Nguồn: [đề M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/).

```{code-cell} python3
:tags: [hide-input]

import os
import sys
from pathlib import Path
from IPython.display import HTML, Markdown, display

project = next((p for p in [Path.cwd(), *Path.cwd().parents]
                if (p / "src/ids_arxiv/m1_report.py").is_file()), None)
if project is not None:
    sys.path.insert(0, str(project / "src"))
from ids_arxiv.m1_report import load_snapshot, coverage_table, coverage_figure

default_path = project / "artifacts/m1-report/snapshot.json" if project else Path("m1-report-snapshot.json")
snapshot_path = Path(os.environ.get("IDS_M1_REPORT_SNAPSHOT", str(default_path)))
snapshot = load_snapshot(snapshot_path) if snapshot_path.is_file() else None
if snapshot is None:
    display(Markdown("**BẢN ĐANG CHUẨN BỊ:** chưa cung cấp snapshot có bằng chứng. "
                     "Không có số liệu minh họa được giả làm kết quả thực nghiệm."))
else:
    display(Markdown(f"**Snapshot:** {snapshot['generated_at']}  \n"
                     f"**Manifest SHA-256:** `{snapshot['discovery_manifest_sha256']}`  \n"
                     "**Trạng thái:** báo cáo tiến độ, chưa xác nhận hoàn tất M1 toàn nhóm."))
```

## 1.2. Thiết kế và luồng thực hiện

Một source Python phục vụ cả ba thành viên; notebook chỉ chọn MSSV, chuẩn bị
Secrets/Drive, khởi chạy và hiển thị. Dải ID xác định namespace dữ liệu, không phụ
thuộc người đang hỗ trợ chạy. Mỗi runtime chỉ có một workflow crawler/audit; cùng
một dải chỉ giao cho một runtime. Drive FUSE không được coi là khóa phân tán.

Luồng thực tế: manifest → đối soát/import cache bằng checksum → metadata theo
phiên bản → source từng phiên bản → toàn bộ references S2 → ngày submission của
references arXiv → kiểm định local → commit có readback → checkpoint → audit → chốt.

- **Discovery/version:** Atom theo ID và version, kết hợp dữ liệu ngày có nguồn
  gốc arXiv. Không chép title/ngày bản mới nhất cho bản cũ chưa có bằng chứng.
- **Source:** chỉ trích `.tex`/`.bib` lên SSD local. Ảnh/binary không được trích vào
  corpus; không sửa lệnh `figure`/`includegraphics` trong TeX. PDF-only/non-TeX hợp
  lệ có trạng thái rõ ràng và thư mục source rỗng.
- **References:** giữ toàn bộ snapshot S2 và view riêng cho references mang arXiv
  ID. Không dùng view đã lọc để tuyên bố giữ đầy đủ references.
- **Commit:** ghi marker cuối, kiểm hash và đọc lại. Upload lỗi giữ staging để
  resume; không xóa bản tốt chỉ vì một lần cào lại không hoàn chỉnh.
- **Mạng:** các runtime dùng lịch UTC chung cho arXiv, pacing và backoff; mỗi tài
  khoản dùng Secrets cá nhân. Đổi email/key không tạo thêm quota arXiv và không
  bảo đảm S2 hết 429.

Thư viện chính: `requests`, `pandas`, `pyarrow`, `psutil`, `pydantic`. Các module
`crawler/runner.py`, `checkpoint.py`, `workflow.py`, `finalize.py`, `audit_journal.py`
thực hiện xử lý. `pytest` kiểm thử lỗi giả lập, không thay thế audit corpus thật.

## 1.3. Retry và ngoại lệ

Workflow giới hạn ba lượt pipeline có hoạt động HTTP/timeout mỗi bài; một lượt có
thể gồm retry hữu hạn tại HTTP client. Chờ UTC/cooldown không tính như lượt lỗi mới.
Hết ngân sách chỉ dừng tự động và tạo hồ sơ cần xem xét, **không chứng minh bài không
tồn tại**. Hết phiên còn việc thì resume, không coi mọi ID chưa xử lý là ngoại lệ.

Audit kiểm toàn bộ ID của dải, với I/O có deadline và checkpoint chunk/index trên
Drive. Resume đối chiếu manifest, validator, bằng chứng và commit marker. Corpus
phải đứng yên; sửa raw ngoài pipeline yêu cầu audit mới, không dùng cache kết luận.

| Phân loại | Ý nghĩa | Tính tải thành công? |
|---|---|---|
| `full_success` | Đạt source, metadata/version, references và hash | Có |
| `verified_exception` | Thiếu source có bằng chứng rút đúng ID/version | Không |
| `references_unavailable` | S2 404 có bằng chứng, phần còn lại đạt | Không; chờ xác nhận học thuật |
| `pending` | Lỗi dữ liệu/I/O hoặc chưa đủ bằng chứng | Không |
| Chưa audit | Chưa có đủ 5.000 đánh giá được đối soát | Chưa kết luận |

`operational_closed` cho phép dừng mạng với hồ sơ đầy đủ; không đồng nghĩa 5.000
lượt tải thành công, `collection_closed`, hay giảng viên đã chấp thuận ngoại lệ.

## 1.4. Coverage đã kiểm định

Bảng và biểu đồ tạo lại khi build Book từ snapshot thống kê; không dùng ảnh chụp
Monitor và không thay số liệu thiếu bằng dữ liệu mẫu.

```{code-cell} python3
:tags: [hide-input]

if snapshot is not None:
    table = coverage_table(snapshot)
    display(HTML(table.astype(object).where(table.notna(), "N/A").to_html(border=0)))
    display(coverage_figure(snapshot))
    import matplotlib.pyplot as plt
    plt.close("all")
```

Mẫu số tỉ lệ tải đạt là toàn bộ ID được giao. Dải chưa audit chỉ có tiến độ crawler,
không phải kết quả kiểm định của hợp đồng dữ liệu hiện tại.

### Thống kê dung lượng và references

Các số đo sau chỉ có khi thu marker từ corpus đã đóng băng sau audit. Trung bình
source trước/sau dùng cùng cohort bài có đủ số đo giải nén cho mọi version; không
trộn PDF-only hoặc missing vào dưới dạng số 0. Số references lấy trung bình trên
các snapshot S2 thành công, gồm cả trường hợp rỗng hợp lệ; mẫu số được ghi riêng.

```{code-cell} python3
:tags: [hide-input]

if snapshot is not None:
    import pandas as pd
    rows = []
    for owner, item in snapshot["owners"].items():
        stats = item.get("corpus_statistics") or {}
        rows.append({"MSSV": owner, "Marker đã đọc": stats.get("observed_committed_markers"),
                     "Bài cùng cohort size": stats.get("paired_size_papers"),
                     "Byte TB trước lọc": stats.get("mean_before_uncompressed_bytes"),
                     "Byte TB TeX/Bib sau lọc": stats.get("mean_after_tex_bib_bytes"),
                     "Bài có số refs": stats.get("all_reference_count_papers"),
                     "Refs TB (toàn bộ S2)": stats.get("mean_all_references"),
                     "Refs arXiv TB": stats.get("mean_arxiv_references")})
    sizes = pd.DataFrame(rows).set_index("MSSV")
    display(HTML(sizes.astype(object).where(sizes.notna(), "N/A").to_html(border=0)))
```

Đây là số đo đã ghi bởi crawler, không phải một lần kiểm định byte mới. Tổng byte
TeX/Bib không được gọi là tổng storage output; dung lượng JSON, log, checkpoint và
filesystem phải được đo riêng. N/A nghĩa chưa thu số đo, không phải giá trị bằng 0.

## 1.5. Benchmark và phạm vi đo

Benchmark cuối phải bao phủ toàn bộ nhóm trên Colab CPU, tính delay, retry và
backoff; nhiều phiên giữ log để đối chiếu. Snapshot phân biệt tổng worker-seconds
với hợp khoảng thời gian các phiên đã kết thúc. Không cộng thời gian worker song
song rồi gọi đó là wall-clock toàn hệ thống.

```{code-cell} python3
:tags: [hide-input]

if snapshot is not None:
    import pandas as pd
    rows = []
    for owner, item in snapshot["owners"].items():
        measured = item["benchmark"]
        rows.append({"MSSV": owner, "Phiên kết thúc": measured["completed_sessions"],
                     "Worker giây": measured.get("measured_worker_seconds"),
                     "ID có log": measured.get("coverage_count"),
                     "RAM TB worker (byte)": measured.get("average_process_tree_rss_bytes"),
                     "Peak một worker (byte)": measured.get("peak_single_worker_rss_bytes"),
                     "End-to-end hệ thống": measured.get("end_to_end_seconds")})
    performance = pd.DataFrame(rows).set_index("MSSV")
    display(HTML(performance.astype(object).where(performance.notna(), "N/A").to_html(border=0)))
```

RAM trung bình = tổng byte-seconds / tổng thời gian lấy mẫu; không trung bình không
trọng số giữa phiên. Peak một worker không chứng minh peak tổng RAM khi nhiều
runtime hoạt động. `mean/p50/p95` trên Monitor là mẫu lượt xử lý gần đây có cache;
không gọi đó là cold benchmark hay speedup đã chứng minh.

Trước bản cuối còn cần: thời gian discovery; end-to-end có nguồn gốc; xác minh CPU
và log bao phủ ba dải; dung lượng output thực; peak disk theo phạm vi đo; trung
bình source trước/sau lọc và references. `initial_bytes` là kích thước thành viên
archive **giải nén trước lọc**, không phải byte tải mạng nén. PDF-only cần cohort
riêng, không đưa số 0 mặc định vào trung bình source trước lọc.

## 1.6. Thử nghiệm S2 có kiểm soát

Phép thử riêng dừng/checkpoint đúng worker, dùng cùng key/quota và tối đa sáu
request trên hai paper của Quang. So sánh page-size 1.000, endpoint chi tiết paper
kèm `referenceCount`, và page-size 100; đảo thứ tự cho paper thứ hai. Không đổi IP
hay tăng quota. Kiểm tra số references và hash snapshot chuẩn hóa trước khi xét
hiệu năng. Đây là thử nghiệm nhỏ, **không phải benchmark cuối toàn nhóm**.

```{code-cell} python3
:tags: [hide-input]

import json
import pandas as pd
probe_default = project / "artifacts/M1_S2_CONTROLLED_RESULT_20261117.json" if project else Path("m1-s2-experiment.json")
probe_path = Path(os.environ.get("IDS_M1_S2_EXPERIMENT", str(probe_default)))
if probe_path.is_file():
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    attempts = probe["attempts"]
    assert probe["state"] == "finished" and 0 < len(attempts) <= 6
    assert sum(len(row.get("events", [])) for row in attempts) <= 6
    display(Markdown(f"**Thời điểm kết thúc phép thử:** {probe['finished_at']}"))
    trial = pd.DataFrame([{"Paper": row["arxiv_id"], "Phương án": row["route"],
                           "HTTP": row.get("http_status"), "References nhận": row.get("raw_count"),
                           "Lời gọi (s)": round(row["elapsed_seconds"], 3),
                           "Snapshot hoàn chỉnh": row.get("snapshot_complete", False)} for row in attempts])
    display(HTML(trial.astype(object).where(trial.notna(), "N/A").to_html(index=False, border=0)))
else:
    display(Markdown("Chưa cung cấp log thử nghiệm S2; không tự tạo kết quả minh họa."))
```

Khoảng nghỉ quota trước lời gọi không nằm trong cột thời gian lời gọi ở bảng này.
Kết quả chỉ có thể xác nhận tính tương đương của snapshot thành công trong mẫu đã
quan sát. Những lời gọi 429 không phải snapshot rỗng hợp lệ. Chưa có đủ bằng chứng
speedup tổng quát thì giữ phương án hiện hành; không tăng concurrency hoặc thử vô
hạn để tìm một kết quả đẹp. Log thử nghiệm tách biệt log benchmark dữ liệu chính.

## 1.7. Tái lập và giới hạn

Chạy `scripts/collect_m1_report.py` tạo snapshot, rồi build bằng
`requirements-book.txt`. Collector chỉ đọc, không crawl, sửa raw hay chạy M2/M3.
Quét log đầy đủ khi crawler đã checkpoint để không tranh I/O Drive. Hướng dẫn:
`docs/M1_REPORT_RUNBOOK.md` trong code repository.

Kết quả gắn manifest/audit/source SHA và timestamp. Báo cáo nêu coverage chưa đủ,
ngoại lệ S2 và phép đo chưa có, không dùng tests xanh làm bằng chứng hoàn tất
15.000 bài. Book vẫn chờ chốt các dải và kiểm chứng benchmark. Vị trí host Book
riêng cần được nhóm đối chiếu yêu cầu nộp; phiên chuẩn bị này không đổi URL,
không publish và không tự tạo repository.
