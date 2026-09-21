"""ILP support for selecting a contiguous Extract Method candidate.

The caller must provide method-level statement metadata. PR-level aggregate
complexity values are intentionally insufficient for semantic refactoring.
"""

from collections import defaultdict
from dataclasses import dataclass

import pulp


@dataclass(frozen=True)
class Statement:
    index: int
    complexity: float
    local_variables: frozenset[str] = frozenset()
    depends_on: frozenset[int] = frozenset()
    # Statements TRUE-nested inside this one (transitively). Selecting this
    # statement forces all of these to be selected too - see _solve's
    # downward-closure constraint.
    descendants: frozenset[int] = frozenset()
    # Nesting depth in the ORIGINAL method (0 = top-level). See _solve's
    # depth-0 penalty: extracting a chunk whose shallowest statement is
    # already at depth 0 can never reduce nesting-based complexity, since
    # that statement's depth in a brand new method is ALSO 0 - no change.
    # Real reduction only comes from extracting something that WAS nested
    # (depth > 0), whose depth resets to ~0 in its new, standalone method.
    nesting_depth: int = 0
    # True for a chained "else if" link (see java_statement_extractor's
    # is_chain_link). Its own source line is `} else if (...) {` - it can
    # never be the shallowest/root statement of a safe, brace-balanced
    # extraction on its own, so _solve excludes it from selection entirely;
    # only its true-nested children (independently safe roots) are
    # selectable.
    is_chain_link: bool = False
    # The TRUE structural parent's index (the chain-link's own index for an
    # exempted chain-link child, the loop's own index for an exempted
    # break/continue-free-loop child, None for genuine top-level statements)
    # - NOT the same as depends_on, which is intentionally empty for exempted
    # children even though they DO have a real parent. Statements sharing the
    # SAME true_parent_index are genuine, physically-adjacent siblings from
    # the SAME statement list - the only safe basis for grouping multiple
    # independent roots together for combined selection (see _solve's
    # contiguous-run constraint). nesting_depth is NOT safe for this: two
    # independent roots can share a numeric depth by pure coincidence while
    # coming from entirely different parents.
    true_parent_index: int | None = None
    # True if this statement's OWN swept text (itself plus everything
    # brace-balancing would sweep in with it) contains a `return` anywhere.
    # Used to keep multi-root combination away from the return-forwarding
    # safety interaction entirely: combining siblings where any one of them
    # contains a return proved harmful in testing (see _solve's contiguous-
    # run constraint) - not because it's always unsafe, but because it can
    # make the solver's FIRST/cheapest choice a return-containing combo
    # instead of the smaller, safe, genuinely-reducing single-root
    # extractions the solver would otherwise find. Conservative by design:
    # a false positive here just means one fewer combination considered,
    # never an unsafe one accepted.
    contains_return: bool = False


def _solve(statements, max_local_variables, complexity_threshold):
    """Shared solver core. `complexity_threshold` is None for the legacy
    "minimize remaining complexity to zero" mode, or a float for the
    threshold-constrained mode (see solve_extract_method's docstring)."""
    problem = pulp.LpProblem("extract_method", pulp.LpMinimize)
    selected = {
        statement.index: pulp.LpVariable(f"select_{statement.index}", cat="Binary")
        for statement in statements
    }
    extracted = pulp.LpVariable("extracted", cat="Binary")

    selected_count = pulp.lpSum(selected.values())
    selected_locals = set().union(*(statement.local_variables for statement in statements))
    local_flags = {
        name: pulp.LpVariable(f"local_{name}", cat="Binary")
        for name in selected_locals
    }
    for statement in statements:
        for name in statement.local_variables:
            problem += local_flags[name] >= selected[statement.index]

    for statement in statements:
        for dependency in statement.depends_on:
            if dependency in selected:
                problem += selected[statement.index] <= selected[dependency]

    # A chain-link statement's own source line is `} else if (...) {` - an
    # orphaned closing brace with no opener of its own in a text slice that
    # starts there. It can never safely be the root of an extraction (see
    # java_statement_extractor.is_chain_link), so it's simply never
    # selectable - only its true-nested children (independently safe roots,
    # already exempted from depending on it - see method_to_statements) can
    # be extracted, leaving its own header behind in the original method.
    for statement in statements:
        if statement.is_chain_link:
            problem += selected[statement.index] == 0

    # Downward closure: selecting a statement forces its whole TRUE-nested
    # body to be selected too. Without this, the solver could pick a
    # "gappy" subset (e.g. a deeply nested statement plus its ancestor, but
    # skipping a sibling nested in between) - textually harmless, since the
    # line-range/brace-balancing splice sweeps the skipped code in anyway,
    # but the ILP's own remaining_complexity/extracted_complexity accounting
    # would then silently under-count what's actually being moved. Keeping
    # selections "whole subtree or nothing" keeps that accounting honest.
    for statement in statements:
        for descendant_index in statement.descendants:
            if descendant_index in selected:
                problem += selected[descendant_index] >= selected[statement.index]

    # At most ONE independently-rooted branch (a statement with no forced
    # ancestor - depends_on is empty - and that isn't itself an unselectable
    # chain-link) may be selected. Without this, the solver is free to
    # select statements from two UNRELATED branches at once (e.g. the
    # GOLD/SILVER tier logic inside one "else if" AND the isHoliday check
    # inside a LATER, sibling "else if"), each individually satisfying
    # every constraint above - but the min-to-max LINE RANGE spanning both
    # then necessarily crosses back out through an intervening branch's
    # closing brace that was never opened within the extraction, producing
    # a text splice whose bracket count nets to zero overall but goes
    # NEGATIVE partway through - a real closing brace with no opener in the
    # extracted text, i.e. invalid Java. Restricting to one independent
    # root keeps every selection confined to a single self-contained,
    # already-brace-balanced-when-read-alone subtree.
    # Generalization of the above: siblings sharing the SAME true structural
    # parent (see Statement.true_parent_index) may be combined into ONE
    # contiguous run, instead of being restricted to exactly one - needed
    # for methods whose complexity comes from several separate FLAT sibling
    # constructs rather than one deep nested tree, where no single sibling
    # alone can bring the method under threshold (confirmed on a real case:
    # RandomStringUtils.random()). "Contiguous" (no gaps) is essential, not
    # optional - see true_parent_index's own docstring for why grouping by
    # anything looser (e.g. nesting depth) produces invalid Java.
    #
    # EXCLUDED from combination entirely: any group containing a statement
    # whose own swept text carries a `return` (see Statement.contains_return)
    # - falls back to the ORIGINAL strict "at most one, full stop" rule for
    # that specific group. Not a correctness requirement on its own (a
    # return-containing extraction is separately checked for safety by
    # render_extraction_suggestion regardless), but an empirically-driven
    # one: allowing such groups to combine let the solver's cheapest overall
    # choice become a return-containing combination, which then correctly
    # gets refused for safety - but at the cost of the smaller, genuinely
    # productive, RETURN-FREE single-root extractions the solver would
    # otherwise have found first. Keeping return-containing groups
    # single-select-only preserves that existing, working behavior exactly.
    independent_roots = [s for s in statements if not s.depends_on and not s.is_chain_link]
    roots_by_parent = defaultdict(list)
    for root in independent_roots:
        roots_by_parent[root.true_parent_index].append(root)

    group_active = {
        parent: pulp.LpVariable(f"root_group_active_{parent}", cat="Binary")
        for parent in roots_by_parent
    }
    problem += pulp.lpSum(group_active.values()) <= 1

    for parent, roots in roots_by_parent.items():
        roots_sorted = sorted(roots, key=lambda s: s.index)
        for root in roots_sorted:
            problem += selected[root.index] <= group_active[parent]

        if any(root.contains_return for root in roots_sorted):
            # Return-carrying group: fall back to the original strict rule -
            # at most one member of this group selected, no combination.
            problem += pulp.lpSum(selected[r.index] for r in roots_sorted) <= 1
            continue

        n = len(roots_sorted)
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    # No internal gaps: if the i-th and k-th (i<j<k) roots in
                    # this TRUE sibling sequence are both selected, the j-th
                    # one (physically between them, same statement list)
                    # must be too.
                    problem += (
                        selected[roots_sorted[i].index] + selected[roots_sorted[k].index]
                        <= 1 + selected[roots_sorted[j].index]
                    )

    problem += pulp.lpSum(local_flags.values()) <= max_local_variables
    problem += selected_count >= 2 * extracted
    problem += selected_count <= len(statements) * extracted
    problem += extracted == 1

    extracted_complexity = pulp.lpSum(
        statement.complexity * selected[statement.index]
        for statement in statements
    )
    remaining_complexity_expr = pulp.lpSum(
        statement.complexity * (1 - selected[statement.index])
        for statement in statements
    )

    # Strong preference against selecting any TOP-LEVEL (nesting_depth == 0)
    # statement. Nesting-depth-based cognitive complexity is relative to the
    # enclosing method: a statement that's already at depth 0 contributes
    # the SAME complexity whether it stays put or moves to a new method
    # (depth 0 either way) - only genuinely NESTED statements (depth > 0)
    # get cheaper when hoisted into their own method (their depth resets
    # near 0 there). Without this penalty, the objective's plain
    # "minimize extracted_complexity" happily grabs a cheap, DATA-
    # UNRELATED top-level statement to close the last mile to the
    # threshold (e.g. a `discount > 0.5` guard) - but including it drags
    # the swept text span's start back down to depth 0, erasing the very
    # nesting reduction the deep part of the extraction just achieved. BIG
    # is far larger than any realistic statement-complexity sum, so the
    # solver only touches a depth-0 statement when the threshold is
    # literally unreachable any other way.
    BIG = 1000.0
    depth0_penalty = BIG * pulp.lpSum(
        selected[statement.index] for statement in statements if statement.nesting_depth == 0
    )

    epsilon = 1e-4
    if complexity_threshold is None:
        # Legacy mode: minimize remaining complexity (to zero), tie-broken by
        # smallest extraction. Degenerate for "useful" Extract Method
        # suggestions (it always prefers extracting everything) - kept only
        # as an explicit opt-in fallback, not the default.
        problem += remaining_complexity_expr + epsilon * selected_count
    else:
        # Primary objective: get the ORIGINAL method's remaining complexity
        # under the threshold, then minimize how much needs to be extracted
        # to get there (avoiding depth-0 statements whenever possible - see
        # depth0_penalty above). Minimizing extraction size (not "remaining
        # to zero") is what keeps the suggestion targeted at the deep,
        # expensive nested subtree actually driving the complexity, rather
        # than dragging the whole method out just because that trivially
        # minimizes what's left behind.
        problem += remaining_complexity_expr <= complexity_threshold
        problem += extracted_complexity + epsilon * selected_count + depth0_penalty

    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    return problem, selected


def solve_extract_method(
    statements: list[Statement],
    max_local_variables: int = 4,
    complexity_threshold: float | None = 15.0,
) -> dict:
    """Select a subset of `statements` to extract into a new method.

    `complexity_threshold`: target ceiling for the ORIGINAL method's
    remaining complexity after extraction - matches SonarQube's own S3776
    per-method cognitive-complexity rule (15), NOT the Sense/Analyze
    layer's PR-level `exceeds_significant_complexity_increase` label,
    which is delta-based and answers a different question (did a PR make
    things worse) rather than this one (is a specific method too complex).
    The solver picks the SMALLEST/cheapest extraction that gets remaining
    complexity at or under this threshold, rather than the degenerate
    "extract everything down to zero" behaviour. Pass None to
    fall back to that legacy all-or-nothing minimization.

    If no subset can reach the threshold (some methods are too tangled by
    dependencies to shrink enough with a single extraction), retries once in
    legacy mode and reports status "threshold_unreachable" so callers can
    tell the difference from a true infeasible/no-solution case.
    """
    if not statements:
        return {"status": "not_run", "reason": "no_method_statements"}

    original_complexity = sum(statement.complexity for statement in statements)
    problem, selected = _solve(statements, max_local_variables, complexity_threshold)
    threshold_unreachable = False

    if complexity_threshold is not None and pulp.LpStatus[problem.status] != "Optimal":
        # No way to get under threshold with one extraction — fall back to
        # "minimize remaining as far as possible" so there's still a useful
        # suggestion, but flag it so callers know the threshold wasn't met.
        threshold_unreachable = True
        problem, selected = _solve(statements, max_local_variables, None)

    if pulp.LpStatus[problem.status] != "Optimal":
        return {"status": "infeasible", "solver_status": pulp.LpStatus[problem.status]}

    selected_indices = [
        index for index, variable in selected.items() if variable.value() == 1
    ]
    remaining_complexity = sum(
        statement.complexity
        for statement in statements
        if statement.index not in selected_indices
    )
    return {
        "status": "threshold_unreachable" if threshold_unreachable else "optimal",
        "solver": "CBC",
        "selected_statement_indices": selected_indices,
        "original_complexity": original_complexity,
        "remaining_complexity": remaining_complexity,
        "complexity_threshold": complexity_threshold,
        "max_local_variables": max_local_variables,
    }