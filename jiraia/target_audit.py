"""Diagnostico de reservas por destino: somente arquivos locais."""

import hashlib
import json
import re
from pathlib import Path

_KEY = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{16}\Z")


def _load_claim(path):
    if path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _valid_claim(record, key):
    if not isinstance(record, dict):
        return False
    target = record.get("target")
    if not isinstance(target, dict) or set(target) != {
        "operation", "board_id", "normalized_name"
    }:
        return False
    name = target.get("normalized_name")
    board = target.get("board_id")
    pid = record.get("proposal_id")
    digest = record.get("proposal_sha256")
    if not (
        record.get("status") == "TARGET_RESERVED"
        and record.get("operation") == "create_sprint"
        and target.get("operation") == "create_sprint"
        and record.get("retry_allowed") is False
        and isinstance(record.get("reserved_at"), str)
        and bool(record["reserved_at"])
        and type(pid) is str and _ID.fullmatch(pid)
        and type(digest) is str and _KEY.fullmatch(digest)
        and type(board) is int and board > 0
        and type(name) is str and 1 <= len(name) <= 80
        and name == name.strip().casefold()
    ):
        return False
    actual = hashlib.sha256(json.dumps(
        target, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return actual == key


def _matches_attempt(claim, attempt):
    if not isinstance(attempt, dict):
        return False
    request = attempt.get("request")
    if not isinstance(request, dict):
        return False
    payload = request.get("payload")
    if not isinstance(payload, dict):
        return False
    target = claim["target"]
    name = payload.get("name")
    return (
        attempt.get("proposal_id") == claim["proposal_id"]
        and attempt.get("proposal_sha256") == claim["proposal_sha256"]
        and attempt.get("operation") == "create_sprint"
        and attempt.get("status") == "RESERVED"
        and request.get("method") == "POST"
        and request.get("endpoint") == "/rest/agile/1.0/sprint"
        and set(payload) == {"name", "originBoardId"}
        and type(name) is str
        and name.strip().casefold() == target["normalized_name"]
        and type(payload.get("originBoardId")) is int
        and payload["originBoardId"] == target["board_id"]
    )


def inspect_target_claims(store, attempts):
    """Relatorio nao autoritativo; nunca concede nova tentativa."""
    folder = Path(store).resolve() / "target_claims"
    items = []
    if not folder.is_dir():
        return items
    for path in sorted(folder.glob("*.json")):
        key = path.stem
        claim = _load_claim(path)
        item = {"marker": path.name, "retry_allowed": False}
        if not _KEY.fullmatch(key) or not _valid_claim(claim, key):
            item["status"] = "INVALID_TARGET_CLAIM"
        else:
            pid = claim["proposal_id"]
            item.update({
                "proposal_id": pid,
                "board_id": claim["target"]["board_id"],
                "normalized_name": claim["target"]["normalized_name"],
            })
            if pid not in attempts:
                item["status"] = "TARGET_RESERVED_NO_ATTEMPT"
            elif _matches_attempt(claim, attempts[pid]):
                item["status"] = "TARGET_RESERVED_WITH_ATTEMPT"
            else:
                item["status"] = "TARGET_CLAIM_ATTEMPT_MISMATCH"
        items.append(item)
    return items
