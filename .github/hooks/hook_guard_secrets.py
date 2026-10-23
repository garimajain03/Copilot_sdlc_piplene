#!/usr/bin/env python3
import json
import re
import sys

SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{30,}",
    r"AIza[0-9A-Za-z\-_]{35}",
    r"AKIA[0-9A-Z]{16}",
    r"(?i)api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"(?i)secret\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{12,}",
]

PROTECTED_FILE_PATTERNS = [
    r"(?:^|/)\.env(?:\.[a-zA-Z0-9_.-]+)?$",
    r"\.(pem|key|cert)$",
    r"\.(tfvars|auto\.tfvars|tfstate|tfstate\.backup)$",
    r"(?:^|/)(credentials|secrets)(\.[a-zA-Z0-9_.-]+)?$",
    r"(?:^|/)\.aws/(credentials|config)",
    r"(?:^|/)\.ssh/",
    r"(?:^|/)kubeconfig$",
    r"(?:^|/)\.kube/config$",
    r"(?:^|/)values-.*\.yaml$",
    r"application_default_credentials\.json$",
]


def _extract_text_and_paths(payload: dict) -> tuple[str, list[str]]:
    tool_input = payload.get("toolInput", {})
    paths = []
    if isinstance(tool_input, dict):
        for k in ("filePath", "file_path", "path", "uri"):
            if k in tool_input and tool_input[k]:
                paths.append(str(tool_input[k]))
        pieces = [str(v) for v in tool_input.values()]
        return "\n".join(pieces), paths
    return str(tool_input), paths


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    text, paths = _extract_text_and_paths(payload)

    for path in paths:
        if any(re.search(p, path, re.IGNORECASE) for p in PROTECTED_FILE_PATTERNS):
            if not re.search(r"\.(example|sample|template)$", path, re.IGNORECASE):
                print(json.dumps({"error": f"Blocked: access to protected secret file {path}."}))
                sys.exit(2)

    if any(re.search(p, text) for p in SECRET_PATTERNS):
        print(json.dumps({"error": "Blocked: possible secret detected in tool input."}))
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
