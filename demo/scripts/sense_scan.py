"""Demo Sense layer — scans a local Java project directory (java_project_before/
or java_project_after/) with the SAME SonarScanner setup used in the main
research pipeline, and returns the real cognitive_complexity of the target
file. This is the "before vs after" measurement step.

Unlike sense/scripts/02_scan_pilot_batch.py, there is no git checkout here -
the demo works on a plain local folder, since there is no PR history for a
standalone file. Everything else (unique project keys, polling for analysis
completion, querying the per-file measure, cleaning up afterward) reuses the
exact same approach validated on the real 150-PR dataset.

Usage:
    python sense_scan.py --version before
    python sense_scan.py --version after
"""

import argparse
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPTS_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPTS_DIR.parent
ROOT = DEMO_DIR.parent  # ppch-framework/
TARGET_FILE = "PricingEngine.java"


def load_env():
    load_dotenv(ROOT / ".env")
    token = os.getenv("SONAR_TOKEN")
    host = os.getenv("SONAR_HOST_URL", "http://localhost:9000")
    if not token:
        raise RuntimeError("SONAR_TOKEN not found in .env — this demo reuses the main project's .env file.")
    return token, host.rstrip("/")


def project_dir_for(version: str) -> Path:
    return DEMO_DIR / f"java_project_{version}"


def run_scanner(project_dir: Path, project_key: str, sonar_token: str, sonar_host: str) -> bool:
    env = os.environ.copy()
    env["SONAR_HOST_URL"] = sonar_host
    env["SONAR_TOKEN"] = sonar_token
    r = subprocess.run(
        [
            "sonar-scanner",
            f"-Dsonar.projectKey={project_key}",
            f"-Dsonar.projectName={project_key}",
            "-Dsonar.sources=.",
            "-Dsonar.sourceEncoding=UTF-8",
        ],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        shell=(platform.system() == "Windows"),  # same Windows .bat fix as the main pipeline
    )
    if "EXECUTION SUCCESS" not in r.stdout:
        print("  [scan] FAILED:")
        print(r.stdout[-1500:])
        return False
    return True


def read_ce_task_url(project_dir: Path):
    report_file = project_dir / ".scannerwork" / "report-task.txt"
    if not report_file.exists():
        return None
    props = {}
    for line in report_file.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props.get("ceTaskUrl")


def wait_for_processing(ce_task_url: str, sonar_token: str, timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(ce_task_url, auth=(sonar_token, ""))
        status = resp.json().get("task", {}).get("status")
        if status == "SUCCESS":
            return True
        if status in ("FAILED", "CANCELED"):
            return False
        time.sleep(2)
    return False


def get_file_complexity(project_key: str, file_path: str, sonar_token: str, sonar_host: str):
    component_key = f"{project_key}:{file_path}"
    resp = requests.get(
        f"{sonar_host}/api/measures/component",
        params={"component": component_key, "metricKeys": "cognitive_complexity"},
        auth=(sonar_token, ""),
    )
    if resp.status_code != 200:
        return None
    for m in resp.json().get("component", {}).get("measures", []):
        if m["metric"] == "cognitive_complexity":
            return float(m["value"])
    return None


def delete_project(project_key: str, sonar_token: str, sonar_host: str):
    requests.post(f"{sonar_host}/api/projects/delete", params={"project": project_key}, auth=(sonar_token, ""))


def scan(version: str, target_file: str = TARGET_FILE) -> dict:
    sonar_token, sonar_host = load_env()
    project_dir = project_dir_for(version)
    if not project_dir.exists():
        raise RuntimeError(f"{project_dir} does not exist — create it first.")

    project_key = f"ppch-demo-{version}"
    print(f"Scanning {project_dir} as SonarQube project '{project_key}'...")

    if not run_scanner(project_dir, project_key, sonar_token, sonar_host):
        raise RuntimeError("SonarScanner run failed — see output above.")

    ce_task_url = read_ce_task_url(project_dir)
    if not ce_task_url or not wait_for_processing(ce_task_url, sonar_token):
        raise RuntimeError("Analysis did not finish processing in time.")

    complexity = get_file_complexity(project_key, target_file, sonar_token, sonar_host)
    delete_project(project_key, sonar_token, sonar_host)

    if complexity is None:
        raise RuntimeError(f"Could not retrieve cognitive_complexity for {target_file}.")

    result = {"version": version, "target_file": target_file, "cognitive_complexity": complexity}
    print(f"  {target_file}: cognitive_complexity = {complexity}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["before", "after"], required=True)
    parser.add_argument("--target-file", default=TARGET_FILE)
    args = parser.parse_args()

    result = scan(args.version, args.target_file)

    results_dir = DEMO_DIR / "results" / args.version
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "sense_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {results_dir / 'sense_result.json'}")


if __name__ == "__main__":
    main()
