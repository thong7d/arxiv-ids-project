"""Read-only, provenance-aware M1 statistics. Missing evidence is never zero."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from ids_arxiv.checkpoint import PROTOCOL
from ids_arxiv.storage import utc_now

CLASSES = ("full_success", "verified_exception", "references_unavailable", "pending")
OWNERS = ("23120364", "23120358", "23120345")
MEMBER_LABELS = {
    "23120364": "Phạm Minh Thông (Dải 1)",
    "23120358": "Nguyễn Tiến Thành (Dải 2)",
    "23120345": "Nguyễn Trịnh Quang (Dải 3)",
}


def member_label(owner, hide_student_id=True):
    return MEMBER_LABELS.get(str(owner), str(owner)) if hide_student_id else str(owner)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def marker_statistics(expected_ids, records):
    """Summarize frozen markers, with matched size cohorts and explicit missingness.

    This reads measurements already recorded by the crawler, not raw bytes or
    a new integrity audit. initial_bytes is expanded archive size, not transfer.
    """
    ids = list(expected_ids)
    if len(set(ids)) != len(ids) or set(records) != set(ids):
        raise ValueError("Marker statistics need an exact owner manifest")
    def numeric(values):
        return all(type(n) is int and n >= 0 for n in values)
    def mean(values):
        return sum(values) / len(values) if values else None
    known, paired, raw_counts, arxiv_counts, ref_success, retained = 0, [], [], [], 0, []
    for aid in ids:
        row = records[aid]
        if (not row or row.get("arxiv_id") != aid or row.get("schema_version") != PROTOCOL
                or row.get("commit_state") != "committed"):
            continue
        known += 1
        versions = row.get("versions", [])
        saved = [v for v in versions if v.get("success")]
        after = [v.get("stripped_bytes") for v in saved]
        if versions and numeric(after):
            retained.append(sum(after))
        before = [v.get("initial_bytes") for v in versions]
        expected = row.get("expected_versions", [])
        if (expected and row.get("source_success") and len(expected) == len(versions)
                and set(expected) == {v.get("version") for v in versions}
                and all(v.get("success") and v.get("state") in {"downloaded", "non_tex_source"} for v in versions)
                and numeric(before) and numeric(after) and sum(before) >= sum(after)):
            paired.append((sum(before), sum(after)))
        refs = row.get("references_status", {})
        complete = bool(refs.get("success") and refs.get("all_references_retained")
                        and type(refs.get("raw_count")) is int and refs["raw_count"] >= 0)
        ref_success += int(complete and bool(refs.get("dates_complete")))
        if complete and type(refs.get("raw_count")) is int and refs["raw_count"] >= 0:
            raw_counts.append(refs["raw_count"])
            count = row.get("num_references_arxiv", row.get("num_references"))
            if type(count) is int and 0 <= count <= refs["raw_count"]:
                arxiv_counts.append(count)
    return {"expected_papers": len(ids), "observed_committed_markers": known,
            "missing_or_incompatible_markers": len(ids)-known, "paired_size_papers": len(paired),
            "mean_before_uncompressed_bytes": mean([v[0] for v in paired]),
            "mean_after_tex_bib_bytes": mean([v[1] for v in paired]),
            "observed_tex_bib_bytes": sum(retained) if retained else None, "size_observed_papers": len(retained),
            "all_reference_count_papers": len(raw_counts), "mean_all_references": mean(raw_counts),
            "arxiv_reference_count_papers": len(arxiv_counts), "mean_arxiv_references": mean(arxiv_counts),
            "reference_metadata_success_rate": ref_success / len(ids) if ids and known == len(ids) else None,
            "note": "Frozen crawler measurements; per publication across versions. PDF-only excluded from paired archive-size cohort. TeX/Bib bytes are not full output disk usage."}


def audit_statistics(owner, expected_ids, manifest_sha, audit):
    """Reconcile a prior audit, not perform a new integrity audit of raw bytes."""
    ids = list(expected_ids)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Expected IDs must be distinct and nonempty")
    if not audit:
        return {"audit_available": False, "expected_count": len(ids), "counts": {},
                "unassessed_count": len(ids), "success_rate": None, "operational_closed": False}
    rows = audit.get("records", [])
    actual = [row.get("arxiv_id") for row in rows]
    if (str(audit.get("student_id")) != str(owner) or audit.get("protocol_version") != PROTOCOL
            or audit.get("discovery_manifest_sha256") != manifest_sha
            or len(actual) != len(ids) or len(set(actual)) != len(actual) or set(actual) != set(ids)):
        raise ValueError("Audit owner, protocol, manifest or coverage mismatch")
    counts = Counter()
    for row in rows:
        kind = row.get("classification")
        if kind not in CLASSES:
            raise ValueError("Unknown audit classification")
        if kind != "pending" and row.get("reasons"):
            raise ValueError("A completed assessment still has unresolved reasons")
        if kind == "full_success" and (row.get("data_download_success") is not True or row.get("withdrawn_versions")):
            raise ValueError("Inconsistent downloaded-success assessment")
        if kind != "full_success" and row.get("data_download_success") is not False:
            raise ValueError("Exception/pending assessment must not claim downloaded success")
        if kind == "verified_exception" and not row.get("withdrawn_versions"):
            raise ValueError("Verified exception needs withdrawn versions")
        counts[kind] += 1
    if any(audit.get("counts", {}).get(k, 0) != counts[k] for k in CLASSES):
        raise ValueError("Audit counters disagree with individual assessments")
    return {"audit_available": True, "expected_count": len(ids),
            "counts": {k: counts[k] for k in CLASSES}, "unassessed_count": 0,
            "success_rate": counts["full_success"] / len(ids),
            "operational_closed": counts["pending"] == 0,
            "academic_exception_approval_pending": counts["references_unavailable"] > 0,
            "audited_at": audit.get("audited_at"), "audit_sha256": fingerprint(audit),
            "source_sha256": audit.get("source_sha256"),
            "note": "Derived from the saved full audit; raw files are not re-audited by this report."}


def benchmark_statistics(sessions, events, expected_ids):
    """Deduplicate session/chunk mirrors; separate worker time from elapsed wall time."""
    unique = {}
    for session in sessions:
        sid = session.get("session_id")
        if not sid:
            raise ValueError("Session ID missing")
        if sid in unique and unique[sid] != session:
            raise ValueError("Conflicting mirrors of one benchmark session")
        unique[sid] = session
    complete = {sid: row for sid, row in unique.items()
                if row.get("state") == "completed" and row.get("ended_at")}
    if not complete:
        return {"session_count": len(unique), "completed_sessions": 0,
                "measured_worker_seconds": None, "coverage_count": 0, "coverage_complete": False,
                "end_to_end_seconds": None, "final_benchmark_verified": False}
    intervals, duration, integral, weight, peak = [], 0.0, 0.0, 0.0, 0
    for row in complete.values():
        start = datetime.fromisoformat(row["started_at"]).timestamp()
        end = datetime.fromisoformat(row["ended_at"]).timestamp()
        seconds, sampled = float(row["elapsed_seconds"]), float(row["sample_seconds"])
        if end < start or seconds < 0 or sampled < 0 or row["ram_byte_seconds"] < 0:
            raise ValueError("Invalid benchmark measurement")
        intervals.append((start, end))
        duration += seconds
        integral += row["ram_byte_seconds"]
        weight += sampled
        peak = max(peak, row["peak_process_tree_rss_bytes"])
    wall, boundary = 0.0, float("-inf")
    for start, end in sorted(intervals):
        wall += max(0, end - max(start, boundary))
        boundary = max(boundary, end)
    seen, covered, latencies = set(), set(), []
    allowed = set(expected_ids)
    for row in events:
        if row.get("kind") != "paper_attempt" or row.get("session_id") not in complete:
            continue
        key = fingerprint(row)
        if key in seen:
            continue
        seen.add(key)
        aid = row.get("arxiv_id")
        if aid not in allowed:
            raise ValueError("Benchmark event outside owner manifest")
        covered.add(aid)
        latency = row.get("elapsed_seconds")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(latency)
    return {"session_count": len(unique), "completed_sessions": len(complete),
            "measured_worker_seconds": duration, "completed_session_wall_union_seconds": wall,
            "end_to_end_seconds": None, "average_process_tree_rss_bytes": integral / weight if weight else None,
            "peak_single_worker_rss_bytes": peak, "paper_attempts": len(seen),
            "mean_attempt_seconds": sum(latencies) / len(latencies) if latencies else None,
            "coverage_count": len(covered), "coverage_complete": covered == allowed,
            "all_sessions_colab": all(s.get("environment") == "colab" for s in complete.values()),
            "source_releases": sorted({s.get("source_bundle_sha256", "unknown") for s in complete.values()}),
            "final_benchmark_verified": False,
            "note": "Worker sum/interval union are not whole-system end-to-end time. CPU mode, discovery, gaps and full-group coverage need separate evidence."}


def make_snapshot(manifest, manifest_sha, bundles):
    """Sanitized aggregate input for report builds; never contains keys or raw papers."""
    owners = {}
    all_ids = [aid for values in manifest.values() for aid in values]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Overlapping owner manifests")
    for owner, ids in manifest.items():
        bundle = bundles.get(owner, {})
        value = audit_statistics(owner, ids, manifest_sha, bundle.get("audit"))
        if bundle.get("benchmark_collected"):
            benchmark = benchmark_statistics(bundle.get("sessions", []), bundle.get("events", []), ids)
            if not bundle.get("events_collected"):
                benchmark.update(coverage_count=None, coverage_complete=False)
        else:
            benchmark = {"session_count": None, "completed_sessions": None,
                         "measured_worker_seconds": None, "coverage_count": None,
                         "coverage_complete": False, "end_to_end_seconds": None,
                         "final_benchmark_verified": False, "collection_state": "not_collected"}
        value.update(student_id=owner, benchmark=benchmark)
        crawl = bundle.get("crawl") or bundle.get("legacy_crawl") or {}
        value["crawl_snapshot"] = {k: crawl.get(k) for k in (
            "selected_publications", "total_attempted", "success_count", "source_success_count",
            "reference_success_count", "quarantined_count", "updated_at", "protocol_version")}
        value["crawl_snapshot"]["is_legacy"] = not bool(bundle.get("crawl"))
        value["collection_errors"] = bundle.get("collection_errors", [])
        value["corpus_statistics"] = (marker_statistics(ids, bundle["markers"])
                                      if "markers" in bundle else None)
        owners[owner] = value
    return {"schema_version": 1, "generated_at": utc_now(), "discovery_manifest_sha256": manifest_sha,
            "expected_count": len(all_ids), "owners": owners, "final_report": False,
            "note": "Crawl counters are provisional. Unknown values remain null; exceptions are not successful downloads."}


def load_snapshot(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("owners"), dict):
        raise ValueError("Unsupported report snapshot")
    for owner, row in value["owners"].items():
        if owner not in OWNERS:
            raise ValueError("Unknown owner in report")
        counts = row.get("counts", {})
        numbers = [row["expected_count"], row["unassessed_count"], *counts.values()]
        if (any(type(n) is not int or n < 0 for n in numbers) or row["expected_count"] == 0
                or not set(counts) <= set(CLASSES)):
            raise ValueError("Invalid report counts")
        if sum(row.get("counts", {}).values()) + row["unassessed_count"] != row["expected_count"]:
            raise ValueError("Report coverage counters inconsistent")
        if row.get("audit_available"):
            if row["unassessed_count"] or row["success_rate"] != counts.get("full_success", 0) / row["expected_count"]:
                raise ValueError("Invalid audited success rate")
        elif counts or row["success_rate"] is not None:
            raise ValueError("Unaudited data must not claim a success rate")
    if sum(row["expected_count"] for row in value["owners"].values()) != value["expected_count"]:
        raise ValueError("Report denominator inconsistent")
    return value


def coverage_table(snapshot, hide_student_id=True):
    import pandas as pd
    rows = []
    index_col = "Thành viên" if hide_student_id else "MSSV"
    for owner, item in snapshot["owners"].items():
        counts = item["counts"]
        rows.append({index_col: member_label(owner, hide_student_id), "Được giao": item["expected_count"],
                     "Đạt sau audit": counts.get("full_success", 0),
                     "Ngoại lệ source": counts.get("verified_exception", 0),
                     "Thiếu S2": counts.get("references_unavailable", 0),
                     "Cần xem xét": counts.get("pending", 0),
                     "Chưa audit": item["unassessed_count"],
                     "Tỉ lệ tải đạt (%)": item["success_rate"] * 100 if item["success_rate"] is not None else None})
    return pd.DataFrame(rows).set_index(index_col)


def coverage_figure(snapshot, hide_student_id=True):
    import matplotlib.pyplot as plt
    table = coverage_table(snapshot, hide_student_id=hide_student_id)
    columns = ["Đạt sau audit", "Ngoại lệ source", "Thiếu S2", "Cần xem xét", "Chưa audit"]
    ax = table[columns].plot.barh(stacked=True, figsize=(10, 4),
                                color=["#238b45", "#fdae6b", "#756bb1", "#de2d26", "#d9d9d9"])
    ax.set_xlabel("Số ID được giao (ngoại lệ không cộng vào tải thành công)")
    ax.set_title("Coverage từ audit đã lưu — không phải bộ đếm crawler cũ")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.23), ncol=3)
    plt.tight_layout()
    return ax.figure


def interactive_coverage_html(snapshot, hide_student_id=True):
    """Self-contained interactive HTML/JS coverage dashboard for Jupyter Book (hover + filters)."""
    import html
    records = []
    for owner, item in snapshot["owners"].items():
        counts = item.get("counts", {})
        expected = int(item.get("expected_count") or 5000)
        stats = item.get("corpus_statistics") or {}
        label = member_label(owner, hide_student_id)
        records.append({
            "id": label,
            "label": label,
            "expected": expected,
            "full_success": int(counts.get("full_success", 0)),
            "verified_exception": int(counts.get("verified_exception", 0)),
            "references_unavailable": int(counts.get("references_unavailable", 0)),
            "pending": int(counts.get("pending", 0)),
            "unassessed": int(item.get("unassessed_count", 0)),
            "audited_at": item.get("audited_at") or "Chưa audit",
            "operational_closed": bool(item.get("operational_closed")),
            "mean_before_kb": round(stats["mean_before_uncompressed_bytes"] / 1024, 1)
            if isinstance(stats.get("mean_before_uncompressed_bytes"), (int, float)) else None,
            "mean_after_kb": round(stats["mean_after_tex_bib_bytes"] / 1024, 1)
            if isinstance(stats.get("mean_after_tex_bib_bytes"), (int, float)) else None,
            "mean_refs": round(stats["mean_all_references"], 1)
            if isinstance(stats.get("mean_all_references"), (int, float)) else None,
        })
    data_json = json.dumps(records, ensure_ascii=False)
    gen_at = html.escape(str(snapshot.get("generated_at", "")))
    return f"""
<div id="ids13-m1-interactive" style="font-family:system-ui,-apple-system,sans-serif;border:1px solid #d0d7de;border-radius:8px;padding:16px;margin:14px 0;background:#ffffff;">
  <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px;">
    <div>
      <strong style="font-size:15px;">Biểu đồ tương tác Coverage & Kiểm định M1</strong>
      <div style="font-size:12px;color:#57606a;">Di chuột (hover) vào từng phân đoạn để xem chi tiết · Snapshot: <code>{gen_at}</code></div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;font-size:13px;">
      <label for="ids13-member-filter">Thành viên:</label>
      <select id="ids13-member-filter" style="padding:4px 8px;border:1px solid #d0d7de;border-radius:4px;">
        <option value="ALL">Tất cả (15.000 ID)</option>
      </select>
      <label for="ids13-unit-mode">Đơn vị:</label>
      <select id="ids13-unit-mode" style="padding:4px 8px;border:1px solid #d0d7de;border-radius:4px;">
        <option value="count">Số lượng bài (ID)</option>
        <option value="pct">Tỉ lệ (%)</option>
      </select>
    </div>
  </div>
  <div id="ids13-bars-container"></div>
  <div id="ids13-tooltip" style="margin-top:10px;padding:8px 12px;border-radius:6px;background:#f6f8fa;border:1px solid #d0d7de;font-size:13px;min-height:22px;color:#24292f;">
    Di chuột vào thanh biểu đồ phía trên để xem số liệu chi tiết từng hạng mục.
  </div>
</div>
<script>
(function() {{
  const data = {data_json};
  const cats = [
    {{key: "full_success", name: "Đạt sau audit (full_success)", color: "#238b45"}},
    {{key: "verified_exception", name: "Ngoại lệ rút bài (verified_exception)", color: "#fdae6b"}},
    {{key: "references_unavailable", name: "Đủ nguồn arXiv · Thiếu S2 (references_unavailable)", color: "#756bb1"}},
    {{key: "pending", name: "Đang chờ / Cần repair (pending)", color: "#de2d26"}},
    {{key: "unassessed", name: "Chưa audit", color: "#d9d9d9"}}
  ];
  const selMember = document.getElementById("ids13-member-filter");
  const selUnit = document.getElementById("ids13-unit-mode");
  const container = document.getElementById("ids13-bars-container");
  const tooltip = document.getElementById("ids13-tooltip");
  data.forEach(r => {{
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = r.label;
    selMember.appendChild(opt);
  }});
  function render() {{
    const filter = selMember.value;
    const mode = selUnit.value;
    container.innerHTML = "";
    const rows = filter === "ALL" ? data : data.filter(r => r.id === filter);
    rows.forEach(r => {{
      const wrap = document.createElement("div");
      wrap.style.marginBottom = "12px";
      const srcCount = r.full_success + r.references_unavailable;
      const srcPct = ((srcCount / r.expected) * 100).toFixed(2);
      const header = document.createElement("div");
      header.style.cssText = "display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;";
      header.innerHTML = "<span><strong>" + r.label + "</strong> (" + (r.operational_closed ? "Đã chốt vận hành" : "Đang cập nhật") + ")</span>" +
        "<span style='color:#57606a;'>Đủ nguồn arXiv: <strong>" + srcCount + "/" + r.expected + " (" + srcPct + "%)</strong> · Đạt toàn phần: <strong>" + r.full_success + "</strong></span>";
      wrap.appendChild(header);
      const bar = document.createElement("div");
      bar.style.cssText = "display:flex;height:26px;border-radius:5px;overflow:hidden;background:#eaeef2;border:1px solid #d0d7de;";
      cats.forEach(c => {{
        const val = r[c.key] || 0;
        if (val <= 0) return;
        const pct = (val / r.expected) * 100;
        const seg = document.createElement("div");
        seg.style.cssText = "width:" + pct + "%;background:" + c.color + ";cursor:pointer;transition:opacity 0.15s;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:600;overflow:hidden;white-space:nowrap;";
        if (pct > 7) {{
          seg.textContent = mode === "pct" ? pct.toFixed(1) + "%" : val;
        }}
        seg.addEventListener("mouseenter", () => {{
          seg.style.opacity = "0.85";
          let extra = "";
          if (r.mean_before_kb !== null && r.mean_after_kb !== null) {{
            extra += " · Size TB trước/sau lọc: " + r.mean_before_kb + " KB → " + r.mean_after_kb + " KB";
          }}
          if (r.mean_refs !== null) {{
            extra += " · Refs S2 TB: " + r.mean_refs;
          }}
          tooltip.innerHTML = "<strong>" + r.label + "</strong> — <span style='color:" + c.color + ";font-weight:600;'>" + c.name + "</span>: <strong>" +
            val + " / " + r.expected + " ID (" + pct.toFixed(2) + "%)</strong> · Audit lúc: <code>" + r.audited_at + "</code>" + extra;
        }});
        seg.addEventListener("mouseleave", () => {{ seg.style.opacity = "1"; }});
        bar.appendChild(seg);
      }});
      wrap.appendChild(bar);
      container.appendChild(wrap);
    }});
  }}
  selMember.addEventListener("change", render);
  selUnit.addEventListener("change", render);
  render();
}})();
</script>
"""


def interactive_checkpoint_timeline_html():
    """Self-contained interactive version and checkpoint timeline for Chapter 1."""
    milestones = [
        {"ver": "v1–v2", "date": "02/11/2026", "dir": "Early Discovery", "title": "Khảo sát API & Phát hiện giới hạn offset 10.000",
         "detail": "arXiv Atom API trả HTTP 500 tại offset 10.000. Nhóm giữ nguyên log v2 để đối soát và thiết kế lại thuật toán chia shard theo tuần ở v3."},
        {"ver": "v3 (Protocol 3)", "date": "13/11 – 16/11/2026", "dir": "m1-pilot-v3/ & m1-final-v3/", "title": "Manifest 15.000 ID & Pilot Gate 30 bài",
         "detail": "Xác minh manifest 15.000 ID (SHA-256: 721cab05206f...), vượt qua Pilot Gate 30 bài và chạy thu thập đợt chính trên Google Colab CPU."},
        {"ver": "v4 (Protocol 4)", "date": "17/11 – 20/11/2026", "dir": "m1-team-v4/ (bundle 6ca65d5e → 9b4cfdb0)", "title": "Kiến trúc Bounded Workflow & Audit độc lập",
         "detail": "Nâng lên schema_version 4: tách io_worker/audit_service, lưu đủ references_all.json và provenance ngày nộp. Chốt xong Dải 1 (4.959 full_success, 37 verified_exception, 4 references_unavailable; 99,26% đủ nguồn TeX/Bib)."},
        {"ver": "v4.1–v4.2", "date": "21/11/2026", "dir": "m1-team-v4/ (bundle 6ae98018 → 8924fa53)", "title": "Targeted Repair, S2 Wait-Cap & Xác minh rút bài Dải 3",
         "detail": "Thử nghiệm có kiểm soát 3 giờ thu hồi +264 bài S2, khôi phục 25/25 ngày arXiv Atom và xác minh 32/32 chứng từ rút bài trên Dải 3 (đạt 4.989/5.000 = 99,78% bài hoàn tất 100% nguồn TeX/Bib)."},
        {"ver": "v4.3 (Hiện hành)", "date": "22/11/2026", "dir": "m1-team-v4/ (bundle a170ab88)", "title": "Hợp nhất Notebook Auto-Repair & Chạy bù Dải 2 + Dải 3",
         "detail": "Tự động chuyển tiếp workflow → repair trên cùng 1 notebook IDS13_M1_Colab.ipynb, chờ cooldown S2 tới 125s và fallback khi key bị 429. Đang chạy bù nguồn cho Dải 2 và references S2 cho Dải 3."}
    ]
    items_json = json.dumps(milestones, ensure_ascii=False)
    return f"""
<div id="ids13-timeline-widget" style="font-family:system-ui,-apple-system,sans-serif;border:1px solid #d0d7de;border-radius:8px;padding:16px;margin:14px 0;background:#ffffff;">
  <div style="font-weight:600;font-size:15px;margin-bottom:8px;">Tiến trình Phiên bản & Các mốc Checkpoint (点击 / Click vào từng mốc để xem chi tiết)</div>
  <div id="ids13-tl-buttons" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;"></div>
  <div id="ids13-tl-box" style="padding:12px;border-radius:6px;background:#f6f8fa;border-left:4px solid #0969da;font-size:13px;line-height:1.5;"></div>
</div>
<script>
(function() {{
  const steps = {items_json};
  const btnWrap = document.getElementById("ids13-tl-buttons");
  const box = document.getElementById("ids13-tl-box");
  function selectStep(idx) {{
    Array.from(btnWrap.children).forEach((b, i) => {{
      b.style.background = i === idx ? "#0969da" : "#f6f8fa";
      b.style.color = i === idx ? "#ffffff" : "#24292f";
      b.style.borderColor = i === idx ? "#0969da" : "#d0d7de";
    }});
    const s = steps[idx];
    box.innerHTML = "<div><strong>" + s.ver + "</strong> · <code>" + s.date + "</code> · Thư mục/Gói: <code>" + s.dir + "</code></div>" +
      "<div style='margin-top:4px;font-weight:600;color:#0969da;'>" + s.title + "</div>" +
      "<div style='margin-top:4px;color:#24292f;'>" + s.detail + "</div>";
  }}
  steps.forEach((s, idx) => {{
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = s.ver + " (" + s.date.split(" ")[0] + ")";
    btn.style.cssText = "padding:6px 12px;border:1px solid #d0d7de;border-radius:16px;cursor:pointer;font-size:12px;font-weight:600;transition:all 0.15s;";
    btn.addEventListener("click", () => selectStep(idx));
    btnWrap.appendChild(btn);
  }});
  selectStep(steps.length - 1);
}})();
</script>
"""
