"""Branch-split: a second, structurally different Extract Method strategy,
alongside the main ILP-based single-region extraction (extract_method.py +
java_statement_extractor.py's render_extraction_suggestion).

MOTIVATION: the main ILP strategy selects one independent root (or, as of a
later fix, a contiguous run of same-parent siblings) and moves it out - the
rest of the enclosing method must be able to function unchanged with that
piece removed. This structurally cannot resolve a method whose complexity
comes from a SINGLE if/else statement where BOTH branches are individually
substantial: a then-branch and its matching else-branch are mutually
exclusive alternatives, not combinable siblings (see extract_method.py's
Statement.true_branch), so the ILP can never select "both branches,
replacing the if/else with two calls" as one coherent extraction.

Confirmed on a real case (Apache Commons Lang, FastDatePrinter.
appendFullDigits, PR #1470): manually splitting its top-level `if (value <
10000) {...} else {...}` into two purpose-named methods resolved the method
entirely (29 CC -> not flagged at all), confirmed via a real SonarQube scan
(file-total 133.0 -> 123.0). The ILP-based strategy alone could never find
this - neither branch alone is "the" complexity driver, and the "at most
one contiguous group" rule can't combine two mutually exclusive branches.

This module implements that specific, narrower pattern directly, completely
INDEPENDENT of extract_method.py's ILP solver - no shared state, no
modified constraints, nothing that touches the already-verified primary
mechanism. It's tried as a separate, additional strategy in
act/refactor_file.py, attempted only when the primary ILP strategy has
already given up on a method - purely additive, never a replacement.

SCOPE (deliberately conservative for a first, safety-first version):
  - Only genuine `if (...) { } else { }` pairs (a real else block, NOT a
    chained "else if" - see java_statement_extractor.is_chain_link for why
    a chain link is a different, already-handled case).
  - Only when NEITHER branch contains a `return`, `break`, or `continue` -
    same conservative safety posture as render_extraction_suggestion's own
    checks, for the same reason (a freestanding extracted method has no
    enclosing method-return-context/loop/switch to target).
  - Only when NEITHER branch has any variable that's both (a) assigned
    within that branch and (b) used anywhere else in the method outside
    this if/else's own span - both branches must be safely "void": nothing
    needs to flow back out to the caller. Multiple/complex outbound-
    variable cases are refused rather than guessed at, matching
    render_extraction_suggestion's own established policy exactly.
"""

import sys
import textwrap
from pathlib import Path

import javalang

sys.path.insert(0, str(Path(__file__).resolve().parent))
from java_statement_extractor import (  # noqa: E402
    _unwrap_block, _complexity_of_node, _contains_return, _contains_break_continue,
    _collect_declared_vars, _collect_used_vars, _collect_assigned_vars,
    _flatten_method_body, _extend_to_balanced_braces,
)

BODY_INDENT = "        "  # standard 8-space method-body indentation


def _branch_profile(stmts_list: list) -> dict:
    """Complexity + variable-flow + safety profile for `stmts_list` AS IF it
    were about to become its own, freestanding method body (nesting resets
    to 0) - the same question render_extraction_suggestion asks about an
    ILP-selected range, asked here about a WHOLE if/else branch instead."""
    flat = _flatten_method_body(stmts_list, nesting_depth=0)
    complexity = sum(_complexity_of_node(fs.node, fs.nesting_depth) for fs in flat)
    declared, used, assigned = set(), set(), set()
    for fs in flat:
        declared |= _collect_declared_vars(fs.node)
        used |= _collect_used_vars(fs.node)
        assigned |= _collect_assigned_vars(fs.node)
    return {
        "complexity": complexity,
        "declared": declared,
        "used": used,
        "assigned": assigned,
        "contains_return": _contains_return(stmts_list),
        "contains_break_continue": _contains_break_continue(stmts_list),
    }


def _find_if_else_pairs(node, out: list) -> None:
    """Recursively collect every genuine if/else pair (raw AST IfStatement
    whose else_statement is a real block, not a chained "else if") anywhere
    in `node`'s subtree."""
    if node is None:
        return
    if isinstance(node, (list, tuple, set)):
        for item in node:
            _find_if_else_pairs(item, out)
        return
    if not hasattr(node, "attrs"):
        return
    if isinstance(node, javalang.tree.IfStatement):
        if node.else_statement is not None and not isinstance(node.else_statement, javalang.tree.IfStatement):
            out.append(node)
    for attr_name in node.attrs:
        _find_if_else_pairs(getattr(node, attr_name, None), out)


def find_branch_split_candidates(
    source_text: str, method_node, meta: dict, min_branch_complexity: float = 2.0,
) -> list:
    """Find every eligible if/else pair in `method_node` where BOTH
    branches are safe (no return/break/continue, no outbound variables) and
    substantial enough to be worth splitting. Returns a list of dicts
    sorted by combined branch complexity descending - the caller tries the
    most impactful candidate first.

    `meta` is method_to_statements' own per-statement metadata for the
    WHOLE method (source_line -> used/assigned vars) - used to determine
    whether a branch-local variable is genuinely needed elsewhere in the
    method (the "used elsewhere" question, applied per-branch here)."""
    if_nodes = []
    _find_if_else_pairs(method_node.body, if_nodes)

    source_lines = source_text.splitlines()
    candidates = []
    for if_node in if_nodes:
        position = getattr(if_node, "position", None)
        if position is None:
            continue
        if_start_line = position.line

        then_stmts = _unwrap_block(if_node.then_statement)
        else_stmts = _unwrap_block(if_node.else_statement)
        if not then_stmts or not else_stmts:
            continue

        then_profile = _branch_profile(then_stmts)
        else_profile = _branch_profile(else_stmts)

        if then_profile["complexity"] < min_branch_complexity or else_profile["complexity"] < min_branch_complexity:
            continue  # not worth splitting - one side is trivial
        if then_profile["contains_return"] or else_profile["contains_return"]:
            continue
        if then_profile["contains_break_continue"] or else_profile["contains_break_continue"]:
            continue

        # This if/else's own full line span - start from its own header
        # line and let brace-balancing consume through BOTH the then- and
        # else-blocks' closing braces (same proven mechanism used
        # throughout the main strategy).
        end_line, is_balanced = _extend_to_balanced_braces(source_lines, if_start_line, if_start_line)
        if not is_balanced:
            continue

        # Outbound-variable safety: a variable assigned within EITHER
        # branch that's also used/assigned ANYWHERE ELSE in the method
        # (outside this if/else's own span) would need to flow back out -
        # this first, safety-first version refuses that case entirely
        # rather than guess at how to thread it back (matches
        # render_extraction_suggestion's own "multiple outbound variables"
        # refusal policy - conservative on purpose).
        outbound_risk = False
        for name in then_profile["assigned"] | else_profile["assigned"]:
            for i, m in meta.items():
                line = m.get("source_line")
                if line is None or if_start_line <= line <= end_line:
                    continue  # inside this if/else - not "elsewhere"
                if name in m.get("used_vars", set()) or name in m.get("assigned_vars", set()):
                    outbound_risk = True
                    break
            if outbound_risk:
                break
        if outbound_risk:
            continue

        candidates.append({
            "if_node": if_node,
            "if_start_line": if_start_line,
            "end_line": end_line,
            "then_stmts": then_stmts,
            "else_stmts": else_stmts,
            "then_profile": then_profile,
            "else_profile": else_profile,
            "combined_complexity": then_profile["complexity"] + else_profile["complexity"],
        })

    candidates.sort(key=lambda c: -c["combined_complexity"])
    return candidates


def _branch_line_range(source_lines: list, stmts_list: list) -> tuple:
    """The [start, end] (1-indexed, inclusive) line range of `stmts_list`
    (a then- or else-branch's own statement list) within the ORIGINAL
    method, balanced against its own braces - the exact span that will be
    replaced by a single call and moved into a new method."""
    positions = [getattr(s, "position", None) for s in stmts_list]
    lines = [p.line for p in positions if p]
    if not lines:
        return None, None
    start = min(lines)
    end, is_balanced = _extend_to_balanced_braces(source_lines, start, max(lines))
    return (start, end) if is_balanced else (None, None)


def _render_branch_method(source_lines: list, name: str, start: int, end: int, params: list, type_map: dict) -> str:
    branch_source = "\n".join(source_lines[start - 1:end])
    dedented = textwrap.dedent(branch_source)
    reindented = "\n".join(f"{BODY_INDENT}{ln}" if ln.strip() else "" for ln in dedented.splitlines())
    param_list = ", ".join(f"{type_map.get(p, 'Object')} {p}" for p in params)
    return f"private static void {name}({param_list}) {{\n{reindented}\n}}"


def render_branch_split(source_text: str, method_name: str, candidate: dict, type_map: dict) -> dict:
    """Render `candidate` (from find_branch_split_candidates) into two
    ready-to-copy new methods plus the two call-site replacements for the
    original if/else's then- and else-branches - the branch-split analogue
    of render_extraction_suggestion."""
    source_lines = source_text.splitlines()

    then_start, then_end = _branch_line_range(source_lines, candidate["then_stmts"])
    else_start, else_end = _branch_line_range(source_lines, candidate["else_stmts"])
    if then_start is None or else_start is None:
        return {"rendered": False, "reason": "could_not_balance_branch_braces"}

    # Only names FOUND in type_map (the method's own parameters + local
    # declarations) become parameters. A used-but-undeclared name NOT in
    # type_map is almost certainly a class-level static field/constant
    # (Java allows referencing those unqualified from any static method in
    # the same class) - type_map has no entry for those at all (it's only
    # ever populated from parameters/locals), so guessing a parameter type
    # for one defaults to "Object", which is actively WRONG when that name
    # is then used somewhere requiring a real type (confirmed by a real
    # case: `new char[MAX_DIGITS]` with MAX_DIGITS typed Object is invalid
    # Java - an array size must be int-compatible). Left un-parameterized,
    # the new method (same class, same static context) can reference it
    # directly, exactly like the original code already did.
    then_params = sorted(
        name for name in candidate["then_profile"]["used"] - candidate["then_profile"]["declared"]
        if name in type_map
    )
    else_params = sorted(
        name for name in candidate["else_profile"]["used"] - candidate["else_profile"]["declared"]
        if name in type_map
    )

    then_name = f"{method_name}IfBranch"
    else_name = f"{method_name}ElseBranch"

    then_snippet = _render_branch_method(source_lines, then_name, then_start, then_end, then_params, type_map)
    else_snippet = _render_branch_method(source_lines, else_name, else_start, else_end, else_params, type_map)

    return {
        "rendered": True,
        "safe_to_auto_apply": True,
        "then_name": then_name,
        "else_name": else_name,
        "then_line_range": [then_start, then_end],
        "else_line_range": [else_start, else_end],
        "then_snippet": then_snippet,
        "else_snippet": else_snippet,
        "then_call": f"{then_name}({', '.join(then_params)});",
        "else_call": f"{else_name}({', '.join(else_params)});",
        "combined_complexity": candidate["combined_complexity"],
        "caveat": (
            "Splits BOTH branches of one if/else into two purpose-named methods - "
            "a structurally different strategy from the main single-region Extract "
            "Method. Parameter types are inferred from the original method's own "
            "parameters/locals - usually correct, but not verified to compile. "
            "Review before applying."
        ),
    }


def apply_branch_split_to_text(source_text: str, method_start_line: int, suggestion: dict) -> tuple:
    """Splice `suggestion` (from render_branch_split) into `source_text`:
    replace each branch's inner content with a single call, then insert
    both new methods after the enclosing method's closing brace. Mirrors
    refactor/apply_extraction.py's apply_extraction_to_text exactly, just
    with two splices and two new methods instead of one."""
    if not suggestion.get("rendered") or not suggestion.get("safe_to_auto_apply"):
        raise RuntimeError("branch-split suggestion is not safe_to_auto_apply.")

    source_lines = source_text.splitlines()
    then_start, then_end = suggestion["then_line_range"]
    else_start, else_end = suggestion["else_line_range"]

    def indent_of(line_no: int) -> str:
        line = source_lines[line_no - 1]
        return line[: len(line) - len(line.lstrip())]

    # Splice from the BOTTOM up (else comes after then in the file) so
    # earlier line numbers stay valid while later ones are being replaced.
    new_lines = source_lines[:]
    new_lines[else_start - 1:else_end] = [f"{indent_of(else_start)}{suggestion['else_call']}"]
    new_lines[then_start - 1:then_end] = [f"{indent_of(then_start)}{suggestion['then_call']}"]

    end_of_method, balanced = _extend_to_balanced_braces(new_lines, method_start_line, method_start_line)
    if not balanced:
        raise RuntimeError("Could not find a balanced closing brace for the enclosing method.")

    original_method_line = source_lines[method_start_line - 1]
    class_member_indent = original_method_line[: len(original_method_line) - len(original_method_line.lstrip())]

    def indent_snippet(snippet: str) -> list:
        lines = snippet.splitlines()
        if len(lines) >= 2:
            return [f"{class_member_indent}{lines[0]}"] + lines[1:-1] + [f"{class_member_indent}{lines[-1]}"]
        return [f"{class_member_indent}{ln}" for ln in lines]

    final_lines = (
        new_lines[:end_of_method]
        + [""] + indent_snippet(suggestion["then_snippet"])
        + [""] + indent_snippet(suggestion["else_snippet"])
        + new_lines[end_of_method:]
    )

    new_text = "\n".join(final_lines) + "\n"
    info = {
        "status": "applied",
        "strategy": "branch_split",
        "then_method": suggestion["then_name"],
        "else_method": suggestion["else_name"],
    }
    return new_text, info
