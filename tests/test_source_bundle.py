import importlib.util
import zipfile
from pathlib import Path


def test_bundle_excludes_book_build_outputs_and_includes_book_requirements(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/build_colab_bundle.py"
    spec = importlib.util.spec_from_file_location("test_bundle_builder", source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for name in ("pyproject.toml", "requirements.txt", "requirements-colab-m1.txt",
                 "requirements-book.txt", "README.md", "PLAN.md", "book/ch1_crawling.md",
                 "book/_build/jupyter_execute/ch1.ipynb", "book/_build/.jupyter_cache/index.json",
                 "src/ids_arxiv/__pycache__/cache.json", "src/ids_arxiv/example.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source or build output")
    monkeypatch.setattr(builder, "__file__", str(tmp_path / "scripts/build_colab_bundle.py"))
    builder.main()
    with zipfile.ZipFile(tmp_path / "artifacts/release/ids13-code.zip") as archive:
        files = archive.namelist()
    assert "requirements-book.txt" in files and "book/ch1_crawling.md" in files
    assert "src/ids_arxiv/example.py" in files
    assert not any("_build" in name or "__pycache__" in name or ".jupyter_cache" in name for name in files)
