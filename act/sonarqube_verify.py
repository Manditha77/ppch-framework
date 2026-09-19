"""Shared helper: verify a Java file's before/after cognitive complexity
against a REAL SonarQube scan, checking SonarQube's own PER-METHOD S3776
rule (not just the file-level aggregate metric - see the module-level note
below for why that distinction matters). Used by both act/refactor_file.py
(the standalone, PR-independent tool) and
act/github-action/verify_pr_suggestion.py (real historical-PR case-study
verification), so this logic - and its safety properties - live in exactly
one place.

Scans an ISOLATED temp-directory copy of just the target file, so
unrelated files that might live alongside the real file on disk don't
pollute the measurement. Requires SONAR_TOKEN/SONAR_HOST_URL in .env and
sonar-scanner on PATH, same setup as the rest of this project.
"""

import os
import platform
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # ppch-framework/


def verify_with_sonarqube(target_filename: str, before_text: str, after_text: str, quiet: bool = False) -> dict:
    """Returns {"before": float|None, "after": float|None,
    "before_issues": [...], "after_issues": [...]} where *_issues are
    SonarQube's own S3776 ("Refactor this method to reduce its Cognitive
    Complexity from X to the Y allowed") issues - the real, per-method
    ground truth, independent of this framework's own Campbell-rule
    approximation. Empty dict (not an error) if SONAR_TOKEN isn't
    configured, since this is always an optional verification step, never
    required for the primary result."""
    load_dotenv(ROOT / ".env")
    token = os.getenv("SONAR_TOKEN")
    host = os.getenv("SONAR_HOST_URL", "http://localhost:9000").rstrip("/")
    if not token:
        if not quiet:
            print("  [verify] SONAR_TOKEN not set in .env - skipping SonarQube verification.")
        return {}

    def log(msg):
        if not quiet:
            print(msg)

    def scan_one(text: str, label: str):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / target_filename).write_text(text, encoding="utf-8")
            project_key = f"ppch-verify-{label}-{uuid.uuid4().hex[:8]}"
            env = os.environ.copy()
            env["SONAR_HOST_URL"] = host
            env["SONAR_TOKEN"] = token
            r = subprocess.run(
                [
                    "sonar-scanner",
                    f"-Dsonar.projectKey={project_key}",
                    f"-Dsonar.projectName={project_key}",
                    "-Dsonar.sources=.",
                    "-Dsonar.sourceEncoding=UTF-8",
                ],
                cwd=tmp_path, env=env, capture_output=True, text=True,
                shell=(platform.system() == "Windows"),
            )
            if "EXECUTION SUCCESS" not in r.stdout:
                log(f"  [verify] SonarQube scan FAILED for {label}:")
                log(r.stdout[-800:])
                return None, []

            report_file = tmp_path / ".scannerwork" / "report-task.txt"
            props = {}
            for line in report_file.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v
            ce_task_url = props.get("ceTaskUrl")

            status = None
            start = time.time()
            while ce_task_url and time.time() - start < 120:
                resp = requests.get(ce_task_url, auth=(token, ""))
                status = resp.json().get("task", {}).get("status")
                if status in ("SUCCESS", "FAILED", "CANCELED"):
                    break
                time.sleep(2)

            complexity = None
            per_method_issues = []
            if status == "SUCCESS":
                component_key = f"{project_key}:{target_filename}"
                resp = requests.get(
                    f"{host}/api/measures/component",
                    params={"component": component_key, "metricKeys": "cognitive_complexity"},
                    auth=(token, ""),
                )
                for m in resp.json().get("component", {}).get("measures", []):
                    if m["metric"] == "cognitive_complexity":
                        complexity = float(m["value"])

                # The FILE-level metric above is a sum across every method -
                # not directly comparable to a PER-METHOD threshold once a
                # file has more than one method (see
                # sense/scripts/03_build_feature_table.py's docstring for
                # the fuller story of why that distinction matters here).
                # SonarQube's own S3776 rule is raised PER METHOD, so it's
                # the real ground truth for "is this specific method fixed."
                resp = requests.get(
                    f"{host}/api/issues/search",
                    params={"componentKeys": project_key, "rules": "java:S3776"},
                    auth=(token, ""),
                )
                per_method_issues = [
                    {"message": issue.get("message"), "line": issue.get("line")}
                    for issue in resp.json().get("issues", [])
                ]

            requests.post(f"{host}/api/projects/delete", params={"project": project_key}, auth=(token, ""))
            return complexity, per_method_issues

    log("  [verify] Running real SonarQube scans (before/after, isolated copies)...")
    before_complexity, before_issues = scan_one(before_text, "before")
    after_complexity, after_issues = scan_one(after_text, "after")
    if before_complexity is not None and after_complexity is not None:
        change = after_complexity - before_complexity
        log(f"  [verify] SonarQube file-total cognitive_complexity: "
            f"{before_complexity} -> {after_complexity} ({change:+.1f})")
    if after_issues:
        log(f"  [verify] SonarQube STILL flags {len(after_issues)} method(s) over its complexity limit after refactoring:")
        for issue in after_issues:
            log(f"    - line {issue['line']}: {issue['message']}")
    elif before_issues:
        log(f"  [verify] SonarQube confirms: all {len(before_issues)} previously-flagged method(s) are now clean.")
    return {
        "before": before_complexity, "after": after_complexity,
        "before_issues": before_issues, "after_issues": after_issues,
    }
