"""
OPTIONAL one-time setup — enables full Long-Method smell detection.

02_scan_pilot_batch.py detects two code smells from Methodology §3.3.2
(God Class via SonarJava S6539 "Monster Class", Long Method via S138
"Methods should not have too many lines"). S6539 is active in SonarQube's
built-in "Sonar way" Java profile by default; S138 is NOT. SonarQube
refuses to modify built-in profiles directly (verified: POST
activate_rule against "Sonar way" returns 400 "Operation forbidden for
built-in Quality Profile"), so getting S138 active requires a small,
one-time setup: create a custom profile copied from "Sonar way", activate
S138 on the copy, and make it the instance's default Java profile.

This is OPTIONAL and SAFE to skip: if you don't run this, god_class_smells
will still be captured correctly (S6539 needs no setup); long_method_smells
will just read 0 for everything (not wrong data - just an unmeasured
signal) until you do. Nothing else in the pipeline depends on this having
been run.

This DOES modify your SonarQube server's Java default profile - reasonable
for a local, project-dedicated Docker instance (which is what this
project's docs assume - see demo/README.md's prerequisites), but you
should NOT run this against a shared/organizational SonarQube server
without checking with whoever else uses it first.

Usage:
    python 00_setup_sonar_profile.py
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CUSTOM_PROFILE_NAME = "PPCH Java (Sonar way + Long Method)"
RULE_TO_ADD = "java:S138"


def load_env():
    load_dotenv(ROOT / ".env")
    token = os.getenv("SONAR_TOKEN")
    host = os.getenv("SONAR_HOST_URL", "http://localhost:9000")
    if not token:
        raise RuntimeError("SONAR_TOKEN not found in .env")
    return token, host.rstrip("/")


def main():
    token, host = load_env()

    resp = requests.get(f"{host}/api/qualityprofiles/search", params={"language": "java"}, auth=(token, ""))
    resp.raise_for_status()
    profiles = resp.json()["profiles"]

    existing = next((p for p in profiles if p["name"] == CUSTOM_PROFILE_NAME), None)
    if existing:
        print(f"Profile '{CUSTOM_PROFILE_NAME}' already exists — reusing it.")
        profile_key = existing["key"]
    else:
        sonar_way = next(p for p in profiles if p["isBuiltIn"] and p["isDefault"])
        print(f"Copying '{sonar_way['name']}' -> '{CUSTOM_PROFILE_NAME}'...")
        resp = requests.post(
            f"{host}/api/qualityprofiles/copy",
            params={"fromKey": sonar_way["key"], "toName": CUSTOM_PROFILE_NAME},
            auth=(token, ""),
        )
        resp.raise_for_status()
        profile_key = resp.json()["key"]

    print(f"Activating {RULE_TO_ADD} on '{CUSTOM_PROFILE_NAME}'...")
    resp = requests.post(
        f"{host}/api/qualityprofiles/activate_rule",
        params={"key": profile_key, "rule": RULE_TO_ADD},
        auth=(token, ""),
    )
    if resp.status_code not in (200, 204):
        print(f"  [warn] activate_rule returned {resp.status_code}: {resp.text[:300]}")
        print("  (this is fine if the rule was already active)")

    print(f"Setting '{CUSTOM_PROFILE_NAME}' as the default Java profile...")
    resp = requests.post(
        f"{host}/api/qualityprofiles/set_default",
        params={"qualityProfile": CUSTOM_PROFILE_NAME, "language": "java"},
        auth=(token, ""),
    )
    resp.raise_for_status()

    resp = requests.get(
        f"{host}/api/rules/search",
        params={"qprofile": profile_key, "activation": "true", "rule_key": RULE_TO_ADD},
        auth=(token, ""),
    )
    active = resp.json().get("total", 0) > 0
    print(f"\nDone. {RULE_TO_ADD} active in default Java profile: {active}")
    if not active:
        print("Something didn't take — long_method_smells will still read 0. "
              "god_class_smells (S6539) is unaffected either way.")


if __name__ == "__main__":
    main()
