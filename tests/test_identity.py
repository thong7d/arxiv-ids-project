import pytest

from ids_arxiv.colab_app import default_config
from ids_arxiv.crawler.arxiv_client import ArxivCrawler
from ids_arxiv.crawler.s2_client import SemanticScholarClient
from ids_arxiv.identity import user_agent
from ids_arxiv.network_schedule import RUNNERS
from ids_arxiv.team_run import environment, output_root


def test_three_operators_have_separate_headers_keys_and_outputs(monkeypatch, tmp_path):
    agents, keys, outputs, arxiv_quotas, s2_quotas = [], [], [], [], []
    for runner in RUNNERS:
        config = default_config(runner, tmp_path)
        monkeypatch.setenv("IDS_RUNNER_ID", environment(config)["IDS_RUNNER_ID"])
        monkeypatch.setenv("ARXIV_CONTACT_EMAIL", f"{runner}@example.org")
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", f"test-key-{runner}")
        arxiv, s2 = ArxivCrawler(), SemanticScholarClient(deferred=True)
        try:
            agent = arxiv.session.headers["User-Agent"]
            assert runner in agent and f"{runner}@example.org" in agent
            assert agent == s2.session.headers["User-Agent"]
            assert "x-api-key" not in arxiv.session.headers
            assert "test-key" not in agent
            agents.append(agent)
            keys.append(s2.session.headers["x-api-key"])
            outputs.append(output_root(config, runner))
            s2_quotas.append(s2.limiter.path)
            from ids_arxiv.crawler.rate_limiter import arxiv_limiter
            arxiv_quotas.append(arxiv_limiter.path)
        finally:
            arxiv.session.close()
            s2.session.close()
    assert len(set(agents)) == len(set(keys)) == len(set(outputs)) == len(set(s2_quotas)) == 3
    assert len(set(arxiv_quotas)) == 1  # Changing email/runner must not multiply arXiv quota.


def test_no_thong_email_fallback_or_header_injection(monkeypatch):
    monkeypatch.delenv("ARXIV_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("IDS_RUNNER_ID", raising=False)
    assert "not-configured" in user_agent() and "thongpham" not in user_agent()
    with pytest.raises(ValueError, match="newlines"):
        user_agent("test@example.org\r\nX-Injected: yes")
