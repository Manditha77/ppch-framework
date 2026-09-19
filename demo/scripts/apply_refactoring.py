"""Demo wrapper around the shared refactor/apply_extraction.py module.

Automatically applies the Act layer's suggestion to PricingEngine.java and
writes the COMPLETE refactored result to java_project_after/, including
copying the unchanged supporting files (Customer.java, Order.java,
CustomerTier.java) so java_project_after/ is immediately ready to scan.

This REPLACES manually retyping the suggestion by hand (the old Step 3).
You should still open and review the output before treating it as final -
this automates the mechanical transformation, it does not verify the result
compiles.

Usage:
    python apply_refactoring.py --version before
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPTS_DIR.parent
ROOT = DEMO_DIR.parent  # ppch-framework/
sys.path.insert(0, str(ROOT / "refactor"))

from apply_extraction import apply_extraction  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="before", help="Which act_result.json to apply")
    parser.add_argument("--target-file", default="PricingEngine.java")
    args = parser.parse_args()

    act_result_path = DEMO_DIR / "results" / args.version / "act_result.json"
    if not act_result_path.exists():
        raise RuntimeError(
            f"{act_result_path} not found — run act_decide_and_suggest.py --version {args.version} first."
        )
    act_result = json.loads(act_result_path.read_text(encoding="utf-8"))

    before_dir = DEMO_DIR / f"java_project_{args.version}"
    after_dir = DEMO_DIR / "java_project_after"
    after_dir.mkdir(parents=True, exist_ok=True)

    # Copy every OTHER .java file unchanged, so java_project_after/ is
    # immediately complete and scannable.
    for java_file in before_dir.glob("*.java"):
        if java_file.name != args.target_file:
            shutil.copy2(java_file, after_dir / java_file.name)
            print(f"Copied unchanged: {java_file.name}")

    source_path = before_dir / args.target_file
    output_path = after_dir / args.target_file
    result = apply_extraction(source_path, output_path, act_result)

    print(json.dumps(result, indent=2))
    print(f"\nWrote {output_path}")
    print(
        "\nIMPORTANT: open and review this file before continuing to Step 4 — "
        "this is an automated text splice, not a verified compile. Confirm it "
        "looks correct (and compiles, if you have a Java toolchain handy) "
        "before scanning it as the 'after' version."
    )


if __name__ == "__main__":
    main()
