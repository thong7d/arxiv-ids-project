import gzip
from unittest.mock import Mock

import pytest
import requests

from ids_arxiv.crawler.arxiv_client import ArxivCrawler


class Response:
    def __init__(self, status, headers, chunks, broken=False):
        self.status_code, self.headers = status, headers
        self.chunks, self.broken = chunks, broken

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield from self.chunks
        if self.broken:
            raise requests.exceptions.ChunkedEncodingError("truncated")


@pytest.mark.parametrize("ignore_range", [False, True])
def test_interrupted_source_recovers_without_duplicate_prefix(tmp_path, monkeypatch, ignore_range):
    replies = [Response(200, {"Content-Length": "6", "ETag": "a"}, [b"abc"], True)]
    replies.append(Response(200, {"Content-Length": "6"}, [b"abcdef"]) if ignore_range else
                   Response(206, {"Content-Range": "bytes 3-5/6", "ETag": "a"}, [b"def"]))
    get = Mock(side_effect=replies)
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", get)
    archive = tmp_path / "source.part"
    assert ArxivCrawler()._download_source("https://example.invalid", archive) == 2
    assert archive.read_bytes() == b"abcdef"
    assert get.call_args.kwargs["headers"]["Range"].startswith("bytes=3-")


def test_wrong_continuation_offset_rejected(tmp_path, monkeypatch):
    get = Mock(side_effect=[Response(200, {"Content-Length": "6"}, [b"abc"], True),
                            Response(206, {"Content-Range": "bytes 2-5/6"}, [b"cdef"])])
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", get)
    with pytest.raises(ValueError, match="Content-Range"):
        ArxivCrawler()._download_source("https://example.invalid", tmp_path / "source.part")


def test_range_specific_etag_uses_same_last_modified_not_inferred_body_hash(tmp_path, monkeypatch):
    get = Mock(side_effect=[
        Response(200, {"Content-Length": "6", "ETag": '"sha256:opaque-not-a-body-digest"',
                       "Last-Modified": "stable"}, [b"abc"], True),
        Response(206, {"Content-Range": "bytes 3-5/6", "ETag": '"range-specific"',
                       "Last-Modified": "stable"}, [b"def"]),
    ])
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", get)
    assert ArxivCrawler()._download_source("https://example.invalid", tmp_path / "source.part") == 2
    assert get.call_args.kwargs["headers"]["If-Range"] == "stable"


def test_corrupt_gzip_crc_rejected_before_extraction(tmp_path):
    compressed = bytearray(gzip.compress(b"\\documentclass{article}\\begin{document}Hello"))
    compressed[-8] ^= 1  # Corrupt the CRC, retaining a valid gzip header.
    archive = tmp_path / "source.gz"
    archive.write_bytes(compressed)
    destination = tmp_path / "output"
    destination.mkdir()
    assert not ArxivCrawler()._safe_extract(archive, destination)
    assert not list(destination.iterdir())
