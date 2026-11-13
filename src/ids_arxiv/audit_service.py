"""Read-only RPC audit with an explicit manifest allowlist."""

from pathlib import Path

from .completion import assess_publication
from .discovery import to_dir_id
from .isolation import serve

context = {}


def handle(request):
    if request["action"] == "init":
        ids = request["ids"]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Invalid audit manifest")
        context.update(ids=set(ids), raw=Path(request["raw"]), proofs=request["proofs"])
        return {"ready": True, "selected": len(ids)}
    aid = request["arxiv_id"]
    if aid not in context.get("ids", set()):
        raise ValueError("Audit ID outside the selected owner manifest")
    return assess_publication(context["raw"] / to_dir_id(aid), aid, context["proofs"])


if __name__ == "__main__":
    serve(handle)
