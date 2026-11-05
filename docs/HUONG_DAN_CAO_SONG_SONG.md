# HƯỚNG DẪN CÀO DỮ LIỆU SONG SONG — THÀNH & QUANG
**Dành cho: Nguyễn Tiến Thành (23120358) và Nguyễn Trịnh Quang (23120345)**
*Cập nhật: 05/11/2026 — Phối hợp cào song song trên 3 Colab CPU riêng biệt*

> [!IMPORTANT]
> **Điều kiện bắt buộc:** Mỗi bạn chạy trên **tài khoản Google Colab riêng của cá nhân**, mount vào **cùng Drive chung của nhóm**. Tuyệt đối KHÔNG chạy 2 worker trên cùng 1 phiên Colab hay cùng 1 tài khoản Google.

---

## 📌 PHÂN CÔNG DẢI ID (ĐÃ CHỐT — KHÔNG THAY ĐỔI)

Theo `configs/members.csv` và bảng phân công chính thức:

| Thành viên | MSSV | Dải arXiv ID | Ghi chú |
|:---|:---:|:---|:---|
| Phạm Minh Thông | 23120364 | `2508.17872` → `2509.01046` | **Đang cào** (PID: 3522 trên Colab Thông) |
| **Nguyễn Tiến Thành** | **23120358** | **`2509.01047` → `2509.06046`** | **Bạn cào dải này** |
| **Nguyễn Trịnh Quang** | **23120345** | **`2509.06047` → `2509.11046`** | **Bạn cào dải này** |

> [!NOTE]
> Dữ liệu được lưu theo thư mục mang mã bài (`2509-01047/`, `2509-06047/`...) — 3 dải hoàn toàn tách biệt nhau, **không bao giờ ghi đè dữ liệu của nhau** dù cùng mount vào 1 Drive.

---

## 🧰 BƯỚC 0: CHUẨN BỊ TRƯỚC KHI MỞ COLAB

### 0.1. Đăng ký Semantic Scholar API Key (cá nhân — bắt buộc)

Nếu chưa có key riêng, làm ngay để tránh bị giới hạn 100 req/5 phút ở chế độ ẩn danh:

1. Truy cập: https://www.semanticscholar.org/product/api
2. Nhấn **"Request API Key"**, điền email sinh viên.
3. Key thường được cấp trong vòng **24–48 giờ**. Nếu chưa có, hệ thống vẫn chạy được nhưng sẽ chậm hơn đáng kể (có thể dừng 5 phút sau mỗi 100 bài).

### 0.2. Yêu cầu Thông cấp quyền Drive

- Nhờ Thông chia sẻ thư mục Drive `IDS_Nhom13_Corpus_Backup` với **email Google cá nhân của bạn** (vai trò **Editor**).
- Link thư mục Drive: https://drive.google.com/drive/folders/1NnyZolqKw5dIl_NsIW7BFMztqIXdetGI
- Sau khi được thêm vào, thư mục sẽ hiện trong **"Shared with me"** trên Google Drive của bạn.

### 0.3. Nhận file bundle từ Thông

Thông sẽ gửi cho bạn 2 file (đã có sẵn trong thư mục Drive chung):
- `ids13-code-692deb8d6f67.zip` — Source code bundle đã đóng gói
- `ids13-code-692deb8d6f67.sha256` — File checksum để xác minh tính toàn vẹn

**SHA-256 chuẩn:** `692deb8d6f67971277ee1caaf2afb5413dfc5a8108a3134954a0a601f7a99662`

---

## ⚙️ BƯỚC 1: THIẾT LẬP COLAB (LÀM 1 LẦN ĐẦU DUY NHẤT)

### 1.1. Mở Google Colab với đúng runtime

1. Truy cập: https://colab.research.google.com
2. Đăng nhập bằng **tài khoản Google cá nhân của bạn**.
3. Vào menu **Runtime → Change runtime type** → Chọn **CPU** (không chọn GPU/TPU).

> [!WARNING]
> Tuyệt đối chọn CPU, không phải GPU/TPU. Script sẽ từ chối chạy và báo lỗi nếu phát hiện GPU runtime (kiểm tra `COLAB_GPU`). Tiêu chí chấm điểm đồ án yêu cầu benchmark trên Colab CPU.

### 1.2. Thiết lập Secrets trong Colab

1. Click biểu tượng 🔑 **"Secrets"** ở thanh bên trái (hoặc menu **Tools → Secrets**).
2. Thêm 2 Secrets sau:

| Tên Secret | Giá trị | Bật "Notebook access" |
|:---|:---|:---:|
| `ARXIV_CONTACT_EMAIL` | Email sinh viên của bạn (ví dụ: `23120358@student.hcmus.edu.vn`) | ✅ Bật |
| `SEMANTIC_SCHOLAR_API_KEY` | API key của **bạn** (xem bước 0.1) | ✅ Bật |

> [!IMPORTANT]
> Mỗi bạn điền **API Key của chính mình**, không dùng chung key với Thông hay với nhau. Đây là lý do chính giúp 3 máy chạy song song mà không bị giới hạn tần suất chung.

---

## 📓 BƯỚC 2: TẠO NOTEBOOK VÀ CÀI ĐẶT CÁC CELL

Mở notebook mới trong Colab (New notebook). Thêm lần lượt các cell code sau:

---

### 📌 CELL 1 — Setup: Đọc Secrets và Mount Drive

```python
# CELL 1: Setup - Đọc Secrets và mount Drive
import os
from google.colab import userdata, drive

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    os.environ[name] = userdata.get(name)
print('Đã đọc hai Secrets; không hiển thị giá trị.')

drive.mount('/content/drive')

DRIVE_ROOT_PATH = '/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup'
import pathlib
DRIVE_ROOT = pathlib.Path(DRIVE_ROOT_PATH)
assert DRIVE_ROOT.is_dir(), f"Không thấy thư mục Drive: {DRIVE_ROOT_PATH}\nKiểm tra lại quyền truy cập Drive."
print(f"✅ Drive đã mount. Thư mục nhóm: {DRIVE_ROOT}")
```

**Kết quả mong đợi:**
```
Đã đọc hai Secrets; không hiển thị giá trị.
Mounted at /content/drive
✅ Drive đã mount. Thư mục nhóm: /content/drive/MyDrive/IDS_Nhom13_Corpus_Backup
```

---

### 📌 CELL 2 — Source: Xác minh checksum và giải nén code

> [!IMPORTANT]
> `SOURCE_SHA256` phải khớp chính xác với giá trị bên dưới. Đây là phiên bản code đã được kiểm định và đang chạy trên máy Thông. Tuyệt đối không tự thay đổi giá trị này.

```python
# CELL 2: Xác minh checksum source và giải nén
from pathlib import Path
import hashlib, zipfile

# ===========================================================
# SHA-256 CHUẨN CỦA BUNDLE — KHÔNG ĐƯỢC THAY ĐỔI GIÁ TRỊ NÀY
SOURCE_SHA256 = '692deb8d6f67971277ee1caaf2afb5413dfc5a8108a3134954a0a601f7a99662'
# ===========================================================

CODE_ROOT = None
archive = DRIVE_ROOT / f'ids13-code-{SOURCE_SHA256[:12]}.zip'

assert archive.exists(), (
    f"Không tìm thấy file bundle: {archive}\n"
    "Kiểm tra lại Drive đã được chia sẻ và file đã có trong thư mục."
)

actual_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
assert actual_hash == SOURCE_SHA256, (
    f"CHECKSUM MISMATCH!\n  Tính được: {actual_hash}\n  Mong đợi:   {SOURCE_SHA256}\n"
    "File bundle có thể bị hỏng. Nhờ Thông upload lại."
)

CODE_ROOT = Path('/content') / f'ids13-code-{SOURCE_SHA256[:12]}'
CODE_ROOT.mkdir(exist_ok=True)

with zipfile.ZipFile(archive) as bundle:
    for name in bundle.namelist():
        assert (CODE_ROOT / name).resolve().is_relative_to(CODE_ROOT.resolve()), \
            f"Path traversal detected: {name}"
    bundle.extractall(CODE_ROOT)

print(f'✅ Source verified: {SOURCE_SHA256[:12]}')
print(f'   Code root: {CODE_ROOT}')
```

**Kết quả mong đợi:**
```
✅ Source verified: 692deb8d6f67
   Code root: /content/ids13-code-692deb8d6f67
```

---

### 📌 CELL 3 — Cài package và chạy Tests

```python
# CELL 3: Cài đặt package và chạy kiểm thử
import subprocess, sys

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), "Chạy CELL 2 trước!"

print("📦 Cài đặt package ids_arxiv...")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE_ROOT), "pytest"],
    check=True
)

print("\n🧪 Chạy kiểm thử (pytest)...")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "--tb=short"],
    cwd=CODE_ROOT,
    capture_output=True, text=True
)
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
if result.returncode != 0:
    print("❌ TESTS THẤT BẠI! Liên hệ Thông trước khi tiếp tục.")
    print(result.stderr[-1000:])
else:
    print("✅ Tất cả tests đã PASS!")
```

**Kết quả mong đợi:** Dòng cuối phải là `✅ Tất cả tests đã PASS!` (không có test nào FAIL).

---

### 📌 CELL 4 — Launch Worker (cào dải ID của BẠN)

> [!IMPORTANT]
> Thay `STUDENT_ID` đúng theo MSSV của bạn. **Chỉ chạy cell này 1 lần.** Nếu chạy lại trong cùng phiên, hệ thống sẽ kiểm tra và báo lỗi nếu worker cũ còn đang sống.

#### Nếu bạn là **Thành (23120358):**
```python
# CELL 4 — THÀNH (23120358): Launch worker cào dải 2509.01047 → 2509.06046
import subprocess, sys, json, os
from pathlib import Path

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), 'Chạy CELL 2 trước!'
assert CODE_ROOT.name.endswith(SOURCE_SHA256[:12]), 'Source revision mismatch'

# --- PHÂN CÔNG CÁ NHÂN ---
MY_STUDENT_ID   = "23120358"      # MSSV của Thành
MY_START_ID     = "2509.01047"    # Bài đầu tiên của Thành
MY_END_ID       = "2509.06046"    # Bài cuối cùng của Thành
MY_LOG_FILE     = DRIVE_ROOT / "m1-agent-23120358.log"
MY_STATUS_FILE  = DRIVE_ROOT / "m1-launch-status-23120358.json"

os.environ['IDS_SOURCE_SHA256'] = SOURCE_SHA256
os.environ['IDS_STUDENT_ID']    = MY_STUDENT_ID

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    assert os.environ.get(name), 'Secret chưa được nạp: ' + name

# Kiểm tra worker cũ còn sống không
if MY_STATUS_FILE.exists():
    prev = json.loads(MY_STATUS_FILE.read_text())
    prev_pid = prev.get('pid')
    if prev_pid:
        cmd_file = Path('/proc') / str(prev_pid) / 'cmdline'
        if cmd_file.exists() and b'colab_install_and_run.py' in cmd_file.read_bytes():
            raise RuntimeError(
                f'Worker cũ (PID {prev_pid}) đang chạy! '
                'Không khởi động thêm. Chuyển sang cell Monitor để theo dõi.'
            )

log_handle = MY_LOG_FILE.open('a', buffering=1)
worker = subprocess.Popen(
    [
        sys.executable,
        str(CODE_ROOT / 'scripts/colab_install_and_run.py'),
        '--root', str(DRIVE_ROOT),
        '--student-id', MY_STUDENT_ID,
        '--log-suffix', MY_STUDENT_ID,
    ],
    cwd=CODE_ROOT,
    stdout=log_handle,
    stderr=subprocess.STDOUT,
    env=os.environ.copy()
)
print(f'✅ Worker THÀNH đã khởi động!')
print(f'   PID: {worker.pid}')
print(f'   Dải: {MY_START_ID} → {MY_END_ID}')
print(f'   Log: {MY_LOG_FILE}')
```

#### Nếu bạn là **Quang (23120345):**
```python
# CELL 4 — QUANG (23120345): Launch worker cào dải 2509.06047 → 2509.11046
import subprocess, sys, json, os
from pathlib import Path

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), 'Chạy CELL 2 trước!'
assert CODE_ROOT.name.endswith(SOURCE_SHA256[:12]), 'Source revision mismatch'

# --- PHÂN CÔNG CÁ NHÂN ---
MY_STUDENT_ID   = "23120345"      # MSSV của Quang
MY_START_ID     = "2509.06047"    # Bài đầu tiên của Quang
MY_END_ID       = "2509.11046"    # Bài cuối cùng của Quang
MY_LOG_FILE     = DRIVE_ROOT / "m1-agent-23120345.log"
MY_STATUS_FILE  = DRIVE_ROOT / "m1-launch-status-23120345.json"
# -------------------------

os.environ['IDS_SOURCE_SHA256'] = SOURCE_SHA256
os.environ['IDS_STUDENT_ID']    = MY_STUDENT_ID

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    assert os.environ.get(name), 'Secret chưa được nạp: ' + name

# Kiểm tra worker cũ còn sống không
if MY_STATUS_FILE.exists():
    prev = json.loads(MY_STATUS_FILE.read_text())
    prev_pid = prev.get('pid')
    if prev_pid:
        cmd_file = Path('/proc') / str(prev_pid) / 'cmdline'
        if cmd_file.exists() and b'colab_install_and_run.py' in cmd_file.read_bytes():
            raise RuntimeError(
                f'Worker cũ (PID {prev_pid}) đang chạy! '
                'Không khởi động thêm. Chuyển sang cell Monitor để theo dõi.'
            )

log_handle = MY_LOG_FILE.open('a', buffering=1)
worker = subprocess.Popen(
    [
        sys.executable,
        str(CODE_ROOT / 'scripts/colab_install_and_run.py'),
        '--root', str(DRIVE_ROOT),
        '--student-id', MY_STUDENT_ID,
        '--log-suffix', MY_STUDENT_ID,
    ],
    cwd=CODE_ROOT,
    stdout=log_handle,
    stderr=subprocess.STDOUT,
    env=os.environ.copy()
)
print(f'✅ Worker QUANG đã khởi động!')
print(f'   PID: {worker.pid}')
print(f'   Dải: {MY_START_ID} → {MY_END_ID}')
print(f'   Log: {MY_LOG_FILE}')
```

---

### 📌 CELL 5 — Monitor: Theo dõi tiến độ

Chạy cell này bất cứ lúc nào để kiểm tra tiến độ (**không ảnh hưởng đến worker đang chạy**):

#### Cho Thành:
```python
# CELL 5 — MONITOR (Thành 23120358)
import json
from pathlib import Path

MY_STUDENT_ID = "23120358"
MY_LOG_FILE   = DRIVE_ROOT / f"m1-agent-{MY_STUDENT_ID}.log"

# Status files
for fname in (
    f'm1-launch-status-{MY_STUDENT_ID}.json',
    'm1-final-v3/raw/crawl_summary.json',
):
    p = DRIVE_ROOT / fname
    if p.exists():
        val = json.loads(p.read_text())
        val.pop('failed_ids', None)
        print(f"[{fname}]\n  {json.dumps(val, ensure_ascii=False, indent=2)}\n")

# Tail log
if MY_LOG_FILE.exists():
    log_text = MY_LOG_FILE.read_text(errors='replace')
    lines = log_text.strip().splitlines()
    print(f"\n📋 LOG (10 dòng cuối — tổng {len(lines)} dòng):")
    for line in lines[-10:]:
        print(f"  {line}")
else:
    print("⏳ Log chưa được tạo — worker chưa bắt đầu ghi log.")
```

#### Cho Quang:
```python
# CELL 5 — MONITOR (Quang 23120345)
import json
from pathlib import Path

MY_STUDENT_ID = "23120345"
MY_LOG_FILE   = DRIVE_ROOT / f"m1-agent-{MY_STUDENT_ID}.log"

for fname in (
    f'm1-launch-status-{MY_STUDENT_ID}.json',
    'm1-final-v3/raw/crawl_summary.json',
):
    p = DRIVE_ROOT / fname
    if p.exists():
        val = json.loads(p.read_text())
        val.pop('failed_ids', None)
        print(f"[{fname}]\n  {json.dumps(val, ensure_ascii=False, indent=2)}\n")

if MY_LOG_FILE.exists():
    log_text = MY_LOG_FILE.read_text(errors='replace')
    lines = log_text.strip().splitlines()
    print(f"\n📋 LOG (10 dòng cuối — tổng {len(lines)} dòng):")
    for line in lines[-10:]:
        print(f"  {line}")
else:
    print("⏳ Log chưa được tạo — worker chưa bắt đầu ghi log.")
```

---

## ♻️ BƯỚC 3: KHI COLAB BỊ NGẮT KẾT NỐI (Resume)

Colab CPU miễn phí tự ngắt sau **9–12 giờ**. Đây là điều bình thường. Toàn bộ bài đã cào không mất vì đã lưu trên Drive.

**Trình tự resume khi mở lại:**

1. Mở lại notebook.
2. Chạy lại **CELL 1** (mount Drive, đọc Secrets).
3. Chạy lại **CELL 2** (xác minh checksum — không cần giải nén lại nếu `/content/ids13-code-fb0283a65ea4` vẫn còn).
4. Chạy lại **CELL 3** (cài package — Colab sẽ cài lại trong mỗi phiên mới vì `/content` bị reset).
5. Chạy lại **CELL 4** — Worker sẽ tự động nhận ra checkpoint và **bỏ qua các bài đã cào thành công**, tiếp tục từ bài còn lại.

> [!TIP]
> **Mẹo:** Giữ tab Colab mở và "click" vào tab Colab thỉnh thoảng (mỗi vài giờ) để ngăn Colab tự dừng do timeout không tương tác. Hoặc có thể dùng tiện ích mở rộng trình duyệt giữ phiên Colab.

---

## ✅ BƯỚC 4: KIỂM TRA SAU KHI HOÀN THÀNH

Khi log báo tất cả bài đã được xử lý, chạy cell xác minh sau:

```python
# CELL 6 — Xác minh tính toàn vẹn dữ liệu sau khi cào xong
import subprocess, sys

MY_STUDENT_ID = "23120358"  # Hoặc "23120345" nếu là Quang

result = subprocess.run(
    [
        sys.executable, "-m", "ids_arxiv", "validate",
        "--stage", "raw",
        "--path", str(DRIVE_ROOT / "m1-final-v3/raw"),
    ],
    cwd=CODE_ROOT,
    capture_output=True, text=True
)
print(result.stdout[-5000:])
if result.returncode != 0:
    print("⚠️ Validation thất bại — xem log trên và báo Thông.")
    print(result.stderr[-1000:])
else:
    print("✅ Toàn bộ dữ liệu hợp lệ!")
```

**Tiêu chuẩn đạt (phải thỏa TẤT CẢ):**
- [x] Mọi thư mục bài trong dải của bạn đều báo `[OK] <id>: valid`.
- [x] Không còn bất kỳ file `.png`, `.jpg`, `.pdf`, `.eps` nào trong thư mục `vN/`.
- [x] File `metadata.json` và `references.json` đúng schema.
- [x] File `crawl_status.json` có `"success": true` hoặc lỗi được ghi nhận rõ ràng.

---

## 🚨 XỬ LÝ CÁC LỖI THƯỜNG GẶP

| Lỗi | Nguyên nhân | Cách xử lý |
|:---|:---|:---|
| `AssertionError: Không thấy thư mục Drive` | Drive chưa được chia sẻ hoặc chưa được mount | Nhờ Thông chia sẻ Drive; chạy lại CELL 1 |
| `CHECKSUM MISMATCH` | File bundle bị hỏng khi tải | Nhờ Thông upload lại file `.zip` và `.sha256` |
| `Secret chưa được nạp` | Chưa thêm Secret hoặc chưa bật "Notebook access" | Vào Tools → Secrets, bật "Notebook access" cho cả 2 key |
| `Tests THẤT BẠI` | Bundle code bị lỗi | Chụp toàn bộ output và nhờ Thông sửa bundle |
| Worker báo `[FAIL]` liên tiếp cho nhiều bài | arXiv/S2 rate-limit — HTTP 429 | Bình thường! Worker tự backoff 60s và tiếp tục; không làm gì cả |
| Colab ngắt giữa chừng | Timeout session 9–12 giờ | Resume bình thường theo BƯỚC 3 |
| `RuntimeError: Worker cũ đang chạy` | Chạy lại CELL 4 khi worker cũ còn sống | Chuyển sang CELL 5 để theo dõi, không cần khởi động mới |

---

## 📊 THÔNG SỐ KỸ THUẬT QUAN TRỌNG (ĐỂ THAM KHẢO)

Những thông số này đã được cài vào source code và **bạn không cần thay đổi**:

| Tham số | Giá trị | Lý do |
|:---|:---:|:---|
| Giãn cách tối thiểu giữa 2 request đến arXiv | **3 giây** | Quy định API Etiquette arXiv |
| Giãn cách Semantic Scholar (có key) | **1.05 giây/req** | Rate limit S2 API: tối đa 1 req/s |
| Giãn cách S2 (không có key) | **100 req / 5 phút** | Giới hạn ẩn danh — ĐÂY LÀ LÝ DO phải có key! |
| Thời gian chờ khi gặp HTTP 429 | **≥ 60 giây** | Theo Retry-After header của arXiv/S2 |
| Số lần thử lại tối đa mỗi request | **3 lần** | Sau đó đánh dấu `[FAIL]` và chuyển bài tiếp theo |
| Số lượt recovery tự động sau Pass 0 | **3 lượt** | Tái cào tất cả `[FAIL]` trước khi kết thúc campaign |
| Budget thời gian tối đa 1 phiên Colab | **9 giờ** | Colab CPU miễn phí timeout |
| Nguồn tải mã LaTeX | `export.arxiv.org/src/` | Mirror chính thức — KHÔNG dùng `arxiv.org` trực tiếp |
| Dữ liệu trích dẫn | `api.semanticscholar.org/graph/v1/paper/arXiv:{id}/references` | Chỉ lấy ref có `externalIds.ArXiv` |

---

## 🗂️ CẤU TRÚC DỮ LIỆU ĐẦU RA SAU KHI CÀO XONG

Mỗi bài báo trong dải của bạn sẽ có cấu trúc chuẩn sau trong Drive:

```text
IDS_Nhom13_Corpus_Backup/
└── m1-final-v3/
    └── raw/
        └── 2509-01047/           ← Thành (tên thư mục: yymm-id)
            ├── v1/
            │   ├── main.tex
            │   ├── sections.tex
            │   └── references.bib
            ├── v2/               ← Nếu bài có phiên bản 2
            │   └── main.tex
            ├── metadata.json     ← Tiêu đề, tác giả, ngày submit
            ├── references.json   ← Danh sách trích dẫn từ Semantic Scholar
            └── crawl_status.json ← Trạng thái cào, checksum, kích thước
```

> [!NOTE]
> File `metadata.json` và `references.json` phải có đủ **tất cả các phiên bản** của bài báo. File ảnh (`.png`, `.jpg`, `.pdf`, `.eps`) đã được tự động xóa sau khi giải nén — chỉ giữ lại file văn bản `.tex`, `.bib` và tương đương.

---

## 📞 KHI CẦN HỖ TRỢ

1. **Thành viên trước tiên:** Chụp ảnh màn hình toàn bộ output lỗi + log 20 dòng cuối từ CELL 5.
2. **Gửi cho Thông qua nhóm chat** kèm: MSSV của bạn, tên cell bị lỗi, và thông báo lỗi chính xác.
3. **Thông sẽ:**
   - Vá code trong repo nếu cần thiết.
   - Build bundle mới và thay thế file trong Drive.
   - Thông báo SHA-256 mới để bạn cập nhật `SOURCE_SHA256` trong CELL 2.

---

## ⚠️ NHỮNG ĐIỀU TUYỆT ĐỐI KHÔNG LÀM

- ❌ **Không** chạy 2 worker trên cùng 1 Colab / cùng 1 tài khoản Google.
- ❌ **Không** thay đổi giá trị `SOURCE_SHA256` trừ khi Thông yêu cầu (và cung cấp giá trị mới).
- ❌ **Không** xóa hoặc di chuyển thư mục `m1-final-v3/` trên Drive.
- ❌ **Không** cào từ domain `arxiv.org` trực tiếp (phải dùng `export.arxiv.org`).
- ❌ **Không** dùng GPU runtime.
- ❌ **Không** chia sẻ hay in ra giá trị của 2 Secrets (`ARXIV_CONTACT_EMAIL`, `SEMANTIC_SCHOLAR_API_KEY`) trong Colab.
- ❌ **Không** commit dữ liệu raw (thư mục `data/`) lên GitHub.
