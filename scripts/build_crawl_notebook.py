"""Generate the thin three-cell Colab notebook from a pinned source bundle."""

import argparse
import ast
import json
from pathlib import Path


def notebook(sha):
    introduction = """# Nhóm 13 · M1 — Cào dữ liệu trên Colab CPU

**Chỉ chọn MSSV ở cell 1 rồi Runtime → Run all.** Lần đầu Google vẫn có thể hỏi
quyền Secrets/Drive; không thể bỏ qua các hộp cấp quyền này bằng mã.

- Mỗi tài khoản dùng email/key S2 cá nhân trong Secrets. Chọn MSSV là chọn dải dữ liệu;
  ai cũng có thể hỗ trợ dải của bạn khác, nhưng **mỗi dải chỉ một runtime** tại một thời điểm.
- Mỗi phiên chỉ xử lý 5.000 ID đã chọn: tận dụng cache → crawl hữu hạn → audit có resume
  → lưu ngoại lệ và dừng. Đổi MSSV trong cùng runtime sẽ dừng có kiểm soát phiên cũ.
- Worker chạy nền, không bị dừng chỉ vì cell Monitor kết thúc; không dùng cell
  "giữ máy sống". Google vẫn có thể thu hồi runtime. Chạy lại để resume.
- Bảng thời gian gồm cache/import, metadata, source, references, ngày references,
  kiểm tra và ghi Drive; mean/p50/p95 tính theo lượt xử lý, không giả làm cold benchmark.
- Output ổn định: `m1-team-v4/<MSSV>/main/full/<owner>/`; pilot dùng ngay dữ liệu này,
  không tạo corpus pilot riêng. File tạm ở SSD local; checkpoint/log benchmark được giữ.
- arXiv chia lượt UTC giữa ba MSSV để không cộng dồn quota. Chạy riêng muốn bỏ
  thời gian chờ phải xác nhận các crawler khác đã dừng qua script, không tự suy đoán.

Notebook chỉ khởi chạy/hiển thị. Crawl, audit và checkpoint nằm trong script Python;
parser, matching và xuất bản là công việc riêng sau M1. Ngoại lệ không được tính thành công.
"""
    setup = '''# @title 1. Chọn MSSV · Chuẩn bị Colab và mã nguồn
STUDENT_ID = "23120364" # @param ["23120364", "23120358", "23120345"]
IDS_SETUP_READY = False
import os, sys, hashlib, zipfile, subprocess
from pathlib import Path
from google.colab import userdata, drive

assert os.environ.get("COLAB_GPU", "0") in ("", "0"), "Chọn runtime CPU, không GPU."
for name in ("ARXIV_CONTACT_EMAIL", "SEMANTIC_SCHOLAR_API_KEY"):
    try:
        os.environ[name] = userdata.get(name)
    except userdata.TimeoutException:
        if not os.environ.get(name):
            raise
        print("MCP timeout: giữ Secret đã được nạp hợp lệ trong runtime:", name,
              "| Nếu vừa đổi Secret, hãy chạy Setup từ giao diện Colab.")
drive.mount("/content/drive")
DRIVE_ROOT = Path("/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup")
assert DRIVE_ROOT.is_dir(), "Thêm shortcut thư mục Drive chung vào My Drive với đúng tên."
SOURCE_SHA256 = "__SHA__"
archive = DRIVE_ROOT / ("ids13-code-" + SOURCE_SHA256[:12] + ".zip")
assert hashlib.sha256(archive.read_bytes()).hexdigest() == SOURCE_SHA256, "Source checksum mismatch"
CODE_ROOT = Path("/content") / ("ids13-code-" + SOURCE_SHA256[:12])
CODE_ROOT.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as bundle:
    for item in bundle.infolist():
        assert (CODE_ROOT/item.filename).resolve().is_relative_to(CODE_ROOT.resolve()), "Unsafe archive path"
        assert (item.external_attr >> 16) & 0o170000 != 0o120000, "Archive symlink"
    bundle.extractall(CODE_ROOT)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(CODE_ROOT/"requirements-colab-m1.txt")], check=True)
os.environ["PYTHONPATH"] = str(CODE_ROOT/"src")
os.environ["IDS_SOURCE_SHA256"] = SOURCE_SHA256
os.environ["IDS_WORKFLOW_MODE"] = "bounded"
IDS_SETUP_READY = True
print("Sẵn sàng:", STUDENT_ID, "| source", SOURCE_SHA256[:12], "| không hiển thị Secrets")
'''.replace("__SHA__", sha)
    launch = '''# @title 2. Tự kiểm tra → cào hữu hạn → audit → chốt ngoại lệ (một MSSV)
assert globals().get("IDS_SETUP_READY", False), "Setup chưa thành công; không dùng lại CODE_ROOT cũ."
import importlib.util
spec = importlib.util.spec_from_file_location("_ids13_colab_entry", CODE_ROOT/"scripts/colab_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
APP = entry.start(STUDENT_ID, DRIVE_ROOT, CODE_ROOT)
'''
    monitor = '''# @title 3. Tiến độ · Tốc độ từng khâu · Độ trễ mỗi lượt paper
APP.monitor(seconds=30)
# Xem tiếp: chạy lại cell này. Dừng có kiểm soát (không chạy mặc định):
# APP.stop(confirm_run_id="copy chính xác run_id từ trạng thái")
'''
    cells = []
    for index, source in enumerate((introduction, setup, launch, monitor)):
        kind = "markdown" if index == 0 else "code"
        if kind == "code":
            ast.parse(source)
        cell = {"cell_type": kind, "id": f"ids13-crawl-{index}", "metadata": {"id": f"ids13-crawl-{index}"},
                "source": source.splitlines(keepends=True)}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    return {"cells": cells, "metadata": {"colab": {"name": "IDS13_M1_Colab.ipynb", "provenance": []},
             "kernelspec": {"name": "python3", "display_name": "Python 3"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    # This script is a bulk notebook serialization/generation step.
    target = Path(__file__).resolve().parents[1] / "notebooks/IDS13_M1_Colab.ipynb"
    value = notebook(args.sha)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        # Preserve notebook identity and any user-added cells/metadata. Only
        # update the four managed cells, without deleting unrelated user work.
        for old, new in zip(existing["cells"][:4], value["cells"]):
            old["source"] = new["source"]
            if old["cell_type"] == "code":
                old.update(outputs=[], execution_count=None)
        value = existing
    target.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
