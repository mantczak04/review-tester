"""Review-Tester – Streamlit app for testing LLM code-review prompts."""

import os
import pathlib

import streamlit as st
from dotenv import load_dotenv

from github_client import (
    get_file_content,
    get_pr_files,
    get_pr_metadata,
    parse_pr_url,
)
from llm_client import AVAILABLE_MODELS, run_review

load_dotenv()  # no-op on Streamlit Cloud, useful locally


def _get_secret(key: str) -> str:
    """Read from st.secrets first (Streamlit Cloud), fall back to env var (.env)."""
    print(st.secrets["GITHUB_TOKEN"])  # Debug print to verify secrets access
    print(st.secrets["GEMINI_API_KEY"])  # Debug print to verify secrets access
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, "")


PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"
GITHUB_TOKEN = _get_secret("GITHUB_TOKEN")
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Review Tester", layout="wide")

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------
for key, default in {
    "pr_meta": None,
    "pr_files": None,
    "file_contents": None,
    "review_result": None,
    "fetched_url": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_prompts() -> list[str]:
    """Return sorted list of .txt filenames in the prompts directory."""
    PROMPTS_DIR.mkdir(exist_ok=True)
    return sorted(p.name for p in PROMPTS_DIR.glob("*.txt"))


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def save_prompt(name: str, content: str) -> None:
    (PROMPTS_DIR / name).write_text(content, encoding="utf-8")


def build_diff_payload(files: list[dict]) -> str:
    """Build a compact diff string from the list of PR files (patches)."""
    parts: list[str] = []
    for f in files:
        patch = f.get("patch", "")
        if not patch:
            continue
        parts.append(f"### File: {f['filename']}  (status: {f['status']})\n```diff\n{patch}\n```")
    return "\n\n".join(parts)


COMMENT_COLORS = {
    "bug": "🔴",
    "security": "🟠",
    "performance": "🟡",
    "style": "🔵",
    "suggestion": "🟢",
}

# ---------------------------------------------------------------------------
# TOP BAR – PR URL input
# ---------------------------------------------------------------------------
st.markdown("## 🔍 Review Tester")
pr_url = st.text_input(
    "Pull Request URL",
    placeholder="https://github.com/SerenityOS/serenity/pull/26562",
)

# Fetch PR when URL changes
if pr_url and pr_url != st.session_state.fetched_url:
    with st.spinner("Fetching pull request…"):
        try:
            owner, repo, pr_number = parse_pr_url(pr_url)
            meta = get_pr_metadata(owner, repo, pr_number, GITHUB_TOKEN)
            files = get_pr_files(owner, repo, pr_number, GITHUB_TOKEN)

            # Fetch full file contents for the diff viewer
            contents: dict[str, dict] = {}
            for f in files:
                fname = f["filename"]
                old_path = f.get("previous_filename") or fname
                if f["status"] == "added":
                    old_text = ""
                else:
                    old_text = get_file_content(owner, repo, old_path, meta["base_sha"], GITHUB_TOKEN) or ""
                if f["status"] == "removed":
                    new_text = ""
                else:
                    new_text = get_file_content(owner, repo, fname, meta["head_sha"], GITHUB_TOKEN) or ""
                contents[fname] = {"old": old_text, "new": new_text}

            st.session_state.pr_meta = meta
            st.session_state.pr_files = files
            st.session_state.file_contents = contents
            st.session_state.review_result = None
            st.session_state.fetched_url = pr_url
        except Exception as e:
            st.error(f"Failed to fetch PR: {e}")

# Show PR title
if st.session_state.pr_meta:
    st.caption(
        f"**{st.session_state.pr_meta['title']}** · "
        f"`{st.session_state.pr_meta['base_ref']}` ← `{st.session_state.pr_meta['head_ref']}` · "
        f"{len(st.session_state.pr_files)} file(s) changed"
    )

st.divider()

# ---------------------------------------------------------------------------
# MAIN LAYOUT: left sidebar (prompt + model) | right area (diffs + comments)
# ---------------------------------------------------------------------------
left_col, right_col = st.columns([1, 3], gap="large")

# ---- LEFT COLUMN ----
with left_col:
    st.markdown("### Prompt")

    prompt_names = list_prompts()
    if not prompt_names:
        save_prompt("default.txt", "You are a code reviewer.\n\n{DIFF}")
        prompt_names = list_prompts()

    # --- Prompt source ---
    prompt_source = st.radio(
        "Source",
        ["From prompts/", "Upload .txt"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if prompt_source == "From prompts/":
        selected_prompt = st.selectbox("Master prompt file", prompt_names)
        # When selection changes, reload text into editor
        if st.session_state.get("_last_selected_prompt") != selected_prompt:
            st.session_state["_last_selected_prompt"] = selected_prompt
            st.session_state["prompt_editor"] = load_prompt(selected_prompt)
    else:
        selected_prompt = None
        uploaded = st.file_uploader("Upload prompt .txt", type=["txt"])
        if uploaded is not None:
            # Only reload when a new file is uploaded
            if st.session_state.get("_last_uploaded_name") != uploaded.name:
                st.session_state["_last_uploaded_name"] = uploaded.name
                st.session_state["prompt_editor"] = uploaded.read().decode("utf-8")

    # Seed editor from prompts/ on very first run
    if "prompt_editor" not in st.session_state:
        first = prompt_names[0] if prompt_names else None
        st.session_state["prompt_editor"] = load_prompt(first) if first else ""

    edited_prompt = st.text_area(
        "Edit prompt",
        height=350,
        key="prompt_editor",
    )

    # Save / Save-as buttons
    if prompt_source == "From prompts/" and selected_prompt:
        save_col, saveas_col = st.columns(2)
        with save_col:
            if st.button("💾 Save", use_container_width=True):
                save_prompt(selected_prompt, edited_prompt)
                st.success(f"Saved {selected_prompt}")
        with saveas_col:
            new_name = st.text_input("Save as", placeholder="new.txt", label_visibility="collapsed")
            if st.button("💾 Save as", use_container_width=True) and new_name:
                fname = new_name if new_name.endswith(".txt") else new_name + ".txt"
                save_prompt(fname, edited_prompt)
                st.success(f"Saved as {fname}")
                st.rerun()
    else:
        # Uploaded file: offer saving to prompts/
        new_name = st.text_input("Save to prompts/ as", placeholder="my_prompt.txt")
        if st.button("💾 Save to prompts/", use_container_width=True) and new_name:
            fname = new_name if new_name.endswith(".txt") else new_name + ".txt"
            save_prompt(fname, edited_prompt)
            st.success(f"Saved as {fname}")
            st.rerun()

    st.markdown("---")
    st.markdown("### Model")
    selected_model = st.selectbox("Gemini model", AVAILABLE_MODELS)

    st.markdown("---")

    # TEST PROMPT button
    test_disabled = st.session_state.pr_files is None
    if st.button("🚀 Test Prompt", type="primary", disabled=test_disabled, use_container_width=True):
        diff_payload = build_diff_payload(st.session_state.pr_files)
        with st.spinner("Sending to Gemini…"):
            try:
                result = run_review(edited_prompt, diff_payload, selected_model, GEMINI_API_KEY)
                st.session_state.review_result = result
            except Exception as e:
                st.error(f"LLM error: {e}")

# ---- RIGHT COLUMN: Diffs + Review Comments ----
with right_col:
    if st.session_state.pr_files is None:
        st.info("Paste a GitHub PR URL above to get started.")
    else:
        from st_diff_viewer import diff_viewer

        files = st.session_state.pr_files
        contents = st.session_state.file_contents or {}
        review = st.session_state.review_result

        # Index comments by filename for quick lookup
        comments_by_file: dict[str, list[dict]] = {}
        if review and "comments" in review:
            for c in review["comments"]:
                comments_by_file.setdefault(c.get("file", ""), []).append(c)

        for f in files:
            fname = f["filename"]
            status_badge = {"added": "🟢", "removed": "🔴", "modified": "🟡", "renamed": "🔄"}.get(f["status"], "⚪")
            file_comments = comments_by_file.get(fname, [])
            comment_badge = f" — **{len(file_comments)} comment(s)**" if file_comments else ""

            with st.expander(f"{status_badge} {fname}{comment_badge}", expanded=bool(file_comments)):
                fc = contents.get(fname, {})
                old_text = fc.get("old", "")
                new_text = fc.get("new", "")

                # Highlighted lines (from review comments)
                highlight = [str(c["line"]) for c in file_comments if "line" in c]

                diff_viewer(
                    old_text,
                    new_text,
                    split_view=True,
                    use_dark_theme=True,
                    left_title=st.session_state.pr_meta["base_ref"],
                    right_title=st.session_state.pr_meta["head_ref"],
                    highlight_lines=highlight,
                    key=f"diff_{fname}",
                )

                # Render review comments below the diff
                for c in sorted(file_comments, key=lambda x: x.get("line", 0)):
                    icon = COMMENT_COLORS.get(c.get("type", ""), "💬")
                    line_info = f"Line {c['line']}" if "line" in c else "General"
                    ctype = c.get("type", "comment").upper()
                    st.markdown(
                        f"> {icon} **{ctype}** ({line_info}): {c['comment']}"
                    )

        # Summary
        if review and review.get("summary"):
            st.divider()
            st.markdown("### 📝 Review Summary")
            st.markdown(review["summary"])
