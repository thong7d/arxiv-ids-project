# HÆ¯á»šNG DáºªN CÃ€O Dá»® LIá»†U SONG SONG â€” THÃ€NH & QUANG
**DÃ nh cho: Nguyá»…n Tiáº¿n ThÃ nh (23120358) vÃ  Nguyá»…n Trá»‹nh Quang (23120345)**
*Cáº­p nháº­t: 05/11/2026 â€” Phá»‘i há»£p cÃ o song song trÃªn 3 Colab CPU riÃªng biá»‡t*

> [!IMPORTANT]
> **Äiá»u kiá»‡n báº¯t buá»™c:** Má»—i báº¡n cháº¡y trÃªn **tÃ i khoáº£n Google Colab riÃªng cá»§a cÃ¡ nhÃ¢n**, mount vÃ o **cÃ¹ng Drive chung cá»§a nhÃ³m**. Tuyá»‡t Ä‘á»‘i KHÃ”NG cháº¡y 2 worker trÃªn cÃ¹ng 1 phiÃªn Colab hay cÃ¹ng 1 tÃ i khoáº£n Google.

---

## ðŸ“Œ PHÃ‚N CÃ”NG Dáº¢I ID (ÄÃƒ CHá»T â€” KHÃ”NG THAY Äá»”I)

Theo `configs/members.csv` vÃ  báº£ng phÃ¢n cÃ´ng chÃ­nh thá»©c:

| ThÃ nh viÃªn | MSSV | Dáº£i arXiv ID | Ghi chÃº |
|:---|:---:|:---|:---|
| Pháº¡m Minh ThÃ´ng | 23120364 | `2508.17872` â†’ `2509.01046` | **Äang cÃ o** (PID: 3522 trÃªn Colab ThÃ´ng) |
| **Nguyá»…n Tiáº¿n ThÃ nh** | **23120358** | **`2509.01047` â†’ `2509.06046`** | **Báº¡n cÃ o dáº£i nÃ y** |
| **Nguyá»…n Trá»‹nh Quang** | **23120345** | **`2509.06047` â†’ `2509.11046`** | **Báº¡n cÃ o dáº£i nÃ y** |

> [!NOTE]
> Dá»¯ liá»‡u Ä‘Æ°á»£c lÆ°u theo thÆ° má»¥c mang mÃ£ bÃ i (`2509-01047/`, `2509-06047/`...) â€” 3 dáº£i hoÃ n toÃ n tÃ¡ch biá»‡t nhau, **khÃ´ng bao giá» ghi Ä‘Ã¨ dá»¯ liá»‡u cá»§a nhau** dÃ¹ cÃ¹ng mount vÃ o 1 Drive.

---

## ðŸ§° BÆ¯á»šC 0: CHUáº¨N Bá»Š TRÆ¯á»šC KHI Má»ž COLAB

### 0.1. ÄÄƒng kÃ½ Semantic Scholar API Key (cÃ¡ nhÃ¢n â€” báº¯t buá»™c)

Náº¿u chÆ°a cÃ³ key riÃªng, lÃ m ngay Ä‘á»ƒ trÃ¡nh bá»‹ giá»›i háº¡n 100 req/5 phÃºt á»Ÿ cháº¿ Ä‘á»™ áº©n danh:

1. Truy cáº­p: https://www.semanticscholar.org/product/api
2. Nháº¥n **"Request API Key"**, Ä‘iá»n email sinh viÃªn.
3. Key thÆ°á»ng Ä‘Æ°á»£c cáº¥p trong vÃ²ng **24â€“48 giá»**. Náº¿u chÆ°a cÃ³, há»‡ thá»‘ng váº«n cháº¡y Ä‘Æ°á»£c nhÆ°ng sáº½ cháº­m hÆ¡n Ä‘Ã¡ng ká»ƒ (cÃ³ thá»ƒ dá»«ng 5 phÃºt sau má»—i 100 bÃ i).

### 0.2. YÃªu cáº§u ThÃ´ng cáº¥p quyá»n Drive

- Nhá» ThÃ´ng chia sáº» thÆ° má»¥c Drive `IDS_Nhom13_Corpus_Backup` vá»›i **email Google cÃ¡ nhÃ¢n cá»§a báº¡n** (vai trÃ² **Editor**).
- Link thÆ° má»¥c Drive: https://drive.google.com/drive/folders/1NnyZolqKw5dIl_NsIW7BFMztqIXdetGI
- Sau khi Ä‘Æ°á»£c thÃªm vÃ o, thÆ° má»¥c sáº½ hiá»‡n trong **"Shared with me"** trÃªn Google Drive cá»§a báº¡n.

### 0.3. Nháº­n file bundle tá»« ThÃ´ng

ThÃ´ng sáº½ gá»­i cho báº¡n 2 file (Ä‘Ã£ cÃ³ sáºµn trong thÆ° má»¥c Drive chung):
- `ids13-code-2c4c368b0253.zip` â€” Source code bundle Ä‘Ã£ Ä‘Ã³ng gÃ³i
- `ids13-code-2c4c368b0253.sha256` â€” File checksum Ä‘á»ƒ xÃ¡c minh tÃ­nh toÃ n váº¹n

**SHA-256 chuáº©n:** `2c4c368b025326c4778b46482caef50dc27293f3dfd7e90f965087547690c1dd`

---

## âš™ï¸ BÆ¯á»šC 1: THIáº¾T Láº¬P COLAB (LÃ€M 1 Láº¦N Äáº¦U DUY NHáº¤T)

### 1.1. Má»Ÿ Google Colab vá»›i Ä‘Ãºng runtime

1. Truy cáº­p: https://colab.research.google.com
2. ÄÄƒng nháº­p báº±ng **tÃ i khoáº£n Google cÃ¡ nhÃ¢n cá»§a báº¡n**.
3. VÃ o menu **Runtime â†’ Change runtime type** â†’ Chá»n **CPU** (khÃ´ng chá»n GPU/TPU).

> [!WARNING]
> Tuyá»‡t Ä‘á»‘i chá»n CPU, khÃ´ng pháº£i GPU/TPU. Script sáº½ tá»« chá»‘i cháº¡y vÃ  bÃ¡o lá»—i náº¿u phÃ¡t hiá»‡n GPU runtime (kiá»ƒm tra `COLAB_GPU`). TiÃªu chÃ­ cháº¥m Ä‘iá»ƒm Ä‘á»“ Ã¡n yÃªu cáº§u benchmark trÃªn Colab CPU.

### 1.2. Thiáº¿t láº­p Secrets trong Colab

1. Click biá»ƒu tÆ°á»£ng ðŸ”‘ **"Secrets"** á»Ÿ thanh bÃªn trÃ¡i (hoáº·c menu **Tools â†’ Secrets**).
2. ThÃªm 2 Secrets sau:

| TÃªn Secret | GiÃ¡ trá»‹ | Báº­t "Notebook access" |
|:---|:---|:---:|
| `ARXIV_CONTACT_EMAIL` | Email sinh viÃªn cá»§a báº¡n (vÃ­ dá»¥: `23120358@student.hcmus.edu.vn`) | âœ… Báº­t |
| `SEMANTIC_SCHOLAR_API_KEY` | API key cá»§a **báº¡n** (xem bÆ°á»›c 0.1) | âœ… Báº­t |

> [!IMPORTANT]
> Má»—i báº¡n Ä‘iá»n **API Key cá»§a chÃ­nh mÃ¬nh**, khÃ´ng dÃ¹ng chung key vá»›i ThÃ´ng hay vá»›i nhau. ÄÃ¢y lÃ  lÃ½ do chÃ­nh giÃºp 3 mÃ¡y cháº¡y song song mÃ  khÃ´ng bá»‹ giá»›i háº¡n táº§n suáº¥t chung.

---

## ðŸ““ BÆ¯á»šC 2: Táº O NOTEBOOK VÃ€ CÃ€I Äáº¶T CÃC CELL

Má»Ÿ notebook má»›i trong Colab (New notebook). ThÃªm láº§n lÆ°á»£t cÃ¡c cell code sau:

---

### ðŸ“Œ CELL 1 â€” Setup: Äá»c Secrets vÃ  Mount Drive

```python
# CELL 1: Setup - Äá»c Secrets vÃ  mount Drive
import os
from google.colab import userdata, drive

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    os.environ[name] = userdata.get(name)
print('ÄÃ£ Ä‘á»c hai Secrets; khÃ´ng hiá»ƒn thá»‹ giÃ¡ trá»‹.')

drive.mount('/content/drive')

DRIVE_ROOT_PATH = '/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup'
import pathlib
DRIVE_ROOT = pathlib.Path(DRIVE_ROOT_PATH)
assert DRIVE_ROOT.is_dir(), f"KhÃ´ng tháº¥y thÆ° má»¥c Drive: {DRIVE_ROOT_PATH}\nKiá»ƒm tra láº¡i quyá»n truy cáº­p Drive."
print(f"âœ… Drive Ä‘Ã£ mount. ThÆ° má»¥c nhÃ³m: {DRIVE_ROOT}")
```

**Káº¿t quáº£ mong Ä‘á»£i:**
```
ÄÃ£ Ä‘á»c hai Secrets; khÃ´ng hiá»ƒn thá»‹ giÃ¡ trá»‹.
Mounted at /content/drive
âœ… Drive Ä‘Ã£ mount. ThÆ° má»¥c nhÃ³m: /content/drive/MyDrive/IDS_Nhom13_Corpus_Backup
```

---

### ðŸ“Œ CELL 2 â€” Source: XÃ¡c minh checksum vÃ  giáº£i nÃ©n code

> [!IMPORTANT]
> `SOURCE_SHA256` pháº£i khá»›p chÃ­nh xÃ¡c vá»›i giÃ¡ trá»‹ bÃªn dÆ°á»›i. ÄÃ¢y lÃ  phiÃªn báº£n code Ä‘Ã£ Ä‘Æ°á»£c kiá»ƒm Ä‘á»‹nh vÃ  Ä‘ang cháº¡y trÃªn mÃ¡y ThÃ´ng. Tuyá»‡t Ä‘á»‘i khÃ´ng tá»± thay Ä‘á»•i giÃ¡ trá»‹ nÃ y.

```python
# CELL 2: XÃ¡c minh checksum source vÃ  giáº£i nÃ©n
from pathlib import Path
import hashlib, zipfile

# ===========================================================
# SHA-256 CHUáº¨N Cá»¦A BUNDLE â€” KHÃ”NG ÄÆ¯á»¢C THAY Äá»”I GIÃ TRá»Š NÃ€Y
SOURCE_SHA256 = '2c4c368b025326c4778b46482caef50dc27293f3dfd7e90f965087547690c1dd'
# ===========================================================

CODE_ROOT = None
archive = DRIVE_ROOT / f'ids13-code-{SOURCE_SHA256[:12]}.zip'

assert archive.exists(), (
    f"KhÃ´ng tÃ¬m tháº¥y file bundle: {archive}\n"
    "Kiá»ƒm tra láº¡i Drive Ä‘Ã£ Ä‘Æ°á»£c chia sáº» vÃ  file Ä‘Ã£ cÃ³ trong thÆ° má»¥c."
)

actual_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
assert actual_hash == SOURCE_SHA256, (
    f"CHECKSUM MISMATCH!\n  TÃ­nh Ä‘Æ°á»£c: {actual_hash}\n  Mong Ä‘á»£i:   {SOURCE_SHA256}\n"
    "File bundle cÃ³ thá»ƒ bá»‹ há»ng. Nhá» ThÃ´ng upload láº¡i."
)

CODE_ROOT = Path('/content') / f'ids13-code-{SOURCE_SHA256[:12]}'
CODE_ROOT.mkdir(exist_ok=True)

with zipfile.ZipFile(archive) as bundle:
    for name in bundle.namelist():
        assert (CODE_ROOT / name).resolve().is_relative_to(CODE_ROOT.resolve()), \
            f"Path traversal detected: {name}"
    bundle.extractall(CODE_ROOT)

print(f'âœ… Source verified: {SOURCE_SHA256[:12]}')
print(f'   Code root: {CODE_ROOT}')
```

**Káº¿t quáº£ mong Ä‘á»£i:**
```
âœ… Source verified: 2c4c368b0253
   Code root: /content/ids13-code-2c4c368b0253
```

---

### ðŸ“Œ CELL 3 â€” CÃ i package vÃ  cháº¡y Tests

```python
# CELL 3: CÃ i Ä‘áº·t package vÃ  cháº¡y kiá»ƒm thá»­
import subprocess, sys

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), "Cháº¡y CELL 2 trÆ°á»›c!"

print("ðŸ“¦ CÃ i Ä‘áº·t package ids_arxiv...")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE_ROOT), "pytest"],
    check=True
)

print("\nðŸ§ª Cháº¡y kiá»ƒm thá»­ (pytest)...")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "--tb=short"],
    cwd=CODE_ROOT,
    capture_output=True, text=True
)
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
if result.returncode != 0:
    print("âŒ TESTS THáº¤T Báº I! LiÃªn há»‡ ThÃ´ng trÆ°á»›c khi tiáº¿p tá»¥c.")
    print(result.stderr[-1000:])
else:
    print("âœ… Táº¥t cáº£ tests Ä‘Ã£ PASS!")
```

**Káº¿t quáº£ mong Ä‘á»£i:** DÃ²ng cuá»‘i pháº£i lÃ  `âœ… Táº¥t cáº£ tests Ä‘Ã£ PASS!` (khÃ´ng cÃ³ test nÃ o FAIL).

---

### ðŸ“Œ CELL 4 â€” Launch Worker (cÃ o dáº£i ID cá»§a Báº N)

> [!IMPORTANT]
> Thay `STUDENT_ID` Ä‘Ãºng theo MSSV cá»§a báº¡n. **Chá»‰ cháº¡y cell nÃ y 1 láº§n.** Náº¿u cháº¡y láº¡i trong cÃ¹ng phiÃªn, há»‡ thá»‘ng sáº½ kiá»ƒm tra vÃ  bÃ¡o lá»—i náº¿u worker cÅ© cÃ²n Ä‘ang sá»‘ng.

#### Náº¿u báº¡n lÃ  **ThÃ nh (23120358):**
```python
# CELL 4 â€” THÃ€NH (23120358): Launch worker cÃ o dáº£i 2509.01047 â†’ 2509.06046
import subprocess, sys, json, os
from pathlib import Path

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), 'Cháº¡y CELL 2 trÆ°á»›c!'
assert CODE_ROOT.name.endswith(SOURCE_SHA256[:12]), 'Source revision mismatch'

# --- PHÃ‚N CÃ”NG CÃ NHÃ‚N ---
MY_STUDENT_ID   = "23120358"      # MSSV cá»§a ThÃ nh
MY_START_ID     = "2509.01047"    # BÃ i Ä‘áº§u tiÃªn cá»§a ThÃ nh
MY_END_ID       = "2509.06046"    # BÃ i cuá»‘i cÃ¹ng cá»§a ThÃ nh
MY_LOG_FILE     = DRIVE_ROOT / "m1-agent-23120358.log"
MY_STATUS_FILE  = DRIVE_ROOT / "m1-launch-status-23120358.json"

os.environ['IDS_SOURCE_SHA256'] = SOURCE_SHA256
os.environ['IDS_STUDENT_ID']    = MY_STUDENT_ID

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    assert os.environ.get(name), 'Secret chÆ°a Ä‘Æ°á»£c náº¡p: ' + name

# Kiá»ƒm tra worker cÅ© cÃ²n sá»‘ng khÃ´ng
if MY_STATUS_FILE.exists():
    prev = json.loads(MY_STATUS_FILE.read_text())
    prev_pid = prev.get('pid')
    if prev_pid:
        cmd_file = Path('/proc') / str(prev_pid) / 'cmdline'
        if cmd_file.exists() and b'colab_install_and_run.py' in cmd_file.read_bytes():
            raise RuntimeError(
                f'Worker cÅ© (PID {prev_pid}) Ä‘ang cháº¡y! '
                'KhÃ´ng khá»Ÿi Ä‘á»™ng thÃªm. Chuyá»ƒn sang cell Monitor Ä‘á»ƒ theo dÃµi.'
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
print(f'âœ… Worker THÃ€NH Ä‘Ã£ khá»Ÿi Ä‘á»™ng!')
print(f'   PID: {worker.pid}')
print(f'   Dáº£i: {MY_START_ID} â†’ {MY_END_ID}')
print(f'   Log: {MY_LOG_FILE}')
```

#### Náº¿u báº¡n lÃ  **Quang (23120345):**
```python
# CELL 4 â€” QUANG (23120345): Launch worker cÃ o dáº£i 2509.06047 â†’ 2509.11046
import subprocess, sys, json, os
from pathlib import Path

assert CODE_ROOT is not None and CODE_ROOT.is_dir(), 'Cháº¡y CELL 2 trÆ°á»›c!'
assert CODE_ROOT.name.endswith(SOURCE_SHA256[:12]), 'Source revision mismatch'

# --- PHÃ‚N CÃ”NG CÃ NHÃ‚N ---
MY_STUDENT_ID   = "23120345"      # MSSV cá»§a Quang
MY_START_ID     = "2509.06047"    # BÃ i Ä‘áº§u tiÃªn cá»§a Quang
MY_END_ID       = "2509.11046"    # BÃ i cuá»‘i cÃ¹ng cá»§a Quang
MY_LOG_FILE     = DRIVE_ROOT / "m1-agent-23120345.log"
MY_STATUS_FILE  = DRIVE_ROOT / "m1-launch-status-23120345.json"
# -------------------------

os.environ['IDS_SOURCE_SHA256'] = SOURCE_SHA256
os.environ['IDS_STUDENT_ID']    = MY_STUDENT_ID

for name in ('ARXIV_CONTACT_EMAIL', 'SEMANTIC_SCHOLAR_API_KEY'):
    assert os.environ.get(name), 'Secret chÆ°a Ä‘Æ°á»£c náº¡p: ' + name

# Kiá»ƒm tra worker cÅ© cÃ²n sá»‘ng khÃ´ng
if MY_STATUS_FILE.exists():
    prev = json.loads(MY_STATUS_FILE.read_text())
    prev_pid = prev.get('pid')
    if prev_pid:
        cmd_file = Path('/proc') / str(prev_pid) / 'cmdline'
        if cmd_file.exists() and b'colab_install_and_run.py' in cmd_file.read_bytes():
            raise RuntimeError(
                f'Worker cÅ© (PID {prev_pid}) Ä‘ang cháº¡y! '
                'KhÃ´ng khá»Ÿi Ä‘á»™ng thÃªm. Chuyá»ƒn sang cell Monitor Ä‘á»ƒ theo dÃµi.'
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
print(f'âœ… Worker QUANG Ä‘Ã£ khá»Ÿi Ä‘á»™ng!')
print(f'   PID: {worker.pid}')
print(f'   Dáº£i: {MY_START_ID} â†’ {MY_END_ID}')
print(f'   Log: {MY_LOG_FILE}')
```

---

### ðŸ“Œ CELL 5 â€” Monitor: Theo dÃµi tiáº¿n Ä‘á»™

Cháº¡y cell nÃ y báº¥t cá»© lÃºc nÃ o Ä‘á»ƒ kiá»ƒm tra tiáº¿n Ä‘á»™ (**khÃ´ng áº£nh hÆ°á»Ÿng Ä‘áº¿n worker Ä‘ang cháº¡y**):

#### Cho ThÃ nh:
```python
# CELL 5 â€” MONITOR (ThÃ nh 23120358)
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
    print(f"\nðŸ“‹ LOG (10 dÃ²ng cuá»‘i â€” tá»•ng {len(lines)} dÃ²ng):")
    for line in lines[-10:]:
        print(f"  {line}")
else:
    print("â³ Log chÆ°a Ä‘Æ°á»£c táº¡o â€” worker chÆ°a báº¯t Ä‘áº§u ghi log.")
```

#### Cho Quang:
```python
# CELL 5 â€” MONITOR (Quang 23120345)
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
    print(f"\nðŸ“‹ LOG (10 dÃ²ng cuá»‘i â€” tá»•ng {len(lines)} dÃ²ng):")
    for line in lines[-10:]:
        print(f"  {line}")
else:
    print("â³ Log chÆ°a Ä‘Æ°á»£c táº¡o â€” worker chÆ°a báº¯t Ä‘áº§u ghi log.")
```

---

## â™»ï¸ BÆ¯á»šC 3: KHI COLAB Bá»Š NGáº®T Káº¾T Ná»I (Resume)

Colab CPU miá»…n phÃ­ tá»± ngáº¯t sau **9â€“12 giá»**. ÄÃ¢y lÃ  Ä‘iá»u bÃ¬nh thÆ°á»ng. ToÃ n bá»™ bÃ i Ä‘Ã£ cÃ o khÃ´ng máº¥t vÃ¬ Ä‘Ã£ lÆ°u trÃªn Drive.

**TrÃ¬nh tá»± resume khi má»Ÿ láº¡i:**

1. Má»Ÿ láº¡i notebook.
2. Cháº¡y láº¡i **CELL 1** (mount Drive, Ä‘á»c Secrets).
3. Cháº¡y láº¡i **CELL 2** (xÃ¡c minh checksum â€” khÃ´ng cáº§n giáº£i nÃ©n láº¡i náº¿u `/content/ids13-code-fb0283a65ea4` váº«n cÃ²n).
4. Cháº¡y láº¡i **CELL 3** (cÃ i package â€” Colab sáº½ cÃ i láº¡i trong má»—i phiÃªn má»›i vÃ¬ `/content` bá»‹ reset).
5. Cháº¡y láº¡i **CELL 4** â€” Worker sáº½ tá»± Ä‘á»™ng nháº­n ra checkpoint vÃ  **bá» qua cÃ¡c bÃ i Ä‘Ã£ cÃ o thÃ nh cÃ´ng**, tiáº¿p tá»¥c tá»« bÃ i cÃ²n láº¡i.

> [!TIP]
> **Máº¹o:** Giá»¯ tab Colab má»Ÿ vÃ  "click" vÃ o tab Colab thá»‰nh thoáº£ng (má»—i vÃ i giá») Ä‘á»ƒ ngÄƒn Colab tá»± dá»«ng do timeout khÃ´ng tÆ°Æ¡ng tÃ¡c. Hoáº·c cÃ³ thá»ƒ dÃ¹ng tiá»‡n Ã­ch má»Ÿ rá»™ng trÃ¬nh duyá»‡t giá»¯ phiÃªn Colab.

---

## âœ… BÆ¯á»šC 4: KIá»‚M TRA SAU KHI HOÃ€N THÃ€NH

Khi log bÃ¡o táº¥t cáº£ bÃ i Ä‘Ã£ Ä‘Æ°á»£c xá»­ lÃ½, cháº¡y cell xÃ¡c minh sau:

```python
# CELL 6 â€” XÃ¡c minh tÃ­nh toÃ n váº¹n dá»¯ liá»‡u sau khi cÃ o xong
import subprocess, sys

MY_STUDENT_ID = "23120358"  # Hoáº·c "23120345" náº¿u lÃ  Quang

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
    print("âš ï¸ Validation tháº¥t báº¡i â€” xem log trÃªn vÃ  bÃ¡o ThÃ´ng.")
    print(result.stderr[-1000:])
else:
    print("âœ… ToÃ n bá»™ dá»¯ liá»‡u há»£p lá»‡!")
```

**TiÃªu chuáº©n Ä‘áº¡t (pháº£i thá»a Táº¤T Cáº¢):**
- [x] Má»i thÆ° má»¥c bÃ i trong dáº£i cá»§a báº¡n Ä‘á»u bÃ¡o `[OK] <id>: valid`.
- [x] KhÃ´ng cÃ²n báº¥t ká»³ file `.png`, `.jpg`, `.pdf`, `.eps` nÃ o trong thÆ° má»¥c `vN/`.
- [x] File `metadata.json` vÃ  `references.json` Ä‘Ãºng schema.
- [x] File `crawl_status.json` cÃ³ `"success": true` hoáº·c lá»—i Ä‘Æ°á»£c ghi nháº­n rÃµ rÃ ng.

---

## ðŸš¨ Xá»¬ LÃ CÃC Lá»–I THÆ¯á»œNG Gáº¶P

| Lá»—i | NguyÃªn nhÃ¢n | CÃ¡ch xá»­ lÃ½ |
|:---|:---|:---|
| `AssertionError: KhÃ´ng tháº¥y thÆ° má»¥c Drive` | Drive chÆ°a Ä‘Æ°á»£c chia sáº» hoáº·c chÆ°a Ä‘Æ°á»£c mount | Nhá» ThÃ´ng chia sáº» Drive; cháº¡y láº¡i CELL 1 |
| `CHECKSUM MISMATCH` | File bundle bá»‹ há»ng khi táº£i | Nhá» ThÃ´ng upload láº¡i file `.zip` vÃ  `.sha256` |
| `Secret chÆ°a Ä‘Æ°á»£c náº¡p` | ChÆ°a thÃªm Secret hoáº·c chÆ°a báº­t "Notebook access" | VÃ o Tools â†’ Secrets, báº­t "Notebook access" cho cáº£ 2 key |
| `Tests THáº¤T Báº I` | Bundle code bá»‹ lá»—i | Chá»¥p toÃ n bá»™ output vÃ  nhá» ThÃ´ng sá»­a bundle |
| Worker bÃ¡o `[FAIL]` liÃªn tiáº¿p cho nhiá»u bÃ i | arXiv/S2 rate-limit â€” HTTP 429 | BÃ¬nh thÆ°á»ng! Worker tá»± backoff 60s vÃ  tiáº¿p tá»¥c; khÃ´ng lÃ m gÃ¬ cáº£ |
| Colab ngáº¯t giá»¯a chá»«ng | Timeout session 9â€“12 giá» | Resume bÃ¬nh thÆ°á»ng theo BÆ¯á»šC 3 |
| `RuntimeError: Worker cÅ© Ä‘ang cháº¡y` | Cháº¡y láº¡i CELL 4 khi worker cÅ© cÃ²n sá»‘ng | Chuyá»ƒn sang CELL 5 Ä‘á»ƒ theo dÃµi, khÃ´ng cáº§n khá»Ÿi Ä‘á»™ng má»›i |

---

## ðŸ“Š THÃ”NG Sá» Ká»¸ THUáº¬T QUAN TRá»ŒNG (Äá»‚ THAM KHáº¢O)

Nhá»¯ng thÃ´ng sá»‘ nÃ y Ä‘Ã£ Ä‘Æ°á»£c cÃ i vÃ o source code vÃ  **báº¡n khÃ´ng cáº§n thay Ä‘á»•i**:

| Tham sá»‘ | GiÃ¡ trá»‹ | LÃ½ do |
|:---|:---:|:---|
| GiÃ£n cÃ¡ch tá»‘i thiá»ƒu giá»¯a 2 request Ä‘áº¿n arXiv | **3 giÃ¢y** | Quy Ä‘á»‹nh API Etiquette arXiv |
| GiÃ£n cÃ¡ch Semantic Scholar (cÃ³ key) | **1.05 giÃ¢y/req** | Rate limit S2 API: tá»‘i Ä‘a 1 req/s |
| GiÃ£n cÃ¡ch S2 (khÃ´ng cÃ³ key) | **100 req / 5 phÃºt** | Giá»›i háº¡n áº©n danh â€” ÄÃ‚Y LÃ€ LÃ DO pháº£i cÃ³ key! |
| Thá»i gian chá» khi gáº·p HTTP 429 | **â‰¥ 60 giÃ¢y** | Theo Retry-After header cá»§a arXiv/S2 |
| Sá»‘ láº§n thá»­ láº¡i tá»‘i Ä‘a má»—i request | **3 láº§n** | Sau Ä‘Ã³ Ä‘Ã¡nh dáº¥u `[FAIL]` vÃ  chuyá»ƒn bÃ i tiáº¿p theo |
| Sá»‘ lÆ°á»£t recovery tá»± Ä‘á»™ng sau Pass 0 | **3 lÆ°á»£t** | TÃ¡i cÃ o táº¥t cáº£ `[FAIL]` trÆ°á»›c khi káº¿t thÃºc campaign |
| Budget thá»i gian tá»‘i Ä‘a 1 phiÃªn Colab | **9 giá»** | Colab CPU miá»…n phÃ­ timeout |
| Nguá»“n táº£i mÃ£ LaTeX | `export.arxiv.org/src/` | Mirror chÃ­nh thá»©c â€” KHÃ”NG dÃ¹ng `arxiv.org` trá»±c tiáº¿p |
| Dá»¯ liá»‡u trÃ­ch dáº«n | `api.semanticscholar.org/graph/v1/paper/arXiv:{id}/references` | Chá»‰ láº¥y ref cÃ³ `externalIds.ArXiv` |

---

## ðŸ—‚ï¸ Cáº¤U TRÃšC Dá»® LIá»†U Äáº¦U RA SAU KHI CÃ€O XONG

Má»—i bÃ i bÃ¡o trong dáº£i cá»§a báº¡n sáº½ cÃ³ cáº¥u trÃºc chuáº©n sau trong Drive:

```text
IDS_Nhom13_Corpus_Backup/
â””â”€â”€ m1-final-v3/
    â””â”€â”€ raw/
        â””â”€â”€ 2509-01047/           â† ThÃ nh (tÃªn thÆ° má»¥c: yymm-id)
            â”œâ”€â”€ v1/
            â”‚   â”œâ”€â”€ main.tex
            â”‚   â”œâ”€â”€ sections.tex
            â”‚   â””â”€â”€ references.bib
            â”œâ”€â”€ v2/               â† Náº¿u bÃ i cÃ³ phiÃªn báº£n 2
            â”‚   â””â”€â”€ main.tex
            â”œâ”€â”€ metadata.json     â† TiÃªu Ä‘á», tÃ¡c giáº£, ngÃ y submit
            â”œâ”€â”€ references.json   â† Danh sÃ¡ch trÃ­ch dáº«n tá»« Semantic Scholar
            â””â”€â”€ crawl_status.json â† Tráº¡ng thÃ¡i cÃ o, checksum, kÃ­ch thÆ°á»›c
```

> [!NOTE]
> File `metadata.json` vÃ  `references.json` pháº£i cÃ³ Ä‘á»§ **táº¥t cáº£ cÃ¡c phiÃªn báº£n** cá»§a bÃ i bÃ¡o. File áº£nh (`.png`, `.jpg`, `.pdf`, `.eps`) Ä‘Ã£ Ä‘Æ°á»£c tá»± Ä‘á»™ng xÃ³a sau khi giáº£i nÃ©n â€” chá»‰ giá»¯ láº¡i file vÄƒn báº£n `.tex`, `.bib` vÃ  tÆ°Æ¡ng Ä‘Æ°Æ¡ng.

---

## ðŸ“ž KHI Cáº¦N Há»– TRá»¢

1. **ThÃ nh viÃªn trÆ°á»›c tiÃªn:** Chá»¥p áº£nh mÃ n hÃ¬nh toÃ n bá»™ output lá»—i + log 20 dÃ²ng cuá»‘i tá»« CELL 5.
2. **Gá»­i cho ThÃ´ng qua nhÃ³m chat** kÃ¨m: MSSV cá»§a báº¡n, tÃªn cell bá»‹ lá»—i, vÃ  thÃ´ng bÃ¡o lá»—i chÃ­nh xÃ¡c.
3. **ThÃ´ng sáº½:**
   - VÃ¡ code trong repo náº¿u cáº§n thiáº¿t.
   - Build bundle má»›i vÃ  thay tháº¿ file trong Drive.
   - ThÃ´ng bÃ¡o SHA-256 má»›i Ä‘á»ƒ báº¡n cáº­p nháº­t `SOURCE_SHA256` trong CELL 2.

---

## âš ï¸ NHá»®NG ÄIá»€U TUYá»†T Äá»I KHÃ”NG LÃ€M

- âŒ **KhÃ´ng** cháº¡y 2 worker trÃªn cÃ¹ng 1 Colab / cÃ¹ng 1 tÃ i khoáº£n Google.
- âŒ **KhÃ´ng** thay Ä‘á»•i giÃ¡ trá»‹ `SOURCE_SHA256` trá»« khi ThÃ´ng yÃªu cáº§u (vÃ  cung cáº¥p giÃ¡ trá»‹ má»›i).
- âŒ **KhÃ´ng** xÃ³a hoáº·c di chuyá»ƒn thÆ° má»¥c `m1-final-v3/` trÃªn Drive.
- âŒ **KhÃ´ng** cÃ o tá»« domain `arxiv.org` trá»±c tiáº¿p (pháº£i dÃ¹ng `export.arxiv.org`).
- âŒ **KhÃ´ng** dÃ¹ng GPU runtime.
- âŒ **KhÃ´ng** chia sáº» hay in ra giÃ¡ trá»‹ cá»§a 2 Secrets (`ARXIV_CONTACT_EMAIL`, `SEMANTIC_SCHOLAR_API_KEY`) trong Colab.
- âŒ **KhÃ´ng** commit dá»¯ liá»‡u raw (thÆ° má»¥c `data/`) lÃªn GitHub.


