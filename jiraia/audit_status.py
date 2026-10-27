"""Local-only diagnostic of JIRAIA write markers; no network or mutations."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

_ID = re.compile(r"[0-9a-f]{16}\Z")
_RECON = re.compile(r"create_sprint-board_([1-9][0-9]*)-sprint_([1-9][0-9]*)\.json\Z")


def _records(folder):
    result = {}
    if not folder.is_dir():
        return result
    for path in sorted(folder.glob("*.json")):
        if _ID.fullmatch(path.stem):
            try:
                result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                result[path.stem] = None
    return result


def _valid_attempt(record, identifier):
    return (
        isinstance(record, dict)
        and record.get("proposal_id") == identifier
        and record.get("operation") == "create_sprint"
        and record.get("status") == "RESERVED"
        and isinstance(record.get("proposal_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", record["proposal_sha256"]) is not None
        and isinstance(record.get("request"), dict)
        and record["request"].get("method") == "POST"
        and record["request"].get("endpoint") == "/rest/agile/1.0/sprint"
        and isinstance(record["request"].get("payload"), dict)
        and set(record["request"]["payload"]) == {"name", "originBoardId"}
        and isinstance(record["request"]["payload"].get("name"), str)
        and type(record["request"]["payload"].get("originBoardId")) is int
    )


def _valid_dispatch(record, identifier, attempt):
    return (
        isinstance(record, dict)
        and record.get("proposal_id") == identifier
        and record.get("proposal_sha256") == attempt["proposal_sha256"]
        and record.get("operation") == "create_sprint"
        and record.get("request") == attempt["request"]
        and record.get("status") == "POST_MAY_HAVE_BEEN_SENT"
        and record.get("retry_allowed") is False
    )


def _valid_outcome(record, identifier, attempt):
    if not (
        isinstance(record, dict)
        and record.get("proposal_id") == identifier
        and record.get("retry_allowed") is False
    ):
        return False
    if record.get("status") == "SUCCESS_VERIFIED":
        payload = attempt["request"]["payload"]
        return (
            type(record.get("sprint_id")) is int
            and record["sprint_id"] > 0
            and record.get("sprint_name") == payload["name"]
            and record.get("origin_board_id") == payload["originBoardId"]
        )
    if record.get("status") == "UNKNOWN_NEEDS_RECONCILIATION":
        candidate = record.get("sprint_id_candidate")
        return (
            candidate is None or (type(candidate) is int and candidate > 0)
        ) and record.get("next_action") == "VERIFY_JIRA_BEFORE_NEW_PROPOSAL"
    return False


def inspect_local(store):
    """Return a non-authoritative summary; does not read credentials or call Jira."""
    store = Path(store).resolve()
    attempts = _records(store / "attempts")
    dispatches = _records(store / "real_dispatch")
    outcomes = _records(store / "real_outcomes")
    items = []
    for identifier in sorted(attempts.keys() | dispatches.keys() | outcomes.keys()):
        attempt = attempts.get(identifier)
        dispatch = dispatches.get(identifier)
        outcome = outcomes.get(identifier)
        if not _valid_attempt(attempt, identifier):
            status = "INCONSISTENT_LOCAL_RECORDS"
        elif identifier not in dispatches and identifier not in outcomes:
            status = "RESERVED_NO_DISPATCH_MARKER"
        elif identifier not in dispatches:
            status = "INCONSISTENT_LOCAL_RECORDS"
        elif not _valid_dispatch(dispatch, identifier, attempt):
            status = "INCONSISTENT_LOCAL_RECORDS"
        elif identifier not in outcomes:
            status = "DISPATCH_OUTCOME_MISSING"
        elif not _valid_outcome(outcome, identifier, attempt):
            status = "INCONSISTENT_LOCAL_RECORDS"
        elif outcome["status"] == "SUCCESS_VERIFIED":
            status = "SUCCESS_RECORDED_LOCALLY"
        else:
            status = "UNKNOWN_NEEDS_RECONCILIATION"
        items.append({"proposal_id": identifier, "status": status, "retry_allowed": False})

    reconciliation_items = []
    folder = store.parent / "reconciliations"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            match = _RECON.fullmatch(path.name)
            if match is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                data = None
            valid = (
                isinstance(data, dict)
                and data.get("status") == "EXTERNAL_SPRINT_OBSERVED"
                and type(data.get("board_id")) is int
                and str(data["board_id"]) == match.group(1)
                and type(data.get("sprint_id")) is int
                and str(data["sprint_id"]) == match.group(2)
                and data.get("jira_requests") == "GET_ONLY"
                and data.get("executed_by_jiraia") is False
            )
            reconciliation_items.append({
                "board_id": int(match.group(1)),
                "sprint_id": int(match.group(2)),
                "status": "EXTERNAL_OBSERVATION_RECORDED" if valid else "INCONSISTENT_LOCAL_RECORDS",
            })

    return {
        "mode": "LOCAL_FILES_ONLY",
        "warning": "Not Jira verification; not approval to execute or retry.",
        "attempts": items,
        "reconciliations": reconciliation_items,
        "counts": dict(sorted(Counter(item["status"] for item in items).items())),
    }


def main():
    from jiraia.action_engine import STORE
    parser = argparse.ArgumentParser(description="Inspect local JIRAIA audit markers (read-only)")
    parser.add_argument("--store", type=Path, default=STORE)
    arguments = parser.parse_args()
    print(json.dumps(inspect_local(arguments.store), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
