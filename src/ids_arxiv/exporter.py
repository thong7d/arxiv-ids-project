"""Sharded Parquet exporter and Hugging Face Dataset Card builder (6-table spec)."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .discovery import load_members, to_arxiv_id, to_dir_id
from .schemas.parquet import TABLE_SCHEMAS

TARGET_SHARD_BYTES = 180 * 1024 * 1024  # ~180 MB target per Parquet shard (< 200 MB Hub viewer optimum)


def _infer_element_kind(element_id: str, explicit_kinds: Optional[Dict[str, str]]) -> str:
    if explicit_kinds and element_id in explicit_kinds:
        return str(explicit_kinds[element_id])
    lower = element_id.lower()
    for token, kind in (
        ("root", "document"),
        ("-doc", "document"),
        ("#doc", "document"),
        ("chap", "chapter"),
        ("subsubsec", "subsubsection"),
        ("subsec", "subsection"),
        ("sec", "section"),
        ("par", "paragraph"),
        ("list", "list"),
        ("item", "item"),
        ("eq", "formula"),
        ("form", "formula"),
        ("fig", "figure"),
        ("tab", "figure"),
        ("sent", "sentence"),
    ):
        if token in lower:
            return kind
    return "sentence"


def _parse_simple_bibtex(bib_text: str) -> List[Dict[str, Any]]:
    """Lightweight fallback parser when bibtex_entries.json is not present alongside refs.bib."""
    entries: List[Dict[str, Any]] = []
    pattern = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", re.M)
    matches = list(pattern.finditer(bib_text))
    for idx, match in enumerate(matches):
        entry_type = match.group(1).lower()
        if entry_type in {"comment", "preamble", "string"}:
            continue
        key = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(bib_text)
        body = bib_text[start:end]
        fields: Dict[str, str] = {}
        for fmatch in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\"|(\d+))",
            body,
            re.S,
        ):
            fname = fmatch.group(1).lower()
            fval = fmatch.group(2) or fmatch.group(3) or fmatch.group(4) or ""
            fields[fname] = " ".join(fval.split())
        authors_raw = fields.get("author", "")
        authors = [a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()] if authors_raw else []
        year_val: Optional[int] = None
        if fields.get("year") and re.search(r"\b(19|20)\d{2}\b", fields["year"]):
            year_val = int(re.search(r"\b(?:19|20)\d{2}\b", fields["year"]).group(0))  # type: ignore[union-attr]
        entries.append(
            {
                "citation_key": key,
                "entry_type": entry_type,
                "title": fields.get("title", ""),
                "authors": authors,
                "year": year_val,
                "doi": fields.get("doi", ""),
                "journal": fields.get("journal") or fields.get("booktitle", ""),
                "url": fields.get("url", ""),
            }
        )
    return entries


def _write_sharded_table(rows: List[Dict[str, Any]], schema: pa.Schema, out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old_file in out_dir.glob("*.parquet"):
        old_file.unlink()
    if not rows:
        empty_cols = {name: [] for name in schema.names}
        empty_table = pa.Table.from_pydict(empty_cols, schema=schema)
        shard_path = out_dir / "part-00000.parquet"
        pq.write_table(empty_table, shard_path, compression="zstd")
        return {"rows": 0, "shards": 1, "bytes": shard_path.stat().st_size}

    full_table = pa.Table.from_pylist(rows, schema=schema)
    total_bytes = max(1, full_table.nbytes)
    num_shards = max(1, (total_bytes + TARGET_SHARD_BYTES - 1) // TARGET_SHARD_BYTES)
    rows_per_shard = max(1, (full_table.num_rows + num_shards - 1) // num_shards)
    written_bytes = 0
    shard_count = 0
    for start in range(0, full_table.num_rows, rows_per_shard):
        piece = full_table.slice(start, rows_per_shard)
        shard_path = out_dir / f"part-{shard_count:05d}.parquet"
        tmp_path = shard_path.with_suffix(".parquet.tmp")
        pq.write_table(piece, tmp_path, compression="zstd")
        tmp_path.replace(shard_path)
        written_bytes += shard_path.stat().st_size
        shard_count += 1
    return {"rows": full_table.num_rows, "shards": shard_count, "bytes": written_bytes}


def build_dataset_card(
    student_id: str,
    member_name: str,
    start_id: str,
    end_id: str,
    table_stats: Dict[str, Dict[str, Any]],
) -> str:
    configs_yaml = []
    for table_name in TABLE_SCHEMAS:
        configs_yaml.extend(
            [
                f"- config_name: {table_name}",
                "  data_files:",
                "  - split: train",
                f"    path: data/{table_name}/*.parquet",
            ]
        )
    m2_ready = table_stats["elements"]["rows"] > 0 or table_stats["bibtex"]["rows"] > 0
    m3_ready = table_stats["predictions"]["rows"] > 0
    stage_note = (
        "Đầy đủ cả 3 Milestone (M1 + M2 + M3)."
        if (m2_ready and m3_ready)
        else (
            "Đã hoàn tất dữ liệu thực nghiệm M1 (`papers`, `references`); các bảng M2/M3 đang ở trạng thái khung đúng chuẩn schema PyArrow và sẽ được cập nhật khi hoàn tất M2/M3."
            if not m2_ready
            else "Đã hoàn tất M1 + M2; bảng `predictions` (M3) sẽ được cập nhật sau bước huấn luyện."
        )
    )
    rows_md = "\n".join(
        f"| `{t}` | {s['rows']:,} | {s['shards']} | {s['bytes']:,} |"
        for t, s in table_stats.items()
    )
    return (
        "---\n"
        "language:\n"
        "- en\n"
        "pretty_name: "
        f"\"IDS Nhóm 13 — arXiv Corpus ({member_name})\"\n"
        "tags:\n"
        "- arxiv\n"
        "- latex-hierarchy\n"
        "- citation-matching\n"
        "- hcmus-ids\n"
        "configs:\n"
        + "\n".join(configs_yaml)
        + "\n---\n\n"
        f"# Dataset Đồ án Nhập môn Khoa học Dữ liệu — Nhóm 13 ({member_name})\n\n"
        "## 1. Thông tin Dải dữ liệu & Trạng thái\n\n"
        f"- **Thành viên phụ trách dải ID:** {member_name}\n"
        f"- **Dải arXiv ID được phân công:** `{start_id}` → `{end_id}`\n"
        f"- **Trạng thái hiện tại:** {stage_note}\n"
        "- **Kho mã nguồn chung:** https://github.com/thong7d/arxiv-ids-project\n"
        "- **Báo cáo Jupyter Book:** https://thong7d.github.io/arxiv-ids-project/\n\n"
        "## 2. Thống kê 6 Bảng Sharded Parquet (ZSTD)\n\n"
        "| Bảng (`config_name`) | Số dòng | Số shard | Dung lượng nén (bytes) |\n"
        "|:---|---:|---:|---:|\n"
        f"{rows_md}\n\n"
        "## 3. Hướng dẫn Đọc dữ liệu (Streaming / Datasets)\n\n"
        "```python\n"
        "from datasets import load_dataset\n\n"
        "for cfg in ('papers', 'references', 'elements', 'hierarchy', 'bibtex', 'predictions'):\n"
        "    ds = load_dataset('<username>/<repo-name>', cfg, split='train', streaming=True)\n"
        "    print(cfg, next(iter(ds), None))\n"
        "```\n\n"
        "## 4. Nguồn gốc & Lưu ý Giấy phép\n\n"
        "- Metadata và mã nguồn bài báo thu thập từ `export.arxiv.org` tuân thủ arXiv API Terms of Use (1 kết nối, giãn cách tối thiểu 3 giây); mỗi bài báo thuộc giấy phép gốc của tác giả trên arXiv.\n"
        "- Siêu dữ liệu trích dẫn thu thập từ Semantic Scholar Academic Graph API.\n"
    )


def _iter_assigned_dirs(raw_dir: Path, member) -> Iterable[tuple[str, Path]]:
    if not raw_dir.is_dir():
        return
    for entry in sorted(raw_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or not re.match(r"^\d{4}[-_.]\d+", entry.name):
            continue
        aid = to_arxiv_id(entry.name)
        if member.contains(aid):
            yield aid, entry


def export_student_dataset(
    student_id: str,
    raw_dir: Path,
    output_dir: Path,
    processed_dir: Optional[Path] = None,
    predictions_path: Optional[Path] = None,
    members_config: Path = Path("configs/members.csv"),
) -> Dict[str, Any]:
    members = load_members(members_config)
    member = next((m for m in members if m.student_id == str(student_id)), None)
    if member is None:
        raise ValueError(f"Unknown student_id: {student_id}")

    papers_rows: List[Dict[str, Any]] = []
    refs_rows: List[Dict[str, Any]] = []
    elements_rows: List[Dict[str, Any]] = []
    hierarchy_rows: List[Dict[str, Any]] = []
    bibtex_rows: List[Dict[str, Any]] = []
    predictions_rows: List[Dict[str, Any]] = []

    for aid, pdir in _iter_assigned_dirs(raw_dir, member):
        meta_file = pdir / "metadata.json"
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            papers_rows.append(
                {
                    "arxiv_id": aid,
                    "title": str(meta.get("title") or ""),
                    "authors": [str(a) for a in (meta.get("authors") or [])],
                    "submission_date": str(meta.get("submission_date") or ""),
                    "revised_dates": [str(d) for d in (meta.get("revised_dates") or [])],
                    "venue": meta.get("venue") if meta.get("venue") is not None else None,
                }
            )
        refs_file = pdir / "references.json"
        if refs_file.is_file():
            refs = json.loads(refs_file.read_text(encoding="utf-8"))
            if isinstance(refs, dict):
                for ref_key, rinfo in sorted(refs.items()):
                    if not isinstance(rinfo, dict):
                        continue
                    ref_aid = str(rinfo.get("arxiv_id") or to_arxiv_id(ref_key))
                    refs_rows.append(
                        {
                            "arxiv_id": aid,
                            "ref_arxiv_id": ref_aid,
                            "ref_title": str(rinfo.get("title") or ""),
                            "ref_authors": [str(a) for a in (rinfo.get("authors") or [])],
                            "ref_submission_date": str(rinfo.get("submission_date") or ""),
                            "ref_s2_id": str(rinfo.get("s2_id") or ""),
                        }
                    )

        if processed_dir is not None:
            proc_paper = processed_dir / to_dir_id(aid)
            if not proc_paper.is_dir():
                proc_paper = processed_dir / pdir.name
            hier_file = proc_paper / "hierarchy.json"
            if hier_file.is_file():
                hdata = json.loads(hier_file.read_text(encoding="utf-8"))
                ekinds = hdata.get("element_kinds")
                for eid, content in (hdata.get("elements") or {}).items():
                    elements_rows.append(
                        {
                            "element_id": str(eid),
                            "arxiv_id": aid,
                            "kind": _infer_element_kind(str(eid), ekinds),
                            "content": str(content or ""),
                        }
                    )
                for ver_str, edges in (hdata.get("hierarchy") or {}).items():
                    if not str(ver_str).isdigit() or not isinstance(edges, dict):
                        continue
                    ver_num = int(ver_str)
                    for child_id, parent_id in edges.items():
                        if not child_id or not parent_id or child_id == parent_id:
                            continue
                        hierarchy_rows.append(
                            {
                                "arxiv_id": aid,
                                "version": ver_num,
                                "element_id": str(child_id),
                                "parent_id": str(parent_id),
                            }
                        )
            bib_json = proc_paper / "bibtex_entries.json"
            bib_raw = proc_paper / "refs.bib"
            parsed_bibs: List[Dict[str, Any]] = []
            if bib_json.is_file():
                loaded = json.loads(bib_json.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    parsed_bibs = loaded
            elif bib_raw.is_file():
                parsed_bibs = _parse_simple_bibtex(
                    bib_raw.read_text(encoding="utf-8", errors="replace")
                )
            for bentry in parsed_bibs:
                bibtex_rows.append(
                    {
                        "arxiv_id": aid,
                        "citation_key": str(bentry.get("citation_key") or ""),
                        "entry_type": str(bentry.get("entry_type") or "misc"),
                        "title": str(bentry.get("title") or ""),
                        "authors": [str(a) for a in (bentry.get("authors") or [])],
                        "year": int(bentry["year"]) if bentry.get("year") is not None else None,
                        "doi": str(bentry.get("doi") or ""),
                        "journal": str(bentry.get("journal") or ""),
                        "url": str(bentry.get("url") or ""),
                    }
                )

    if predictions_path is not None and predictions_path.exists():
        pred_table = pq.read_table(predictions_path)
        for row in pred_table.to_pylist():
            aid = to_arxiv_id(str(row.get("arxiv_id") or ""))
            if member.contains(aid):
                predictions_rows.append(
                    {
                        "arxiv_id": aid,
                        "partition": str(row["partition"]),
                        "citation_key": str(row["citation_key"]),
                        "groundtruth_arxiv_id": row.get("groundtruth_arxiv_id"),
                        "cand_1": row.get("cand_1"),
                        "cand_2": row.get("cand_2"),
                        "cand_3": row.get("cand_3"),
                        "cand_4": row.get("cand_4"),
                        "cand_5": row.get("cand_5"),
                    }
                )

    data_root = output_dir / "data"
    payloads = {
        "papers": papers_rows,
        "references": refs_rows,
        "elements": elements_rows,
        "hierarchy": hierarchy_rows,
        "bibtex": bibtex_rows,
        "predictions": predictions_rows,
    }
    stats = {
        name: _write_sharded_table(rows, TABLE_SCHEMAS[name], data_root / name)
        for name, rows in payloads.items()
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    readme_text = build_dataset_card(
        student_id=member.student_id,
        member_name=member.name,
        start_id=member.start_id,
        end_id=member.end_id,
        table_stats=stats,
    )
    readme_path = output_dir / "README.md"
    tmp_readme = output_dir / "README.md.tmp"
    tmp_readme.write_text(readme_text, encoding="utf-8")
    tmp_readme.replace(readme_path)
    return {"student_id": student_id, "output_dir": str(output_dir), "tables": stats}
