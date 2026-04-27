"""Convert Bandit JSON output into a minimal SARIF report."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _level(issue_severity: str) -> str:
    mapping = {
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "note",
    }
    return mapping.get(issue_severity.upper(), "warning")


def _rule(issue: dict) -> dict:
    test_id = issue.get("test_id", "bandit")
    return {
        "id": test_id,
        "name": issue.get("test_name", test_id),
        "shortDescription": {"text": issue.get("issue_text", test_id)},
        "properties": {
            "tags": [
                f"severity:{issue.get('issue_severity', 'UNKNOWN')}",
                f"confidence:{issue.get('issue_confidence', 'UNKNOWN')}",
            ],
        },
    }


def _result(issue: dict) -> dict:
    filename = issue.get("filename", "")
    line = issue.get("line_number", 1)
    return {
        "ruleId": issue.get("test_id", "bandit"),
        "level": _level(issue.get("issue_severity", "MEDIUM")),
        "message": {"text": issue.get("issue_text", "Bandit finding")},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": filename},
                    "region": {"startLine": line},
                }
            }
        ],
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: bandit_json_to_sarif.py <input.json> <output.sarif>", file=sys.stderr)
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    bandit = json.loads(input_path.read_text(encoding="utf-8"))
    results = bandit.get("results", [])

    unique_rules: dict[str, dict] = {}
    for issue in results:
        unique_rules.setdefault(issue.get("test_id", "bandit"), _rule(issue))

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Bandit",
                        "informationUri": "https://bandit.readthedocs.io/",
                        "rules": list(unique_rules.values()),
                    }
                },
                "results": [_result(issue) for issue in results],
            }
        ],
    }
    output_path.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
