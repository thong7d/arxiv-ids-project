"""Build an explicit source-only Colab release; never include secrets or data."""

import hashlib
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/release/ids13-code.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    allowed = {
        ".py",
        ".tex",
        ".bib",
        ".json",
        ".md",
        ".yaml",
        ".yml",
        ".toml",
        ".txt",
        ".csv",
        ".ipynb",
    }
    candidates = []
    for name in ("src", "tests", "configs", "scripts", "book"):
        directory = root / name
        if directory.exists():
            candidates.extend(
                p
                for p in directory.rglob("*")
                if p.is_file() and p.suffix in allowed and "__pycache__" not in p.parts
            )
    candidates += [
        root / name for name in ("pyproject.toml", "requirements.txt", "README.md", "PLAN.md")
    ]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(candidates)):
            archive.write(path, path.relative_to(root).as_posix())
    print(f"Bundle: {output}")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".sha256").write_text(checksum + "\n", encoding="utf-8")
    print(f"SHA256: {checksum}")
    print(f"Source files: {len(set(candidates))}")


if __name__ == "__main__":
    main()
