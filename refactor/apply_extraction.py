"""Refactor layer — applies an Act-layer ILP suggestion to the ORIGINAL
source file automatically, producing a COMPLETE refactored file, not just an
isolated snippet the developer has to hand-assemble.

This is a deliberately SEPARATE module from Act (mirroring the top-level
sense/ analyze/ act/ structure with a sibling refactor/ folder), because
"decide what to extract and describe it" (Act, advisory) and "actually apply
that decision to a file" (Refactor, mechanical) are different
responsibilities. Act stays honestly advisory; this module does the
mechanical text transformation on top of what Act already decided - it does
NOT re-run any prediction or re-decide anything.

How it works (text splicing on tracked line numbers, not full AST
regeneration - preserves the original file's exact formatting/comments, but
does not verify the result compiles):
  1. Read act_result.json (the Act layer's output for one file/method).
  2. Refuse immediately if the suggestion is not safe_to_auto_apply (e.g. it
     modifies multiple variables that are used elsewhere in the method - see
     java_statement_extractor.render_extraction_suggestion's return-value
     analysis) - rather than guess at unsafe code.
  3. Replace the extracted line range in the original method with the
     suggestion's call_site_replacement line.
  4. Find the (now-shortened) original method's closing brace, and insert
     the suggestion's full_snippet (the new extracted method) right after it.
  5. Write the complete result to the output path.

Usage:
    python refactor/apply_extraction.py \
        --source demo/java_project_before/PricingEngine.java \
        --act-result demo/results/before/act_result.json \
        --output demo/java_project_after/PricingEngine.java
"""

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
ROOT = THIS_FILE.parents[1]  # ppch-framework/
ILP_ENGINE_DIR = ROOT / "act" / "ilp-engine"
sys.path.insert(0, str(ILP_ENGINE_DIR))

from java_statement_extractor import _extend_to_balanced_braces  # noqa: E402


def find_enclosing_method_end(source_lines: list, method_start_line: int) -> int:
    """Find the line of the closing brace of the method that starts at
    method_start_line, by counting braces from that line forward - reusing
    the same brace-balancing helper the Act layer uses for extraction
    snippets, applied here to the whole enclosing method instead."""
    end, balanced = _extend_to_balanced_braces(source_lines, method_start_line, method_start_line)
    if not balanced:
        raise RuntimeError(
            f"Could not find a balanced closing brace for the method starting at "
            f"line {method_start_line} — refusing to auto-apply rather than guess."
        )
    return end


def apply_extraction_to_text(source_text: str, act_result: dict) -> tuple:
    """Pure-text core of apply_extraction: same validation and splice logic,
    but operating on an in-memory string instead of reading/writing files.
    Factored out so callers doing several extractions in sequence on the
    same file (see act/refactor_file.py's iterative single-file loop, which
    may need to extract from the same method more than once, or from
    several methods in turn) can chain them in memory without a
    round-trip through the filesystem between each one.

    Returns (new_text, info) where `info` has the same fields as
    apply_extraction()'s return value, minus the file-path-specific ones.
    Raises RuntimeError on the same unsafe/invalid conditions
    apply_extraction() does - this IS apply_extraction()'s validation, not a
    separate, looser copy of it.
    """
    # "threshold_unreachable" is accepted alongside "optimal": it means the
    # solver couldn't get remaining complexity under the target ceiling with
    # a single safe extraction, not that the suggestion is unsafe - safety
    # (brace-balanced, single self-contained root, valid return handling) is
    # exactly what safe_to_auto_apply below is for, independent of status.
    if act_result.get("status") not in ("optimal", "threshold_unreachable"):
        raise RuntimeError(
            f"act_result status is '{act_result.get('status')}', not 'optimal' or "
            "'threshold_unreachable' — there is no suggestion to apply."
        )

    suggestion = act_result.get("suggestion")
    if not suggestion or not suggestion.get("rendered"):
        raise RuntimeError("act_result has no rendered suggestion to apply.")

    if not suggestion.get("safe_to_auto_apply", False):
        raise RuntimeError(
            "This suggestion is flagged safe_to_auto_apply=False "
            f"(return_analysis: {suggestion.get('return_analysis')}). It modifies "
            "multiple variables that are also used elsewhere in the method, which "
            "cannot be safely carried back through a single return value. Refusing "
            "to auto-apply — this case needs manual restructuring. See the "
            "suggestion's 'caveat' field for the specific reason."
        )

    method_start_line = act_result.get("method_start_line")
    if method_start_line is None:
        raise RuntimeError(
            "act_result.json has no 'method_start_line' — re-run the Act layer "
            "with the current pipeline.py / act_decide_and_suggest.py version."
        )

    source_lines = source_text.splitlines()
    extract_start, extract_end = suggestion["source_line_range"]

    # Match the surrounding code's indentation for the replacement call line.
    first_line = source_lines[extract_start - 1]
    call_site_indent = first_line[: len(first_line) - len(first_line.lstrip())]
    replacement_line = f"{call_site_indent}{suggestion['call_site_replacement']}"

    # 1) Splice out the extracted lines, replace with the single call-site line.
    new_lines = source_lines[: extract_start - 1] + [replacement_line] + source_lines[extract_end:]

    # 2) Find where the (now-shortened) original method ends, on the SPLICED
    # lines directly (recomputing rather than offsetting avoids off-by-one
    # errors from the line-count change above).
    method_end_in_new = find_enclosing_method_end(new_lines, method_start_line)

    # The new method's SIGNATURE and CLOSING BRACE should sit at the same
    # indentation as the original method they're being inserted next to
    # (class-member level); its BODY lines are already correctly, uniformly
    # indented by render_extraction_suggestion's own normalization and must
    # NOT have extra indentation stacked on top of them.
    original_method_line = source_lines[method_start_line - 1]
    class_member_indent = original_method_line[: len(original_method_line) - len(original_method_line.lstrip())]

    new_method_lines = suggestion["full_snippet"].splitlines()
    if len(new_method_lines) >= 2:
        indented_new_method = (
            [f"{class_member_indent}{new_method_lines[0]}"]
            + new_method_lines[1:-1]
            + [f"{class_member_indent}{new_method_lines[-1]}"]
        )
    else:
        indented_new_method = [f"{class_member_indent}{line}" for line in new_method_lines]

    # 3) Insert the new extracted method right after the original method's
    # closing brace, with a blank line for readability.
    final_lines = (
        new_lines[:method_end_in_new]
        + [""]
        + indented_new_method
        + new_lines[method_end_in_new:]
    )

    new_text = "\n".join(final_lines) + "\n"
    info = {
        "status": "applied",
        "extracted_line_range": [extract_start, extract_end],
        "new_method_inserted_after_line": method_end_in_new,
        "suggested_method_name": suggestion["suggested_method_name"],
        "warning": (
            "This is an automated TEXT SPLICE, not a verified compilation. "
            "Always compile and review the output before treating it as final — "
            "this tool applies the Act layer's decision mechanically; it does not "
            "guarantee the result is correct Java."
        ),
    }
    return new_text, info


def apply_extraction(source_path: Path, output_path: Path, act_result: dict) -> dict:
    new_text, info = apply_extraction_to_text(source_path.read_text(encoding="utf-8"), act_result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(new_text, encoding="utf-8")
    return {
        "source_file": str(source_path),
        "output_file": str(output_path),
        **info,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Path to the ORIGINAL .java file")
    parser.add_argument("--act-result", required=True, help="Path to act_result.json from the Act layer")
    parser.add_argument("--output", required=True, help="Path to write the refactored .java file")
    args = parser.parse_args()

    act_result = json.loads(Path(args.act_result).read_text(encoding="utf-8"))
    result = apply_extraction(Path(args.source), Path(args.output), act_result)

    print(json.dumps(result, indent=2))
    print(f"\nWrote {args.output}")
    print("Reminder: this is a text splice, not a verified compile — review before use.")


if __name__ == "__main__":
    main()
