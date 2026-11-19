"""Read-only RPC audit with an explicit manifest allowlist."""

from pathlib import Path

from .completion import assess_publication
from .discovery import to_dir_id
from .isolation import serve
from .storage import sha256_file

context = {}


def handle(request):
    if request["action"] == "init":
        ids = request["ids"]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Invalid audit manifest")
        context.update(ids=set(ids), raw=Path(request["raw"]), proofs=request["proofs"],
                       allow_s2_unavailable=request.get("allow_s2_unavailable", False))
        return {"ready": True, "selected": len(ids)}
    aid = request["arxiv_id"]
    if aid not in context.get("ids", set()):
        raise ValueError("Audit ID outside the selected owner manifest")
    directory = context["raw"] / to_dir_id(aid)
    marker = directory / "crawl_status.json"
    before = sha256_file(marker) if marker.is_file() else None
    result = assess_publication(directory, aid, context["proofs"], context["allow_s2_unavailable"])
    after = sha256_file(marker) if marker.is_file() else None
    if before != after:
        result.update(classification="pending", data_download_success=False,
                      reasons=["Raw commit changed during audit; freeze the writer first"])
    result["commit_marker_sha256"] = after
    return result


if __name__ == "__main__":
    serve(handle)
