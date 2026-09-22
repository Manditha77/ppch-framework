"""Parses a Java source file and extracts the most complex method as a flat
Statement list, ready for act/ilp-engine/extract_method.py's solve_extract_method().

APPROXIMATION NOTE: this implements the core SonarSource Cognitive Complexity
rules (Campbell, 2018) as described in Methodology §1.2.1/§2.3.2 - +1 per
interruption of linear flow (if/else/for/while/do/catch/switch-case/ternary/
boolean-operator-sequence), plus a nesting-depth increment for structures
nested inside other structures - using javalang's AST. It is a reproduction of
the published rules, not a call into SonarSource's actual proprietary engine
(which is not exposed as a queryable API), so exact figures may differ slightly
from SonarQube's own computation.

CORRECTNESS HISTORY (read before trusting old results): an earlier version of
this module did not unwrap javalang's BlockStatement wrapper for `{ ... }`
bodies, which silently treated almost everything inside any braced block as a
single opaque, zero-complexity node - a serious undercounting bug caught by a
suspiciously low complexity reading on a hand-authored demo file. It also
incorrectly deepened the nesting level for each link of an "else if" chain,
which Campbell's rules keep at the SAME level as the original `if`. Both are
fixed here (_unwrap_block, and same-level else-if handling in
_flatten_method_body). ANY complexity numbers or extraction suggestions
produced before this fix (including the PR #1719 case study and the 49-PR
survey in the main pipeline) should be treated as unverified until re-run.

Known remaining approximation gaps (not hit by the demo file, not yet fixed):
switch-case bodies and catch-block bodies are not individually flattened into
nested statements (their own header is scored, but their contents are not
descended into) - acceptable for now since neither construct is exercised by
current usage, but worth fixing before relying on results for code that uses
them.

Dependency modelling for the ILP: a statement "depends on" (a) any earlier
statement in the same method whose declared local variable it reads, and
(b) its immediate enclosing control-statement (so a statement cannot be
selected for extraction without the wrapper that contains it) - see
Methodology §3.4.3.

Requires: pip install javalang
"""

import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import javalang

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_method import Statement

# AST node types that interrupt linear control flow -> +1 base increment
FLOW_BREAKING_TYPES = (
    javalang.tree.IfStatement,
    javalang.tree.ForStatement,
    javalang.tree.WhileStatement,
    javalang.tree.DoStatement,
    javalang.tree.CatchClause,
    javalang.tree.SwitchStatementCase,
    javalang.tree.TernaryExpression,
)
# These add nesting depth for statements truly NESTED INSIDE their body -
# NOT for chained "else if" links, which stay at the same level (handled
# specially in _flatten_method_body).
NESTING_INCREMENTING_TYPES = (
    javalang.tree.IfStatement,
    javalang.tree.ForStatement,
    javalang.tree.WhileStatement,
    javalang.tree.DoStatement,
    javalang.tree.CatchClause,
    javalang.tree.SwitchStatement,
)


@dataclass
class _FlatStatement:
    node: object
    nesting_depth: int
    parent_index: int | None
    source_line: int | None = None
    declared_vars: set = field(default_factory=set)
    used_vars: set = field(default_factory=set)
    assigned_vars: set = field(default_factory=set)
    # True for a same-level chained "else if" link (SAVE20/VIP/SEASONAL in
    # `if(SAVE10)...else if(SAVE20)...else if(VIP)...`). Its own source line
    # is `} else if (...) {` - an orphaned closing brace with nothing in
    # THIS statement's own selected text to match it. It can never safely be
    # the ROOT (shallowest line) of an extraction on its own; only its TRUE-
    # NESTED children (whose own lines are complete, independent statements)
    # can be. See method_to_statements / extract_method.py's handling.
    is_chain_link: bool = False
    # True if THIS statement alone (its own then/else structure, recursively
    # - see _definitely_returns) guarantees a `return`/`throw` on every path
    # through it. Used by render_extraction_suggestion to detect an
    # "exhaustive" guard-clause/decision chain (e.g. isAssignable's
    # `if (X) return a; if (Y) return b; ... return false;`) as the safe,
    # tractable sub-case of return-forwarding - as opposed to a `return`
    # mixed with genuine fall-through, which stays the existing unsafe/
    # manual-review case.
    definitely_returns: bool = False


def _unwrap_block(node):
    """Java's `{ ... }` braces parse, via javalang, as a BlockStatement
    wrapping the real statement list in `.statements`. Returns the actual
    list of statements to recurse into - unwrapping BlockStatement, passing
    lists through (flattening any nesting), and wrapping a bare single
    statement (the no-braces `if (x) foo();` case) in a one-element list."""
    if node is None:
        return []
    if isinstance(node, javalang.tree.BlockStatement):
        return list(node.statements or [])
    if isinstance(node, (list, tuple)):
        result = []
        for item in node:
            result.extend(_unwrap_block(item))
        return result
    return [node]


def _count_boolean_operator_sequences(node, parent_operator=None, exclude_attrs=frozenset({"then_statement", "else_statement", "body"})):
    """Campbell's rule for logical operators: each MAXIMAL RUN of the same
    &&/|| operator in an expression counts once; switching operator type
    within the same expression (e.g. `a && b || c`) adds another increment.
    `parent_operator` tells a BinaryOperation node whether it's a
    continuation of its parent's run (same operator - contributes 0 more)
    or the start of a new one (different operator, or no logical parent -
    contributes 1).

    `exclude_attrs` mirrors _walk_own_subtree's exclusion set EXACTLY, and
    for the same reason: _complexity_of_node is called with the WHOLE
    statement node (e.g. an IfStatement, which structurally still contains
    its then/else/body children in the raw AST) - without this exclusion,
    a boolean expression inside a nested branch would be counted HERE
    (via its ancestor if-statement) AND AGAIN by that branch's own
    separately-flattened statement entry.

    CORRECTNESS HISTORY: _complexity_of_node used to have a dead branch
    checking `isinstance(node, BinaryOperation)` - but the node it's called
    with is always a STATEMENT (an if/for/while/... header), never the
    boolean EXPRESSION inside that statement's own condition, so that
    branch could never fire. Confirmed by reproducing on two real PRs (see
    git history): a method with 6 &&/|| operators in its guard conditions
    scored a Campbell estimate 5 points below SonarQube's own real
    measurement."""
    if node is None:
        return 0
    if isinstance(node, (list, tuple, set)):
        return sum(_count_boolean_operator_sequences(item, parent_operator, exclude_attrs) for item in node)
    if not hasattr(node, "attrs"):
        return 0  # primitive value - not a javalang Node

    if isinstance(node, javalang.tree.BinaryOperation) and node.operator in ("&&", "||"):
        increment = 0 if node.operator == parent_operator else 1
        left = _count_boolean_operator_sequences(node.operandl, node.operator, exclude_attrs)
        right = _count_boolean_operator_sequences(node.operandr, node.operator, exclude_attrs)
        return increment + left + right

    total = 0
    for attr_name in node.attrs:
        if attr_name in exclude_attrs:
            continue
        total += _count_boolean_operator_sequences(getattr(node, attr_name, None), None, exclude_attrs)
    return total


def _complexity_of_node(node, nesting_depth: int) -> float:
    """+1 for a flow-breaking node, plus its current nesting depth as a
    nesting penalty (approximating Campbell's B3 rule), plus one increment
    per logical-operator run/change in its OWN condition/expression content
    (Campbell's B2 rule for &&/||) - see _count_boolean_operator_sequences."""
    base = 1.0 + nesting_depth if isinstance(node, FLOW_BREAKING_TYPES) else 0.0
    return base + _count_boolean_operator_sequences(node)


def _walk_own_subtree(node, exclude_attrs=frozenset({"then_statement", "else_statement", "body"})):
    """Yield `node` and every descendant in its subtree, EXCLUDING the
    attributes in `exclude_attrs` (the nested-block attributes that
    _flatten_method_body already expands into their own separate flat
    statements). Without this exclusion, a control statement like an `if`
    would recursively claim variables actually declared/used/assigned deep
    inside its own nested body - which is already correctly attributed to
    that body's own flattened statement entries."""
    if node is None:
        return
    if isinstance(node, (list, tuple, set)):
        for item in node:
            yield from _walk_own_subtree(item, exclude_attrs)
        return
    if not hasattr(node, "attrs"):
        return  # primitive value (str, int, bool) - not a javalang Node
    yield node
    for attr_name in node.attrs:
        if attr_name in exclude_attrs:
            continue
        yield from _walk_own_subtree(getattr(node, attr_name, None), exclude_attrs)


def _contains_break_continue(node) -> bool:
    """True if `node`'s FULL subtree - unlike _walk_own_subtree, this does
    NOT exclude nested then/else/body blocks, it needs to see everything -
    contains a break or continue statement anywhere. Used to decide whether
    a loop's body can be safely split from its own header during
    extraction: a break/continue inside the extracted piece would target a
    loop that no longer physically encloses it once moved to a separate
    method - `continue;` (or `break;`) with no enclosing loop is a compile
    error. Conservative: ANY break/continue anywhere in the subtree blocks
    splitting, even a labelled one that targets some OTHER, outer loop -
    getting that distinction right isn't worth the complexity here, and
    erring conservative (keep the loop header attached) only costs a
    smaller-than-ideal extraction, never an unsafe one."""
    if node is None:
        return False
    if isinstance(node, (list, tuple, set)):
        return any(_contains_break_continue(item) for item in node)
    if isinstance(node, (javalang.tree.BreakStatement, javalang.tree.ContinueStatement)):
        return True
    if not hasattr(node, "attrs"):
        return False
    return any(_contains_break_continue(getattr(node, attr, None)) for attr in node.attrs)


def _contains_return(node) -> bool:
    """True if `node`'s FULL subtree contains a `return` statement anywhere -
    same shape as _contains_break_continue, used to keep the ILP's multi-root
    sibling-combination rule (see extract_method.py's Statement.contains_
    return) away from the return-forwarding safety interaction entirely."""
    if node is None:
        return False
    if isinstance(node, (list, tuple, set)):
        return any(_contains_return(item) for item in node)
    if isinstance(node, javalang.tree.ReturnStatement):
        return True
    if not hasattr(node, "attrs"):
        return False
    return any(_contains_return(getattr(node, attr, None)) for attr in node.attrs)


def _definitely_returns(node) -> bool:
    """True if `node` GUARANTEES control never falls through past it - every
    path reachable through `node` itself (and its own nested then/else
    structure, recursively) ends in a `return` (or `throw`). This is the
    SAME "can complete normally" reachability rule javac itself uses for its
    "missing return statement" compile check: an `if` with no `else` can
    always fall through (condition false -> nothing happens), so it never
    counts; an `if/else` (including an "else if" chain, via the recursive
    IfStatement case below) only counts if BOTH sides do.

    Deliberately conservative for constructs not handled here (loops,
    switch, try/catch all fall through the final `return False`) - a false
    negative here just means a genuinely safe exhaustive-return block gets
    (still correctly, just more cautiously) treated as the existing unsafe/
    manual-review case, never the other way around. See
    render_extraction_suggestion's return-forwarding handling, which is the
    only caller of this and _block_definitely_returns."""
    if isinstance(node, (javalang.tree.ReturnStatement, javalang.tree.ThrowStatement)):
        return True
    if isinstance(node, javalang.tree.IfStatement):
        if node.else_statement is None:
            return False
        return (
            _block_definitely_returns(_unwrap_block(node.then_statement))
            and _block_definitely_returns(_unwrap_block(node.else_statement))
        )
    if isinstance(node, javalang.tree.BlockStatement):
        return _block_definitely_returns(list(node.statements or []))
    return False


def _block_definitely_returns(statements: list) -> bool:
    """A sequence of statements definitely returns iff its LAST statement
    does - matching Java's own reachability rule (if an earlier statement in
    the sequence unconditionally returned, nothing legally compiles after it
    in the same block anyway, so for real, already-compiling source, only
    the last statement needs checking)."""
    if not statements:
        return False
    return _definitely_returns(statements[-1])


def _collect_declared_vars(node) -> set:
    names = set()
    for descendant in _walk_own_subtree(node):
        if isinstance(descendant, javalang.tree.VariableDeclarator):
            names.add(descendant.name)
    return names


def _collect_used_vars(node) -> set:
    """Local variables READ within this statement's own content. A plain
    reference (`discount`) parses as a MemberReference with `member` set
    and an empty `qualifier` - the local var is `member`. A QUALIFIED
    reference parses as ONE MemberReference either way, so `qualifier` has
    to be inspected to tell them apart: `CustomerTier.GOLD` (a static/enum
    constant access - qualifier='CustomerTier', capitalized per Java type-
    naming convention) has NO local variable in it at all, while
    `order.total` (instance field access via a local reference - qualifier
    ='order', lowercase) means the local variable being read is the
    QUALIFIER (`order`), not the field name (`total`). Confirmed via
    javalang.parse against both forms before writing this - see git history
    for the reproduction. Getting this wrong previously caused enum
    constants like CustomerTier.GOLD to be misread as free local variables
    needing to become extracted-method parameters.

    MethodInvocation (`customer.getTier()`) needs the SAME qualifier
    handling, separately, since javalang gives it its own node type instead
    of reusing MemberReference: an empty qualifier means a same-class call
    (`baseDiscountForTier(...)`, no local variable involved at all), a
    lowercase qualifier means the local variable `customer` is being read
    (to call a method ON it), and an uppercase qualifier means a static
    call (`Math.max(...)`, again no local variable). Missing this case
    previously meant a statement whose ONLY reference to a variable was via
    a method call on it (e.g. `customer.getTier() == CustomerTier.GOLD`,
    with no bare `customer` reference anywhere else) silently dropped
    `customer` from used_vars - so it was never inferred as a needed
    parameter, and the extracted method referenced an undeclared variable."""
    names = set()
    for descendant in _walk_own_subtree(node):
        if isinstance(descendant, javalang.tree.MemberReference):
            qualifier = descendant.qualifier or ""
            if not qualifier:
                names.add(descendant.member)
            elif not qualifier[0].isupper():
                names.add(qualifier)
        elif isinstance(descendant, javalang.tree.MethodInvocation):
            qualifier = descendant.qualifier or ""
            if qualifier and not qualifier[0].isupper():
                names.add(qualifier)
    return names


def _collect_assigned_vars(node) -> set:
    """Variables that are the TARGET of an assignment (`x = ...`, `x += ...`)
    within this statement's own content. Distinct from _collect_used_vars
    (which also counts reads) - needed to detect variables a block MODIFIES,
    for return-value inference in render_extraction_suggestion. Same
    qualifier handling as _collect_used_vars: `this.x = ...` / `obj.x = ...`
    assigns a FIELD, not a local variable named `x` - not tracked here at
    all (assigning through an object reference doesn't change what needs to
    flow back out via a return value the way reassigning a local does)."""
    names = set()
    for descendant in _walk_own_subtree(node):
        if isinstance(descendant, javalang.tree.Assignment):
            target = getattr(descendant, "expressionl", None)
            if isinstance(target, javalang.tree.MemberReference) and not target.qualifier:
                names.add(target.member)
    return names


def _type_to_string(type_node) -> str:
    """Best-effort Java type name from a javalang Type node. Falls back to
    'Object' rather than guessing wrong for constructs not handled here
    (e.g. complex generics) - an honest placeholder, not a wrong answer."""
    if type_node is None:
        return "Object"
    name = getattr(type_node, "name", None)
    if not name:
        return "Object"
    dimensions = getattr(type_node, "dimensions", None) or []
    return name + ("[]" * len(dimensions))


def _flatten_method_body(statements, nesting_depth=0, parent_index=None, flat=None, is_chain_link=False):
    if flat is None:
        flat = []
    for stmt in statements or []:
        my_index = len(flat)
        position = getattr(stmt, "position", None)
        flat.append(_FlatStatement(
            node=stmt,
            nesting_depth=nesting_depth,
            parent_index=parent_index,
            source_line=position.line if position else None,
            declared_vars=_collect_declared_vars(stmt),
            used_vars=_collect_used_vars(stmt),
            assigned_vars=_collect_assigned_vars(stmt),
            is_chain_link=is_chain_link,
            definitely_returns=_definitely_returns(stmt),
        ))
        child_nesting = nesting_depth + 1 if isinstance(stmt, NESTING_INCREMENTING_TYPES) else nesting_depth

        then_child = getattr(stmt, "then_statement", None)
        if then_child is not None:
            _flatten_method_body(
                _unwrap_block(then_child), nesting_depth=child_nesting, parent_index=my_index, flat=flat
            )

        else_child = getattr(stmt, "else_statement", None)
        if else_child is not None:
            if isinstance(else_child, javalang.tree.IfStatement):
                # "else if": a CONTINUATION of the same decision chain, not a
                # new nested level - Campbell's rules keep chained else-if
                # conditions at the SAME nesting depth as the original `if`.
                #
                # parent_index=None (not my_index) is deliberate: a chain
                # link is a sibling ALTERNATIVE to the previous link, not
                # something nested inside it. Recording the previous link as
                # its extraction dependency was a real bug - it forced
                # selecting an entire preceding else-if chain just to
                # extract one deep branch (e.g. wanting the "VIP" branch's
                # nested tier logic required also selecting "SAVE10"/"SAVE20"),
                # which is exactly why an earlier version of this tool ended
                # up recommending "extract nearly the whole method" instead
                # of a small, targeted extraction. See extract_method.py's
                # downward-closure constraint for how a chain link's TRUE
                # nested body is still kept together with it.
                #
                # is_chain_link=True: this specific statement's own source
                # line is `} else if (...) {` - a lone closing brace with no
                # opener of its own in a text slice that starts here. It
                # must never be the ROOT of an extraction (see
                # method_to_statements / extract_method.py's exclusion of
                # chain-link statements from selection); only its own
                # TRUE-nested children, flattened below with the default
                # is_chain_link=False, are safe roots.
                _flatten_method_body(
                    [else_child], nesting_depth=nesting_depth, parent_index=None, flat=flat,
                    is_chain_link=True,
                )
            else:
                # a genuine `else { ... }` block - its CONTENTS are nested one
                # level deeper (the else-block header itself has no separate
                # complexity in Campbell's rules beyond the if's own +1).
                _flatten_method_body(
                    _unwrap_block(else_child), nesting_depth=child_nesting, parent_index=my_index, flat=flat
                )

        body_child = getattr(stmt, "body", None)
        if body_child is not None:
            _flatten_method_body(
                _unwrap_block(body_child), nesting_depth=child_nesting, parent_index=my_index, flat=flat
            )
    return flat


def _collect_type_map(method_node, flat: list) -> dict:
    """Best-effort {variable_name: java_type_string} map, built from the
    method's own formal parameters and local variable declarations. Used to
    replace guesswork placeholders with real, usually-correct Java types in
    the rendered suggestion.

    Checks VariableDeclaration, not the narrower LocalVariableDeclaration:
    a for-loop's own induction variable (`for (int i = 0; ...)`) parses as
    a plain VariableDeclaration, not LocalVariableDeclaration (javalang
    uses the latter only for declarations that are themselves a full
    statement) - LocalVariableDeclaration IS a VariableDeclaration
    subclass, so checking the broader type still catches ordinary local
    declarations too. Missing the loop-induction case previously left loop
    variables (`i`) typed as the 'Object' fallback, which fails to compile
    the moment the extracted snippet does array indexing (`regions[i]`) -
    surfaced once loop bodies became independently extractable (see
    method_to_statements's break/continue-free-loop handling)."""
    type_map = {}
    for param in getattr(method_node, "parameters", []) or []:
        type_map[param.name] = _type_to_string(param.type)
    for fs in flat:
        for descendant in _walk_own_subtree(fs.node):
            if isinstance(descendant, javalang.tree.VariableDeclaration):
                type_str = _type_to_string(descendant.type)
                for declarator in descendant.declarators:
                    type_map[declarator.name] = type_str
    return type_map


def method_to_statements(method_node):
    """Flatten one javalang MethodDeclaration body into ILP-ready Statements.

    Returns (statements, meta, type_map):
    - statements: list[Statement], consumed by the ILP solver
    - meta: {index: {"source_line", "used_vars", "declared_vars",
      "assigned_vars"}} - extra information needed afterwards to render an
      actual code suggestion and infer return-value/parameter handling
    - type_map: {variable_name: java_type_string}, from method_to_statements'
      own parameters and local declarations
    """
    flat = _flatten_method_body(method_node.body or [])

    # Downward closure: for each statement, every statement TRUE-nested
    # inside it (transitively, via the now-corrected parent_index - same-
    # level else-if chain links no longer count). Used by extract_method.py
    # to force "select a node => select its whole nested body too", so the
    # ILP can never choose a "gappy" subset that the line-range/brace-
    # balancing text splice would silently sweep extra, unaccounted-for
    # code into anyway (see render_extraction_suggestion / apply_extraction).
    descendants_of = {i: set() for i in range(len(flat))}
    for i, fs in enumerate(flat):
        ancestor = fs.parent_index
        while ancestor is not None:
            descendants_of[ancestor].add(i)
            ancestor = flat[ancestor].parent_index

    statements = []
    meta = {}
    for i, fs in enumerate(flat):
        # NOTE: depends_on intentionally does NOT include "the statement
        # that declares a variable this one reads" (it used to - see git
        # history). A statement reading an outside variable never NEEDS
        # that variable's declaration selected too: it can always just
        # become an inbound parameter instead (see inferred_parameters in
        # render_extraction_suggestion). Forcing the declaration in was
        # actively harmful: it dragged cheap, shallow (often top-level,
        # nesting_depth=0) declarations into extractions that otherwise
        # targeted a deep, expensive nested block, widening the swept text
        # span back down to a shallow starting point - which erases the
        # nesting-depth reduction that's the entire point of extracting a
        # deep block in the first place (see extract_method.py's
        # depth-0 penalty for the other half of this fix).
        #
        # One more exclusion: if this statement's TRUE parent is itself a
        # chain-link (e.g. GOLD-if's recorded parent is VIP-if, an "else
        # if" link), don't record that as a depends_on edge either. A
        # chain-link statement can never be selected at all (see
        # is_chain_link handling below and in extract_method.py), so a
        # dependency on it would just make its children unselectable too -
        # defeating the entire point of letting a deeply nested, safely-
        # rooted child (GOLD-if's own line is a normal `if`, not `} else
        # if`) be extracted without its unsafe-to-move chain-link parent.
        #
        # Third exclusion: a loop (for/while/do) whose body contains no
        # break/continue anywhere. Its children can then ALSO be extracted
        # independently of the loop header - e.g. just the nested if-chain
        # driving a loop body's complexity, leaving `for (...) { call(); }`
        # behind - exactly like the chain-link case above, and for the same
        # reason (their own line is a normal, complete statement start).
        # UNLIKE a chain-link, the loop itself remains independently
        # selectable too (moving a whole break/continue-free loop is valid
        # Java, just doesn't reduce nesting) - so this only relaxes the
        # UPWARD requirement on its children, it doesn't also exclude the
        # loop from selection the way is_chain_link does. Caught via a
        # second test file whose entire complexity lived inside one loop:
        # without this, the whole loop had to move as a single unit
        # (headers included), preserving 100% of its internal nesting and
        # therefore its complexity - the same "wholesale extraction changes
        # nothing" failure mode chain-link decoupling fixed for if-chains.
        depends_on = set()
        if fs.parent_index is not None:
            parent = flat[fs.parent_index]
            parent_lets_children_go_solo = parent.is_chain_link or (
                isinstance(parent.node, (
                    javalang.tree.ForStatement, javalang.tree.WhileStatement, javalang.tree.DoStatement,
                ))
                and not _contains_break_continue(parent.node)
            )
            if not parent_lets_children_go_solo:
                depends_on.add(fs.parent_index)
        complexity = _complexity_of_node(fs.node, fs.nesting_depth)
        statements.append(Statement(
            index=i,
            complexity=complexity,
            local_variables=frozenset(fs.declared_vars),
            depends_on=frozenset(depends_on),
            descendants=frozenset(descendants_of[i]),
            nesting_depth=fs.nesting_depth,
            is_chain_link=fs.is_chain_link,
            true_parent_index=fs.parent_index,
            contains_return=_contains_return(fs.node),
        ))
        meta[i] = {
            "source_line": fs.source_line,
            "used_vars": fs.used_vars,
            "declared_vars": fs.declared_vars,
            "assigned_vars": fs.assigned_vars,
            "nesting_depth": fs.nesting_depth,
            "definitely_returns": fs.definitely_returns,
        }

    type_map = _collect_type_map(method_node, flat)
    # "$return" is not a valid Java identifier, so it can never collide with
    # a real parameter/local-variable entry in this same dict - reserved key
    # for the enclosing method's OWN declared return type, needed by
    # render_extraction_suggestion's return-forwarding case (an extracted
    # exhaustive-return sub-block must return the SAME type the statements
    # already return today, since that code already compiles against it).
    type_map["$return"] = (
        "void" if method_node.return_type is None else _type_to_string(method_node.return_type)
    )
    return statements, meta, type_map


def _extend_to_balanced_braces(source_lines: list, start_line: int, end_line: int) -> tuple:
    """Extend `end_line` forward (1-indexed, inclusive) until every `{`
    opened within [start_line, end_line] is matched by a `}` within the same
    range. Fixes the case where the LAST selected statement itself spans
    multiple lines - the naive slice based only on each statement's STARTING
    line would otherwise cut it off mid-block, producing broken Java.

    Tracks whether an opening brace has been seen at all, not just the net
    depth: a wrapped method signature or condition (`public double foo(int a,\n
    int b) {` - the `{` only appears on the SECOND line) starts with net
    depth 0 for a while, which a plain "depth == 0 means balanced" check
    would wrongly treat as already-complete after just the first line,
    truncating the extraction (or, in apply_extraction's use of this same
    helper to find a method's closing brace, truncating the METHOD) mid-
    signature. Caught via a real multi-line signature in a second test file
    - PricingEngine's signature happens to fit on one line, so this never
    surfaced until a structurally different file was tried.

    Best-effort: a plain per-line count of '{' and '}', which can be thrown
    off by braces inside string literals or comments. Returns
    (extended_end_line, is_balanced) - is_balanced is only True once at
    least one '{' was seen AND the running depth has returned to 0."""
    depth = 0
    seen_open = False
    for lineno in range(start_line, min(end_line, len(source_lines)) + 1):
        line = source_lines[lineno - 1]
        opens = line.count("{")
        depth += opens - line.count("}")
        seen_open = seen_open or opens > 0

    # depth==0 with no brace seen at all is ambiguous between two real
    # cases: (a) a genuinely brace-free sequence of plain statements -
    # already complete, must NOT keep extending (there's no brace to ever
    # balance against, so "keep extending until a brace appears" runs away
    # and sweeps in unrelated later code - confirmed by a real crash: two
    # loop-body statements selected without their loop header, containing
    # no braces of their own, swept everything up to the next stray '}' in
    # the file and corrupted the output), or (b) a genuinely wrapped multi-
    # line signature/condition whose `{` hasn't appeared yet (the case this
    # function was originally built for). Distinguished by whether the last
    # considered line looks terminated (ends with `;` or `}`, ignoring a
    # trailing line comment) - a real statement always does; a wrapped
    # signature/header never does (it ends mid-parameter-list or mid-
    # condition, e.g. with `,` or `(`).
    last_line = source_lines[min(end_line, len(source_lines)) - 1].split("//")[0].rstrip()
    looks_complete = last_line.endswith((";", "}"))

    extended_end = end_line
    max_line = len(source_lines)
    while (depth > 0 or (not seen_open and not looks_complete)) and extended_end < max_line:
        extended_end += 1
        line = source_lines[extended_end - 1]
        opens = line.count("{")
        depth += opens - line.count("}")
        seen_open = seen_open or opens > 0

    return extended_end, depth == 0 and (seen_open or looks_complete)


def render_extraction_suggestion(
    source_text: str,
    method_name: str,
    statements: list,
    meta: dict,
    selected_indices: list,
    type_map: dict = None,
) -> dict:
    """Turn the ILP solver's abstract selected_statement_indices into an
    actual, readable, ready-to-copy suggested extraction.

    Improvements over the first version:
    - REAL parameter types, from the method's own parameter list and local
      variable declarations (type_map), not '/* type? */' placeholders.
    - Return-value inference: detects variables the extracted block MODIFIES
      that are also used elsewhere in the method (outside the block) -
      if there is exactly one such variable, the suggestion returns it and
      shows the correct call-site assignment; zero such variables -> a void
      method; MORE than one -> flagged as needing manual review rather than
      guessed at.
    - `full_snippet`: one ready-to-copy string containing the complete new
      method (signature + body + closing brace).
    - `call_site_replacement`: the exact line(s) to replace the extracted
      block with in the original method.
    - Return-forwarding (the "easy", tractable sub-case only): a block
      containing `return` statements is normally refused outright (see
      `contains_return_statement` below) - but if the block is EXHAUSTIVE
      (every path through it guarantees a `return`, e.g. a single
      `if/else-if/.../else` chain with a terminal `else` covering every
      remaining case - see _definitely_returns) AND has no outbound side
      effects on pre-existing variables, it's safe to forward: the extracted
      method reuses the enclosing method's own return type, and the call
      site becomes `return extracted(...);`. Verified (2026-09) to have zero
      real-world impact on the 85-PR Apache Commons Lang survey - this
      codebase's own guard-clause style tends to use SEPARATE sibling `if`
      statements with a trailing fallback `return`, not a single chained
      `if/else-if/.../else`, and the ILP's one-independent-root constraint
      (a deliberate fix for an earlier "gappy extraction" bug - see
      extract_method.py) means those siblings can never be bundled into one
      extraction. Kept anyway: correct and safe for the idiom it does cover,
      and the ILP constraint it depends on is intentionally NOT being
      relaxed to chase this case further.

    Still advisory: this does not verify the result compiles, multi-
    outbound-variable cases are intentionally left for manual handling, and
    a `return` mixed with genuine fall-through (not exhaustive) is still
    refused rather than guessed at.
    """
    if not selected_indices:
        return {"rendered": False, "reason": "no_statements_selected"}

    type_map = type_map or {}
    source_lines = source_text.splitlines()
    line_numbers = [
        meta[i]["source_line"] for i in selected_indices
        if meta.get(i, {}).get("source_line")
    ]
    if not line_numbers:
        return {"rendered": False, "reason": "no_source_line_info_available"}

    start_line, end_line = min(line_numbers), max(line_numbers)
    balanced_end_line, is_balanced = _extend_to_balanced_braces(source_lines, start_line, end_line)
    extracted_source = "\n".join(source_lines[start_line - 1:balanced_end_line])

    # A `return` statement inside the extracted block is NOT modeled at
    # all by the variable-based return-value inference below: it returns a
    # value from the ORIGINAL method, not a value this function's own
    # return-value analysis tracks. Naively moving it would either produce
    # a `return` inside a `void` extracted method (compile error) or a
    # `return` of the wrong type, AND the original method would silently
    # stop returning on that path - a real control-flow change, not a
    # value-passing one. Properly supporting this needs the extracted
    # method to forward a "did this path return, and what" signal back to
    # the caller, which this text-splice tool does not implement - so any
    # such extraction is flagged unsafe rather than guessed at. Detected by
    # text search (not AST) since this function only has statement-level
    # metadata here, not raw nodes for the full selected range - a
    # deliberately conservative approximation: false positives (an
    # unrelated "return" appearing in a string/comment) just mean an extra,
    # unnecessary manual-review flag, never a missed unsafe case.
    contains_return_statement = re.search(r"\breturn\b", extracted_source) is not None

    # Variable accounting must be based on what actually ENDS UP in
    # `extracted_source`, not just on `selected_indices`. Brace-balancing
    # above extends the line range by raw text, with no awareness of which
    # statements the ILP selected - a statement lexically BETWEEN two
    # selected ones (e.g. a chain link's own header/condition, still
    # required to make the else-if chain syntactically complete) gets swept
    # into the physical text either way. Computing declared/used/assigned
    # only from selected_indices previously missed exactly this: a variable
    # referenced only in a swept-but-not-"selected" statement (like
    # `couponCode` in the chain's own `if (couponCode != null …)` header)
    # would be used in the real extracted code without ever being detected
    # as needing to become a parameter - a guaranteed compile error.
    swept_indices = {
        i for i, m in meta.items()
        if m.get("source_line") is not None and start_line <= m["source_line"] <= balanced_end_line
    }

    declared_within, used_within, assigned_within = set(), set(), set()
    for i in swept_indices:
        m = meta.get(i, {})
        declared_within |= m.get("declared_vars", set())
        used_within |= m.get("used_vars", set())
        assigned_within |= m.get("assigned_vars", set())

    inferred_parameters = sorted(used_within - declared_within)

    # Return-value inference: any variable whose CURRENT VALUE could be
    # needed after the extracted block ends. Two distinct cases, both
    # covered here:
    #  (a) a PRE-EXISTING variable (declared outside the block) that gets
    #      reassigned inside it (assigned_within - declared_within) - the
    #      caller's copy is now stale unless the new value comes back.
    #  (b) a variable BOTH declared AND assigned inside the block
    #      (declared_within) whose value is read somewhere else in the
    #      method, outside the selected range (e.g. `double finalPrice = …;`
    #      inside the block, `return finalPrice;` after it) - the earlier
    #      version of this function only checked (a), so case (b) variables
    #      silently vanished: the method was inferred as void, and the
    #      original method was left with a dangling reference to a variable
    #      whose declaration had just been extracted out from under it.
    outbound_candidates = (assigned_within - declared_within) | declared_within
    outbound_vars = []
    for name in sorted(outbound_candidates):
        used_elsewhere = any(
            (name in meta[i].get("used_vars", set()) or name in meta[i].get("assigned_vars", set()))
            for i in meta if i not in swept_indices
        )
        if used_elsewhere:
            outbound_vars.append(name)

    # Exhaustive-return check: the "easy", tractable sub-case of return-
    # forwarding. Only applies when the extracted block is a pure guard-
    # clause/decision-tree pattern - EVERY path through it guarantees a
    # `return` (no fall-through) AND it has no outbound side effects on
    # pre-existing variables - exactly what isAssignable-style methods look
    # like (`if (X) return a; if (Y) return b; ... return false;`). The hard
    # case (a `return` mixed with genuine fall-through, or combined with
    # outbound variables) deliberately falls through unchanged to the
    # existing unsafe/manual-review handling below - this does NOT attempt
    # to make that case safe.
    #
    # "Top level of the extraction" = the swept statements at the SHALLOWEST
    # nesting depth present (the independent root plus any same-level
    # siblings swept in alongside it) - anything deeper is nested inside one
    # of these and its own return-behavior is already folded in recursively
    # by _definitely_returns's own then/else handling. Whether the sequence
    # as a whole falls through is then just: does its LAST statement (in
    # source order) definitely return - see _block_definitely_returns.
    is_exhaustive_return = False
    if contains_return_statement and swept_indices:
        min_depth = min(meta[i]["nesting_depth"] for i in swept_indices)
        top_level_indices = sorted(
            (i for i in swept_indices if meta[i]["nesting_depth"] == min_depth),
            key=lambda i: meta[i]["source_line"],
        )
        is_exhaustive_return = bool(top_level_indices) and meta[top_level_indices[-1]]["definitely_returns"]

    return_forwarding = contains_return_statement and is_exhaustive_return and not outbound_vars

    suggested_name = f"{method_name}Extracted"
    param_list = ", ".join(f"{type_map.get(name, 'Object')} {name}" for name in inferred_parameters)

    return_analysis = {
        "outbound_variables": outbound_vars,
        "status": (
            "return_forwarding" if return_forwarding
            else "void" if not outbound_vars
            else "single_return" if len(outbound_vars) == 1
            else "multiple_outbound_manual_review_required"
        ),
    }

    caveat_parts = []
    if return_forwarding:
        caveat_parts.append(
            "This extracted block guarantees a `return` on every path (an exhaustive "
            "guard-clause/decision chain, no fall-through) - the extracted method "
            "mirrors the original method's own return type, and the call site "
            "forwards the result directly (`return " + suggested_name + "(...);`)."
        )
    elif contains_return_statement:
        caveat_parts.append(
            "WARNING: the extracted block contains a `return` statement. This tool "
            "does not model return-forwarding, so the snippet below may return from "
            "the wrong method or with the wrong type. NOT safe to auto-apply - "
            "restructure manually (e.g. have the extracted method return a status "
            "the caller checks, or don't extract across this return)."
        )
    if not is_balanced:
        caveat_parts.append(
            "WARNING: brace balancing could not complete before end of file — "
            "this snippet may still be truncated; verify manually."
        )
    elif balanced_end_line != end_line:
        caveat_parts.append(
            f"(Extended from the naive line {end_line} to {balanced_end_line} to "
            "avoid cutting off a multi-line statement mid-block.)"
        )
    caveat_parts.append(
        "Parameter and return types are inferred from the ORIGINAL method's own "
        "parameters and local variable declarations — usually correct, but not "
        "verified to compile. Review before applying."
    )

    BODY_INDENT = "        "  # standard 8-space method-body indentation
    if return_analysis["status"] == "return_forwarding":
        # The extracted body already ends in a `return` on every path (that
        # is the whole definition of "exhaustive") - no extra return_stmt to
        # append, and the return TYPE is simply the enclosing method's own
        # declared return type: the moved `return X;` statements already
        # compile against it today, so reusing it is guaranteed compatible,
        # not a fresh inference.
        return_type = type_map.get("$return", "Object")
        return_stmt = ""
        call_site = f"return {suggested_name}({', '.join(inferred_parameters)});"
    elif return_analysis["status"] == "void":
        return_type = "void"
        return_stmt = ""
        call_site = f"{suggested_name}({', '.join(inferred_parameters)});"
    elif return_analysis["status"] == "single_return":
        var_name = outbound_vars[0]
        return_type = type_map.get(var_name, "Object")
        return_stmt = f"\n{BODY_INDENT}return {var_name};"
        call = f"{suggested_name}({', '.join(inferred_parameters)})"
        if var_name in declared_within:
            # The variable's own declaration was moved INTO the extracted
            # method (case (b) above) - there's no longer a declaration of
            # it left in the original method, so the call site must
            # (re-)declare it, not just assign to an already-declared name.
            call_site = f"{return_type} {var_name} = {call};"
        else:
            call_site = f"{var_name} = {call};"
    else:
        return_type = "/* MULTIPLE outbound variables — manual review required, see outbound_variables */"
        return_stmt = ""
        call_site = (
            f"/* MANUAL REVIEW NEEDED: {suggested_name}({', '.join(inferred_parameters)}) "
            f"modifies {outbound_vars}, which are used elsewhere in the method */"
        )
        caveat_parts.append(
            f"Multiple variables ({outbound_vars}) are modified inside the extracted block "
            "AND used elsewhere in the method — a single return value can't carry all of "
            "them back. This suggestion is NOT safe to auto-apply; restructure manually "
            "(e.g. return a small result object, or keep this logic un-extracted)."
        )

    # Normalize indentation: the extracted lines carry whatever depth they had
    # inside the ORIGINAL method (which could be deeply nested); dedent to a
    # common baseline, then reindent to a single, consistent method-body
    # level. Without this, a block extracted from deep nesting renders with
    # confusing, inconsistent indentation once placed in a new, shallower
    # method - correct Java either way, but hard to read and easy to
    # mistrust at a glance.
    dedented = textwrap.dedent(extracted_source)
    reindented_body = "\n".join(
        f"{BODY_INDENT}{line}" if line.strip() else "" for line in dedented.splitlines()
    )

    suggested_signature = f"private {return_type} {suggested_name}({param_list})"
    full_snippet = f"{suggested_signature} {{\n{reindented_body}{return_stmt}\n}}"

    return {
        "rendered": True,
        "source_line_range": [start_line, balanced_end_line],
        "brace_balanced": is_balanced,
        "inferred_parameters": inferred_parameters,
        "parameter_types": {name: type_map.get(name, "Object") for name in inferred_parameters},
        "return_analysis": return_analysis,
        "suggested_method_name": suggested_name,
        "suggested_signature": suggested_signature,
        "extracted_source": extracted_source,
        "full_snippet": full_snippet,
        "call_site_replacement": call_site,
        "safe_to_auto_apply": (
            return_analysis["status"] != "multiple_outbound_manual_review_required"
            and (not contains_return_statement or return_analysis["status"] == "return_forwarding")
        ),
        "caveat": " ".join(caveat_parts),
    }


def most_complex_method(source_text: str, changed_lines: set = None):
    """Parse a Java source file and return a target method, as:

        (method_name, statements, total_complexity, meta, method_start_line,
         was_touched_by_pr, type_map)

    Selection priority (diff-scoping):
      1. If `changed_lines` is given (the set of line numbers this PR actually
         added/modified in this file - see diff_utils.changed_line_numbers),
         prefer methods that OVERLAP those lines, ranked by complexity among
         those.
      2. Otherwise (or if no method overlaps), FALL BACK to the single most
         complex method in the whole file - but `was_touched_by_pr` is False
         in that case, so callers can flag that the suggestion may not be
         about code this PR actually changed.

    Returns None if the file has no parseable methods.
    """
    tree = javalang.parse.parse(source_text)

    touched_best = None
    overall_best = None
    for _, method_node in tree.filter(javalang.tree.MethodDeclaration):
        statements, meta, type_map = method_to_statements(method_node)
        total = sum(s.complexity for s in statements)
        position = getattr(method_node, "position", None)
        start_line = position.line if position else None
        entry = (method_node.name, statements, total, meta, start_line, type_map)

        if overall_best is None or total > overall_best[2]:
            overall_best = entry

        if changed_lines:
            overlaps = any(
                m.get("source_line") in changed_lines for m in meta.values()
            )
            if overlaps and (touched_best is None or total > touched_best[2]):
                touched_best = entry

    chosen = touched_best if touched_best is not None else overall_best
    if chosen is None:
        return None
    name, statements, total, meta, start_line, type_map = chosen
    return name, statements, total, meta, start_line, (touched_best is not None), type_map


def all_methods_by_complexity(source_text: str) -> list:
    """Parse a Java source file and return EVERY method it defines, as a
    list of (method_name, statements, total_complexity, meta,
    method_start_line, type_map) tuples, sorted by total_complexity
    descending.

    Unlike most_complex_method (which is diff/PR-scoped - it picks ONE
    target method, preferring whichever the PR actually touched), this is
    for the PR-independent case: given an arbitrary Java file with no PR
    context at all, find every method that might need attention, not just
    the single worst one. See act/refactor_file.py, which repeatedly takes
    the current worst offender from this list, tries to shrink it, and
    reparses - since extracting from one method changes line numbers for
    the rest of the file, this function is called fresh each iteration
    rather than computing the full list once up front.

    Returns [] if the file has no parseable methods.
    """
    tree = javalang.parse.parse(source_text)
    entries = []
    for _, method_node in tree.filter(javalang.tree.MethodDeclaration):
        statements, meta, type_map = method_to_statements(method_node)
        total = sum(s.complexity for s in statements)
        position = getattr(method_node, "position", None)
        start_line = position.line if position else None
        entries.append((method_node.name, statements, total, meta, start_line, type_map))
    entries.sort(key=lambda entry: entry[2], reverse=True)
    return entries


def max_complexity_across_sources(sources: list) -> float:
    """Given raw Java source texts (typically every file a PR touched, at
    HEAD/post-PR state), returns the highest single-method Campbell-rule
    complexity found across ALL of them.

    Exists to close a real gap found via a live self-hosted-runner test
    (2026-09-22): the Analyze layer's only complexity-related feature,
    complexity_before, is computed by scanning a file's PRE-PR state - for a
    brand-new file that didn't exist before the PR, this is always 0
    (see 02_scan_pilot_batch.py::get_scoped_complexity's own "404 -> 0"
    handling), regardless of how complex the new file's own code actually
    is. A genuinely complex brand-new file was therefore invisible to the
    model. This function measures the code actually being INTRODUCED,
    independent of whether any prior baseline exists - see
    sense/scripts/06_compute_touched_code_complexity.py for the historical
    backfill and act/github-action/live_predict.py for the live equivalent.

    Unparseable files are skipped, not fatal (a PR's diff can include
    non-Java-parseable edge cases - e.g. a file mid-rename). Returns 0.0 if
    nothing parseable is found."""
    best = 0.0
    for source in sources:
        try:
            methods = all_methods_by_complexity(source)
        except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError):
            continue
        if methods:
            best = max(best, methods[0][2])
    return best