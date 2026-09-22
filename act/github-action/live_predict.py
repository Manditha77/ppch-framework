"""Live prediction: computes a REAL feature vector for an ARBITRARY, live PR
on apache/commons-lang - decoupled from the pre-scanned historical dataset
(sense/data/raw/pilot_scan_results.jsonl) - and runs the same Analyze/Act
pipeline against it.

Methodology §3.4.4 describes the intended final artifact as "a GitHub Action
that could be installed on any Java repository... triggered on pull request
events." Everything else built so far (pipeline.py, explore_candidates.py,
verify_pr_suggestion.py) only REPLAYS PRs that were already scanned into the
historical dataset at Sense-phase time - useful for evaluation, but it can't
answer "what would this framework actually say about a PR that exists right
now." This module closes that gap: given nothing but a PR number, it fetches
everything live via the GitHub API and a real SonarQube scan, the same way a
real deployment would.

Deliberately scoped to apache/commons-lang, the repo the models were
actually trained on - running against a different, untrained repo would be
out-of-distribution for the classifiers (and for the contributor-history
features, which reuse this project's own locally-cached PR history - see
compute_live_feature_row's contributor section). Not a silent limitation:
stated here and checked at the call site.

Every numeric feature is computed with the EXACT SAME mechanism used to
build the training data (02_scan_pilot_batch.py's scan_snapshot for
complexity_before, the persisted PCA/scaler/Word2Vec models from
05_compute_textual_embeddings.py for the textual features) - a live feature
computed a different way would silently drift the model's input
distribution away from what it was actually trained on, undermining the
prediction's validity even if the code runs without error.

Usage:
    python act/github-action/live_predict.py --pr-number 1719
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import joblib
import numpy as np
from dotenv import load_dotenv
from github import Github, Auth

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[1]
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
sys.path.insert(0, str(ROOT / "refactor"))

from pipeline import (  # noqa: E402
    FEATURES, MODEL_DIR, GITHUB_OWNER, GITHUB_REPO,
    WARNING_THRESHOLD, NOTICE_THRESHOLD, STRUCTURAL_COMPLEXITY_THRESHOLD,
    load_models, predict_risk, generate_refactoring_suggestion, decide_intervention,
)
from fetch_source import fetch_file_at_commit  # noqa: E402
from java_statement_extractor import max_complexity_across_sources  # noqa: E402

TOKEN_RE = re.compile(r"[a-zA-Z]+")

LIVE_REPOS_DIR = ROOT / "sense" / "data" / "raw" / "live_repos"


def _ensure_local_clone(owner: str, repo: str) -> Path:
    """02_scan_pilot_batch.py's scan_snapshot() operates on a local git
    clone (checkout a commit, run sonar-scanner, read the report) - for the
    historical batch pipeline that's always the pre-existing commons-lang
    clone (REPO_DIR). A live PR can be on ANY repo, so this clones (once)
    or fetches (on later calls) that repo's own working copy into a
    dedicated directory, keyed by owner/repo - never touches or reuses
    REPO_DIR itself, so the historical pipeline stays completely unaffected
    regardless of what live_predict.py is pointed at."""
    if owner == "apache" and repo == "commons-lang" and _scan.REPO_DIR.exists():
        # Reuse the existing, already-present batch-pipeline clone instead of
        # a redundant fresh clone of the same (large) repository - purely an
        # optimization, not a behavior change (same repo, same commits).
        return _scan.REPO_DIR

    repo_dir = LIVE_REPOS_DIR / f"{owner}__{repo}"
    if not repo_dir.exists():
        LIVE_REPOS_DIR.mkdir(parents=True, exist_ok=True)
        import subprocess
        subprocess.run(
            ["git", "clone", f"https://github.com/{owner}/{repo}.git", str(repo_dir)],
            check=True,
        )
    else:
        import subprocess
        subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, check=True)
    return repo_dir


def _import_by_path(name: str, filename: str):
    """sense/scripts/02_scan_pilot_batch.py and 04_enrich_process_features.py
    have digit-prefixed filenames - not valid Python identifiers, so they
    can't be `import`-ed normally. Load by file path instead."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "sense" / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_scan = _import_by_path("_live_scan", "02_scan_pilot_batch.py")
_enrich = _import_by_path("_live_enrich", "04_enrich_process_features.py")


def _load_env() -> tuple:
    load_dotenv(ROOT / ".env")
    github_token = os.getenv("GITHUB_TOKEN")
    sonar_token = os.getenv("SONAR_TOKEN")
    sonar_host = os.getenv("SONAR_HOST_URL", "http://localhost:9000")
    if not github_token:
        raise RuntimeError("GITHUB_TOKEN not found in .env")
    if not sonar_token:
        raise RuntimeError("SONAR_TOKEN not found in .env")
    return github_token, sonar_token, sonar_host


def compute_live_textual_embeddings(title: str, body: str) -> dict:
    """Reuses the FITTED Word2Vec/PCA/MinMaxScaler models persisted by
    sense/scripts/05_compute_textual_embeddings.py - never refit per PR, or
    the feature distribution would silently drift from what the classifiers
    were trained on (see that module's own docstring for the same point)."""
    from gensim.models import Word2Vec
    from sentence_transformers import SentenceTransformer

    text = f"{title}. {body}"
    tokens = TOKEN_RE.findall(text.lower())

    w2v_model = Word2Vec.load(str(MODEL_DIR / "word2vec.model"))
    word_vecs = [w2v_model.wv[t] for t in tokens if t in w2v_model.wv]
    w2v_raw = np.mean(word_vecs, axis=0) if word_vecs else np.zeros(w2v_model.vector_size)
    w2v_pca = joblib.load(MODEL_DIR / "w2v_pca.joblib")
    w2v_scaler = joblib.load(MODEL_DIR / "w2v_scaler.joblib")
    w2v_reduced = w2v_scaler.transform(w2v_pca.transform([w2v_raw]))[0]

    bert_model = SentenceTransformer("all-MiniLM-L6-v2")
    bert_raw = bert_model.encode([text])[0]
    bert_pca = joblib.load(MODEL_DIR / "bert_pca.joblib")
    bert_scaler = joblib.load(MODEL_DIR / "bert_scaler.joblib")
    bert_reduced = bert_scaler.transform(bert_pca.transform([bert_raw]))[0]

    result = {}
    for i in range(5):
        result[f"w2v_embed_{i}"] = float(w2v_reduced[i])
        result[f"bert_embed_{i}"] = float(bert_reduced[i])
    return result


def compute_live_feature_row(pr_number: int, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> dict:
    """Fetches PR #pr_number LIVE (not from the pre-scanned dataset) and
    computes every field in FEATURES fresh. Returns (feature_row, scan_info)
    where scan_info carries what generate_refactoring_suggestion needs
    (changed_java_files/base_sha/head_sha) without a second GitHub API round
    trip."""
    github_token, sonar_token, sonar_host = _load_env()
    gh = Github(auth=Auth.Token(github_token), per_page=100)
    repo_obj = gh.get_repo(f"{owner}/{repo}")
    pr = repo_obj.get_pull(pr_number)

    changed_files_info = list(pr.get_files())
    changed_java_files = [f.filename for f in changed_files_info if f.filename.endswith(".java")]
    base_sha = pr.base.sha
    head_sha = pr.head.sha
    body = pr.body or ""
    title = pr.title or ""

    row = {
        "pr_number": pr_number,
        "title": title,
        "body": body,
        "created_at": pr.created_at.isoformat(),
        "contributor": pr.user.login if pr.user else None,
        "additions": pr.additions,
        "deletions": pr.deletions,
        "changed_files": pr.changed_files,
        "changed_java_files": len(changed_java_files),
        "commits": pr.commits,
        "comments": pr.comments,
        "review_comments": pr.review_comments,
        "body_character_count": len(body),
        "title_word_count": len(title.split()),
    }

    # complexity_before: a REAL SonarQube scan of the live base-branch state,
    # via the EXACT same scan mechanism (checkout in the shared local clone,
    # full-tree scan, scoped query) 02_scan_pilot_batch.py used to build the
    # training data.
    if changed_java_files:
        project_key = f"live-pred-{owner}-{repo}-{pr_number}-{base_sha[:10]}"
        repo_dir = _ensure_local_clone(owner, repo)
        scan_result = _scan.scan_snapshot(
            base_sha, project_key, changed_java_files, sonar_token, sonar_host, repo_dir=repo_dir,
        )
        _scan.delete_project(project_key, sonar_token, sonar_host)
        row["complexity_before"] = scan_result["complexity"] if scan_result else 0.0
    else:
        row["complexity_before"] = 0.0

    # max_touched_method_complexity: the highest single-method Campbell-rule
    # complexity found across this PR's own HEAD content - independent of
    # complexity_before, and computed the SAME way
    # sense/scripts/06_compute_touched_code_complexity.py backfilled it for
    # the training set (fetch HEAD content, run the same AST approximation,
    # take the max). Closes the gap where a brand-new file's own complexity
    # was otherwise invisible to the model - see that script's own docstring.
    head_sources = []
    for file_path in changed_java_files:
        try:
            head_sources.append(fetch_file_at_commit(owner, repo, head_sha, file_path))
        except Exception as exc:  # noqa: BLE001 — file removed/renamed by a later commit, network hiccup
            print(f"  [warn] could not fetch {file_path}@{head_sha[:10]} for complexity scoring: {exc}")
    row["max_touched_method_complexity"] = max_complexity_across_sources(head_sources)

    # Contributor process features - reuses 04_enrich_process_features.py's
    # own local historical index (sense/data/raw/apache_commons-lang_prs.jsonl)
    # rather than re-deriving it; valid as long as this stays scoped to the
    # repo the model was trained on (see module docstring).
    try:
        history = _enrich.load_full_history()
    except FileNotFoundError:
        # sense/data/raw/apache_commons-lang_prs.jsonl is local research data,
        # deliberately gitignored (see .gitignore's sense/data/raw/* rule) -
        # a fresh checkout of this Action on a machine that never ran the
        # Sense-phase scripts (e.g. the packaged Action running on someone
        # else's runner) won't have it. contributor_index.get(login, [])
        # already degrades to the same zero-stats prior_stats() returns for
        # an unknown login, so an empty history here is a safe, honest
        # fallback rather than crashing the whole prediction.
        history = []
    contributor_index = _enrich.build_contributor_index(history)
    login = row["contributor"]
    if login:
        stats = _enrich.prior_stats(contributor_index, login, row["created_at"])
        follower_cache = _enrich.load_follower_cache()
        stats["contributor_follower_count"] = _enrich.get_follower_count(gh, login, follower_cache)
    else:
        stats = {
            "contributor_prior_pr_count": 0,
            "contributor_prior_acceptance_rate": 0.0,
            "contributor_tenure_days": 0.0,
            "contributor_follower_count": 0,
        }
    row.update(stats)

    row.update(compute_live_textual_embeddings(title, body))

    missing = [f for f in FEATURES if f not in row]
    if missing:
        raise RuntimeError(f"compute_live_feature_row did not populate: {missing}")

    scan_info = {"changed_java_files": changed_java_files, "base_sha": base_sha, "head_sha": head_sha}
    return row, scan_info


def build_live_intervention(feature_row: dict, prediction: dict) -> dict:
    """The live-deployment counterpart of pipeline.py's build_intervention -
    same thresholds, same action/message logic, but WITHOUT the
    post_hoc_validation block: that section compares the prediction against
    an already-known actual outcome, which only exists for historical PRs
    replayed from the pre-scanned dataset. A genuinely live, still-open PR
    has no "actual" outcome yet - this is the real "predict blind" case the
    rest of the framework's post-hoc validation exists to check against, not
    a case that itself has ground truth to check."""
    risk_score = prediction["risk_score"]
    decision = decide_intervention(risk_score, feature_row.get("max_touched_method_complexity", 0.0))

    return {
        "pr_number": feature_row["pr_number"],
        "stage": "predicted_at_submission_time_LIVE",
        **decision,
        "risk_score": risk_score,
        "model_probabilities": prediction["model_probabilities"],
        "warning_threshold": WARNING_THRESHOLD,
        "notice_threshold": NOTICE_THRESHOLD,
        "structural_complexity_threshold": STRUCTURAL_COMPLEXITY_THRESHOLD,
        "predicted_label": int(risk_score >= 0.5),
        "evidence_pre_submission_features": {f: feature_row[f] for f in FEATURES},
    }


def generate_live_act_report(pr_number: int, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> dict:
    feature_row, scan_info = compute_live_feature_row(pr_number, owner, repo)
    models = load_models()
    prediction = predict_risk(models, feature_row)
    payload = build_live_intervention(feature_row, prediction)
    payload["ilp"] = (
        generate_refactoring_suggestion(pr_number, scan_record=scan_info, owner=owner, repo=repo)
        if payload["refactoring_suggestion_requested"]
        else {"status": "not_requested"}
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--owner", default=GITHUB_OWNER)
    parser.add_argument("--repo", default=GITHUB_REPO)
    args = parser.parse_args()

    print(f"Fetching PR #{args.pr_number} on {args.owner}/{args.repo} LIVE (not from the historical dataset)...")
    payload = generate_live_act_report(args.pr_number, args.owner, args.repo)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
