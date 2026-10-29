"""
Tests for crawler components: rate limiter, S2 reference extraction, safe extraction, and checkpointing.
"""

import io
import json
import tarfile
import time

from ids_arxiv.crawler.arxiv_client import ArxivCrawler
from ids_arxiv.crawler.rate_limiter import PoliteRateLimiter
from ids_arxiv.crawler.runner import crawl_paper
from ids_arxiv.crawler.s2_client import SemanticScholarClient


def test_rate_limiter():
    limiter = PoliteRateLimiter(min_interval_seconds=0.1)
    t0 = time.time()
    limiter.wait()
    limiter.wait()
    elapsed = time.time() - t0
    assert elapsed >= 0.09, f"Rate limiter did not enforce delay: {elapsed}s"


def test_s2_process_references():
    client = SemanticScholarClient()
    raw_refs = [
        {
            "paperId": "s2_123",
            "title": "Attention Is All You Need",
            "year": 2017,
            "authors": [{"name": "Ashish Vaswani"}],
            "externalIds": {"ArXiv": "1706.03762"},
        },
        {
            "paperId": "s2_456",
            "title": "Book without arXiv",
            "year": 2010,
            "authors": [{"name": "Author Book"}],
            "externalIds": {"DOI": "10.1234/something"},  # No arXiv -> must be ignored!
        },
    ]

    processed = client._process_references(raw_refs)
    assert len(processed) == 1
    assert "1706-03762" in processed
    item = processed["1706-03762"]
    assert item["title"] == "Attention Is All You Need"
    assert item["s2_id"] == "s2_123"
    assert item["authors"] == ["Ashish Vaswani"]
    assert item["year"] == 2017


def test_safe_extract_tar(tmp_path):
    crawler = ArxivCrawler()
    dest_dir = tmp_path / "extracted"
    dest_dir.mkdir()

    # Create dummy tar.gz
    archive_file = tmp_path / "test.tar.gz"
    with tarfile.open(archive_file, "w:gz") as tar:
        data = b"\\documentclass{article}\\begin{document}Hello\\end{document}"
        ti = tarfile.TarInfo(name="main.tex")
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))

    ok = crawler._safe_extract(archive_file, dest_dir)
    assert ok
    assert (dest_dir / "main.tex").exists()
    assert (dest_dir / "main.tex").read_bytes().startswith(b"\\documentclass")


def test_crawl_paper_checkpoint(tmp_path):
    output_dir = tmp_path / "raw"
    paper_dir = output_dir / "2509-01047"
    paper_dir.mkdir(parents=True)

    # Mock an existing successful status
    cached_status = {
        "arxiv_id": "2509.01047",
        "dir_name": "2509-01047",
        "success": True,
        "versions": [{"version": 1, "success": True}],
    }
    with open(paper_dir / "crawl_status.json", "w", encoding="utf-8") as f:
        json.dump(cached_status, f)

    crawler = ArxivCrawler()
    s2 = SemanticScholarClient()

    # Should resume and return cached without making network calls
    res = crawl_paper("2509.01047", output_dir, crawler, s2, resume=True)
    assert res["success"] is True
    assert res["arxiv_id"] == "2509.01047"


def test_run_crawling_pipeline_student_filter(tmp_path):
    import pandas as pd

    from ids_arxiv.crawler.runner import run_crawling_pipeline

    manifest_path = tmp_path / "papers.parquet"
    mock_df = pd.DataFrame([
        {"arxiv_id": "2508.17872", "owner_student_id": "23120364", "owner_name": "Pham Minh Thong", "order_in_range": 1},
        {"arxiv_id": "2509.01047", "owner_student_id": "23120358", "owner_name": "Nguyen Tien Thanh", "order_in_range": 1},
    ])
    mock_df.to_parquet(manifest_path)

    output_dir = tmp_path / "raw"
    summary = run_crawling_pipeline(
        manifest_path=manifest_path,
        output_dir=output_dir,
        student_id="99999999",  # Non-existent
    )
    assert summary["total_attempted"] == 0
