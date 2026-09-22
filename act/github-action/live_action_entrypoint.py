"""Entrypoint for the packaged GitHub Action (../../action.yml). Reads the
real `pull_request` event GitHub provides, runs live_predict.py's real,
live prediction against that exact PR, and:

  1. ALWAYS writes a local JSON/Markdown report as a build artifact - this
     alone is a complete, honest "real output against a real live PR" demo,
     independent of comment-posting, and needs no extra permissions beyond
     read access.
  2. OPTIONALLY (only when the `post-comment` Action input is "true"),
     posts/updates a real PR comment via PyGithub - idempotent per
     Methodology §3.4.4's own requirement ("engineered to be idempotent and
     to update its previous comment rather than to accumulate a new comment
     per subsequent commit"): searches existing issue comments for a hidden
     marker and edits that comment rather than posting a new one each run.

IMPORTANT SCOPE CAVEAT, surfaced in the report itself rather than left
implied: the trained models were fit ONLY on apache/commons-lang PR data.
Running this Action on a DIFFERENT repository is mechanically supported
(every feature is computed fresh, live, from that repo's own PR/git data),
but the resulting risk_score is out-of-distribution for the model and
should not be trusted the same way - the report says so explicitly when
this isn't apache/commons-lang, rather than silently presenting a number
with false authority.

Local testing (no real GitHub Actions environment needed - see this
module's own __main__ block / the plan's verification section for the
exact invocation): simulate GITHUB_EVENT_PATH with a hand-built
pull_request event JSON and set GITHUB_REPOSITORY, then run this script
directly. Comment-posting is NOT exercised by local testing against the
real apache/commons-lang upstream - it stays verified-by-code-review only
until tested against a repository the user actually controls.
"""

import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[1]
sys.path.insert(0, str(THIS_DIR))

from live_predict import generate_live_act_report  # noqa: E402

COMMENT_MARKER = "<!-- ppch-framework-action -->"


def read_event() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        raise RuntimeError(
            "GITHUB_EVENT_PATH not set or file missing - this entrypoint expects to run "
            "inside a GitHub Actions pull_request-triggered job (or a local simulation "
            "of one - see this module's docstring)."
        )
    return json.loads(Path(event_path).read_text(encoding="utf-8"))


def resolve_pr_and_repo() -> tuple:
    event = read_event()
    pr_number = event.get("pull_request", {}).get("number") or event.get("number")
    if pr_number is None:
        raise RuntimeError("No pull_request.number found in the event payload.")

    repo_full = os.environ.get("GITHUB_REPOSITORY")
    if repo_full and "/" in repo_full:
        owner, repo = repo_full.split("/", 1)
    else:
        owner = event.get("repository", {}).get("owner", {}).get("login")
        repo = event.get("repository", {}).get("name")
    if not owner or not repo:
        raise RuntimeError("Could not resolve owner/repo from GITHUB_REPOSITORY or the event payload.")
    return int(pr_number), owner, repo


def render_markdown(payload: dict, owner: str, repo: str) -> str:
    out_of_distribution = not (owner == "apache" and repo == "commons-lang")
    lines = [
        COMMENT_MARKER,
        f"## PPCH Framework — PR #{payload['pr_number']} Cognitive Complexity Prediction",
        "",
        f"**Action:** `{payload['action']}`  ",
        payload["message"],
        "",
        f"- Risk score (average of model probabilities): {payload['risk_score']:.3f}",
        f"- Random Forest: {payload['model_probabilities']['random_forest']:.3f}  ",
        f"- XGBoost: {payload['model_probabilities']['xgboost']:.3f}",
        f"- Refactoring suggestion requested: `{payload['refactoring_suggestion_requested']}`",
        "",
    ]
    evidence = payload.get("evidence_pre_submission_features", {})
    if "complexity_before" in evidence or "max_touched_method_complexity" in evidence:
        lines += [
            "**Complexity signals:**",
            f"- complexity_before (target file's pre-existing complexity): {evidence.get('complexity_before', 'n/a')}",
            f"- max_touched_method_complexity (highest complexity among this PR's own new/changed methods): "
            f"{evidence.get('max_touched_method_complexity', 'n/a')}",
            "",
        ]
    if out_of_distribution:
        lines += [
            "> **Scope caveat:** the trained models were fit only on `apache/commons-lang` "
            f"PR data. This repository (`{owner}/{repo}`) is different, so the risk_score "
            "above is out-of-distribution for the model and should be treated as "
            "illustrative, not calibrated.",
            "",
        ]

    ilp = payload.get("ilp", {})
    if ilp.get("status") in ("optimal", "threshold_unreachable"):
        suggestion = ilp.get("suggestion")
        lines += [
            f"### Suggested extraction — `{ilp.get('method_name')}` in `{ilp.get('source_file')}`",
            "",
        ]
        if suggestion and suggestion.get("rendered"):
            safe = suggestion.get("safe_to_auto_apply", False)
            safe_flag = "✅ yes" if safe else "⚠️ NO — see caveat below, manual restructuring needed"
            lines += [
                f"- Safe to auto-apply: {safe_flag}",
                "",
                "```java",
                suggestion["full_snippet"],
                "```",
                "",
                f"*{suggestion['caveat']}*",
                "",
            ]
        elif suggestion:
            lines.append(f"*Could not render a concrete snippet: {suggestion.get('reason')}*\n")
    elif ilp.get("status") not in (None, "not_requested"):
        lines.append(f"*No refactoring suggestion: `{ilp.get('status')}` ({ilp.get('reason', '')})*\n")

    lines.append(
        "This is an advisory, automatically generated prediction — it does not modify "
        "source code and does not block merging."
    )
    return "\n".join(lines) + "\n"


def write_local_report(payload: dict, owner: str, repo: str) -> Path:
    out_dir = ROOT / "evaluation" / "live_action_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"pr_{payload['pr_number']}_live"
    stem.with_suffix(".json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(payload, owner, repo)
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(f"Wrote {stem.with_suffix('.json')}")
    print(f"Wrote {stem.with_suffix('.md')}")
    return stem.with_suffix(".md")


def post_or_update_comment(pr_number: int, owner: str, repo: str, markdown: str) -> None:
    """Idempotent: finds an existing bot comment (by the hidden marker) and
    edits it, rather than posting a new one every run - Methodology §3.4.4's
    own stated requirement."""
    import os as _os
    from github import Github, Auth

    token = _os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN required to post a comment (post-comment was set to true).")
    gh = Github(auth=Auth.Token(token))
    repo_obj = gh.get_repo(f"{owner}/{repo}")
    pr = repo_obj.get_pull(pr_number)

    existing = next((c for c in pr.get_issue_comments() if COMMENT_MARKER in (c.body or "")), None)
    if existing:
        existing.edit(markdown)
        print(f"Updated existing PPCH comment on PR #{pr_number}.")
    else:
        pr.create_issue_comment(markdown)
        print(f"Posted new PPCH comment on PR #{pr_number}.")


def main() -> None:
    pr_number, owner, repo = resolve_pr_and_repo()
    print(f"PPCH live action: PR #{pr_number} on {owner}/{repo}")

    payload = generate_live_act_report(pr_number, owner=owner, repo=repo)
    write_local_report(payload, owner, repo)

    post_comment = os.environ.get("POST_COMMENT", "false").strip().lower() == "true"
    if post_comment:
        markdown = render_markdown(payload, owner, repo)
        post_or_update_comment(pr_number, owner, repo, markdown)
    else:
        print("post-comment is false (default) - local report only, no PR comment posted.")


if __name__ == "__main__":
    main()
