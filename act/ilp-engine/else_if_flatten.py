"""A third, independent refactoring strategy: else-if flattening.

Motivation (found via direct analysis of a real, user-flagged case,
2026-09-23): SonarSource's own Cognitive Complexity spec gives `else if`
special treatment - a chained `else if` link does NOT compound nesting
the way a genuinely nested `if` does (already correctly modeled in this
framework's own Campbell-rule reproduction - see
java_statement_extractor.py's own "else if" handling in
method_to_statements). But that special treatment only applies when the
code is ACTUALLY WRITTEN as `else if`, not as the semantically-identical
`else { if (...) { ... } }`. Real code (including PPCH-framework's own
test file, ComplexityTestUtil.classifyTransaction) frequently uses the
nested form purely by habit, paying a real, unnecessary nesting-depth
complexity cost for something Java's grammar treats as interchangeable.

This is a PURE SYNTACTIC transformation, not a structural one: Java
guarantees `else { if (c) {A} else {B} }` and `else if (c) {A} else {B}`
execute identically whenever the else-block's ENTIRE content is exactly
one if-statement and nothing else (no other statements, no comments that
would be silently dropped by a naive rewrite). This is why it's lower-risk
than extraction or branch-split: there is no new method, no parameter
inference, no variable-scope reasoning - just removing one redundant
brace pair. It's applied as a pre-pass (even before branch-split), since
flattening can turn a method that LOOKS unfixably deep into a flatter
shape where the ILP solver's contiguous-region search or branch-split's
independent-branch search has real material to work with.

Deliberately conservative about what it attempts (mirrors branch_split.py's
own safety posture):
  - Only fires when the else-block contains EXACTLY one statement, and
    that statement is itself an IfStatement - anything else in the
    else-block (another statement before/after, a comment-only block,
    etc.) is left alone.
  - Only fires when the inner if's own header (`if (...) {`) is a SINGLE
    LINE - a wrapped multi-line condition is skipped rather than risk a
    fragile multi-line splice.
  - Verifies the text between the else-block's opening brace and the
    inner if's `if` keyword is pure whitespace (nothing hidden there -
    e.g. a comment - that a naive rewrite would silently delete).
  - Every application is verified with a real javalang.parse.parse()
    call before being accepted, same as every other text-mutating step
    in this codebase.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import javalang  # noqa: E402

from java_statement_extractor import _extend_to_balanced_braces  # noqa: E402


def _find_flatten_candidates(method_node) -> list:
    """Returns a list of (outer_if_node, else_block_node, inner_if_node)
    triples - every `else { <single IfStatement> }` pattern found in this
    method, in AST traversal order (outermost/earliest first, which matters
    since applying one can shift line numbers for the rest - callers should
    re-scan after each application, same pattern as branch_split.py's own
    pre-pass loop)."""
    candidates = []
    for _, node in method_node.filter(javalang.tree.IfStatement):
        else_stmt = node.else_statement
        if else_stmt is None or not isinstance(else_stmt, javalang.tree.BlockStatement):
            continue  # None = no else; NOT a BlockStatement = already "else if" (an IfStatement directly)
        inner = else_stmt.statements
        if len(inner) == 1 and isinstance(inner[0], javalang.tree.IfStatement):
            candidates.append((node, else_stmt, inner[0]))
    return candidates


def _line_is_blank(line: str) -> bool:
    return line.strip() == ""


def flatten_one(source_text: str, else_block_node, inner_if_node) -> str | None:
    """Attempts ONE else-if flattening. Returns the new source text, or
    None if this specific candidate doesn't meet the conservative safety
    checks (caller should just skip it, not treat None as an error)."""
    source_lines = source_text.splitlines(keepends=True)  # keepends: line-based edits must preserve original newlines

    else_open_line = else_block_node.position.line  # 1-indexed line containing the else-block's own '{'
    inner_if_line = inner_if_node.position.line

    # Safety: nothing but whitespace between the else-block's '{' and the
    # inner if's own 'if' keyword - if there's a comment or anything else
    # hiding there, a naive rewrite would silently delete it.
    else_line_text = source_lines[else_open_line - 1]
    brace_col = else_line_text.find("{")
    if brace_col == -1:
        return None  # the else block's own '{' isn't on the line javalang says it is - don't guess, skip
    after_brace = else_line_text[brace_col + 1:]
    if not _line_is_blank(after_brace):
        return None
    for lineno in range(else_open_line + 1, inner_if_line):
        if not _line_is_blank(source_lines[lineno - 1]):
            return None
    inner_if_line_text = source_lines[inner_if_line - 1]
    if_col = inner_if_line_text.find("if")
    if if_col == -1 or not _line_is_blank(inner_if_line_text[:if_col]):
        return None

    # Safety: the inner if's own header (`if (...) {`) must be a single
    # line - a wrapped multi-line condition is skipped, not risked.
    if "{" not in inner_if_line_text[if_col:]:
        return None
    inner_header = inner_if_line_text[if_col:].rstrip("\r\n")
    if not inner_header.rstrip().endswith("{"):
        return None  # something else follows the '{' on this line (e.g. a trailing comment) - skip, don't guess

    # Find where the inner if-statement's OWN complete structure (including
    # its own else/else-if chain, if any) ends, so we know which line holds
    # the OUTER else-block's now-redundant closing brace.
    inner_end_line, balanced = _extend_to_balanced_braces(
        [ln.rstrip("\r\n") for ln in source_lines], inner_if_line, inner_if_line,
    )
    if not balanced:
        return None

    # The outer else-block's closing '}' must be the very next line after
    # the inner if's own structure ends, containing NOTHING but that one
    # closing brace (confirms the else-block truly had nothing else in it
    # at the source-text level too, not just per the AST statement count).
    close_line_idx = inner_end_line  # 0-indexed access to the line AFTER inner_end_line (1-indexed)
    if close_line_idx >= len(source_lines):
        return None
    close_line_text = source_lines[close_line_idx]
    if close_line_text.strip("\r\n") != " " * (len(close_line_text) - len(close_line_text.lstrip(" ")) ) + "}":
        # exact match against "<indent>}" and nothing else on that line
        stripped = close_line_text.rstrip("\r\n")
        if stripped.strip() != "}":
            return None

    # All checks passed - perform the splice (bottom-up: remove the
    # redundant closing brace line FIRST, so line numbers for the earlier
    # edit stay valid).
    new_lines = list(source_lines)
    del new_lines[close_line_idx]  # remove the outer else-block's now-redundant closing '}' line
    # Merge: "<indent>} else {" + "<indent>if (cond) {" -> "<indent>} else if (cond) {"
    # (inner_header.split("if", 1)[1] already starts with the space that
    # was between "if" and "(" in the original - don't add another one.)
    new_lines[else_open_line - 1] = else_line_text[:brace_col] + "if" + inner_header.split("if", 1)[1] + "\n"

    # Dedent one level: everything from the inner if's own body through its
    # own closing brace (inner_if_line+1 .. inner_end_line) was previously
    # nested one level deeper than it needs to be now that the wrapping
    # else-block is gone. Purely cosmetic (doesn't change what parses or
    # what the complexity measurement sees - both already correct before
    # this step) but real code quality matters for anything presented as a
    # suggested fix, not just what technically compiles.
    indent_unit = "    "
    for lineno in range(inner_if_line + 1, inner_end_line + 1):
        idx = lineno - 1
        line = new_lines[idx]
        stripped = line.lstrip(" ")
        removed = len(line) - len(stripped)
        if stripped.strip("\r\n") == "":
            continue  # blank line - nothing to dedent
        if removed >= len(indent_unit):
            new_lines[idx] = line[len(indent_unit):]
        # else: less indentation than expected - leave as-is rather than guess

    del new_lines[inner_if_line - 1]  # the inner if's own header line is now redundant (merged above)

    return "".join(new_lines)


def flatten_else_if_chains(source_text: str) -> tuple:
    """Repeatedly finds and applies safe else-if flattenings across the
    WHOLE file (every method), until no more candidates are found or a
    safety cap is hit. Returns (new_source_text, applied_count).

    Verifies EVERY application with a real javalang.parse.parse() call
    before accepting it - if a splice ever produces invalid Java (a bug in
    the conservative checks above, or a genuinely unanticipated shape),
    that one candidate is discarded and the ORIGINAL text for that attempt
    is kept, not the broken result."""
    applied = 0
    for _ in range(50):  # generous cap; real files rarely have more than a handful of these
        try:
            tree = javalang.parse.parse(source_text)
        except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError):
            break  # shouldn't happen (we only ever commit parseable text) but never loop on unparseable input

        found_one = False
        for _, method_node in tree.filter(javalang.tree.MethodDeclaration):
            candidates = _find_flatten_candidates(method_node)
            if not candidates:
                continue
            outer_if, else_block, inner_if = candidates[0]
            new_text = flatten_one(source_text, else_block, inner_if)
            if new_text is None:
                continue  # this specific candidate didn't meet the safety checks - try the next method/file, don't retry it
            try:
                javalang.parse.parse(new_text)  # the real safety gate: never accept a splice that doesn't parse
            except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError):
                continue  # discard - keep source_text as it was before this attempt
            source_text = new_text
            applied += 1
            found_one = True
            break  # source_text changed - re-parse from scratch before touching anything else
        if not found_one:
            break

    return source_text, applied
