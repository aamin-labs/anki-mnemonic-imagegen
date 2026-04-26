#!/usr/bin/env python3
"""Consolidate Anki Context field values into a smaller stable tag set.

Must be run with Anki's bundled Python because it writes to collection.anki2.

Examples:
  Dry run on the AI & Coding deck:
    /Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13 \
      scripts/consolidate_context_tags.py \
      --query 'deck:"1. 🎖️ Active::1.10 🤖 AI & Coding"' \
      --dry-run

  Apply changes:
    /Users/aamin/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13 \
      scripts/consolidate_context_tags.py \
      --query 'deck:"1. 🎖️ Active::1.10 🤖 AI & Coding"'
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path


ANKI2_ROOT = Path.home() / "Library" / "Application Support" / "Anki2"
STABLE_TAGS = [
    "RAG",
    "Agents",
    "Python",
    "Git",
    "LangGraph",
    "LLM architecture",
    "Post-training",
    "Evaluation",
    "Inference",
    "Claude Code",
    "UI",
]
TAG_ORDER = {tag: i for i, tag in enumerate(STABLE_TAGS)}
HTML_RE = re.compile(r"<[^>]+>")


EXACT_MAP: dict[str, tuple[str, ...]] = {
    "a2a": ("Agents",),
    "advantage": ("Post-training",),
    "agent architecture": ("Agents",),
    "agent evals": ("Agents", "Evaluation"),
    "agent memory": ("Agents",),
    "agent patterns": ("Agents", "Evaluation"),
    "agentic document extraction": ("Agents",),
    "agentic workflows": ("Agents",),
    "agents": ("Agents",),
    "agents - event-driven workflows": ("Agents",),
    "ai agent evaluation": ("Agents", "Evaluation"),
    "ai deployment": ("UI",),
    "alignment tax": ("Post-training", "Evaluation"),
    "architecture": ("LLM architecture",),
    "architecture variants": ("LLM architecture",),
    "asyncio": ("Python",),
    "attention": ("LLM architecture",),
    "attention mechanism": ("LLM architecture",),
    "bash": ("Python",),
    "catastrophic adherence": ("Post-training",),
    "causal masking": ("LLM architecture",),
    "chinchilla": ("LLM architecture",),
    "claude code": ("Claude Code",),
    "clipping": ("Post-training",),
    "cloud": ("Python",),
    "cloud services": ("Python",),
    "compute": ("Post-training", "Inference"),
    "concepts": ("LLM architecture",),
    "constitutional ai": ("Post-training",),
    "context": ("Claude Code",),
    "context engineering": ("Claude Code", "Agents"),
    "cot": ("Post-training",),
    "critiques": ("Post-training",),
    "cross-attention": ("LLM architecture",),
    "cross-entropy": ("Post-training",),
    "data agents": ("Agents",),
    "data mixing": ("Post-training",),
    "data pipeline": ("Post-training",),
    "data splits": ("Post-training",),
    "deepseek r1": ("Post-training",),
    "deepseek r1 zero": ("Post-training",),
    "deploying to production": ("UI",),
    "distillation": ("Post-training",),
    "dpo": ("Post-training",),
    "dpo vs rlhf": ("Post-training",),
    "embeddings": ("RAG",),
    "error analysis": ("Evaluation",),
    "evaluating ai agents": ("Agents", "Evaluation"),
    "evaluation": ("Evaluation",),
    "evaluting ai agents": ("Agents", "Evaluation"),
    "fine tuning": ("Post-training",),
    "fine-tuning": ("Post-training",),
    "fine-tuning math": ("Post-training",),
    "fine-turning and rl": ("Post-training",),
    "functions": ("Python",),
    "git": ("Git",),
    "grpo": ("Post-training",),
    "grpo efficiency": ("Post-training",),
    "grpo loss": ("Post-training",),
    "grpo vs ppo": ("Post-training",),
    "hyperparameters": ("Post-training",),
    "infrastructure": ("Inference",),
    "kl divergence": ("Post-training",),
    "knowledge graphs": ("RAG",),
    "kv caching": ("Inference",),
    "langchain": ("RAG",),
    "lcel": ("Agents",),
    "llm": ("LLM architecture",),
    "llm basics": ("LLM architecture",),
    "llm training": ("LLM architecture",),
    "llm training phases": ("LLM architecture",),
    "llms": ("LLM architecture",),
    "lora": ("Post-training",),
    "loss curves": ("Post-training", "Evaluation"),
    "mcp architecture": ("Agents", "Claude Code"),
    "mcts": ("Post-training",),
    "mcts / agentq": ("Agents", "Post-training"),
    "mcts / dpo": ("Post-training",),
    "mental models": ("LLM architecture",),
    "model optimization": ("Inference",),
    "networks": ("Python",),
    "on-policy": ("Post-training",),
    "openai agents": ("Agents",),
    "openai agents sdk": ("Agents", "Python"),
    "openai api": ("Python",),
    "openai sdk": ("Python",),
    "pass@k": ("Evaluation",),
    "pass k": ("Evaluation",),
    "pipeline": ("Python",),
    "post-training": ("Post-training",),
    "pre-training": ("LLM architecture",),
    "production": ("Evaluation",),
    "production interventions": ("Evaluation",),
    "promotion rules": ("Evaluation",),
    "pruning": ("Inference",),
    "pydantic": ("Python",),
    "python": ("Python",),
    "python - pydantic": ("Python",),
    "python classes": ("Python",),
    "python functions": ("Python",),
    "quantization": ("Inference",),
    "rag": ("RAG",),
    "rag - chunking": ("RAG",),
    "rag - evaluations": ("RAG", "Evaluation"),
    "rag - query enhancement": ("RAG",),
    "rag - rrf": ("RAG",),
    "react": ("UI",),
    "refactoring ui": ("UI",),
    "reproducibility": ("Evaluation",),
    "reward balancing": ("Post-training",),
    "reward hacking": ("Post-training", "Evaluation"),
    "reward shaping": ("Post-training",),
    "rl": ("Post-training",),
    "rl approach selection": ("Post-training",),
    "rl classification": ("Post-training",),
    "rl compute": ("Post-training",),
    "rl data": ("Post-training",),
    "rl emergence": ("Post-training",),
    "rl monitoring": ("Post-training", "Evaluation"),
    "rl stability": ("Post-training",),
    "rl training": ("Post-training",),
    "rl training objective": ("Post-training",),
    "rl/grpo": ("Post-training",),
    "rl/ppo": ("Post-training",),
    "rlhf": ("Post-training",),
    "sampling": ("Inference",),
    "sas": ("Python",),
    "scaling laws": ("LLM architecture",),
    "self-attention": ("LLM architecture",),
    "semantic caching": ("RAG", "Inference"),
    "sft": ("Post-training",),
    "sft+grpo": ("Post-training",),
    "sft+rl": ("Post-training",),
    "sft-then-rl": ("Post-training",),
    "sglang/attention": ("Inference", "LLM architecture"),
    "sglang/inference": ("Inference",),
    "sglang/kvcache": ("Inference",),
    "software engineering": ("Python",),
    "structured generation": ("Inference",),
    "swe": ("Python",),
    "syntax": ("Python",),
    "synthetic data": ("Post-training",),
    "terminal": ("Python",),
    "testing": ("Python",),
    "these are architecture type names distinct from training objective names.": ("LLM architecture",),
    "tokenization": ("LLM architecture",),
    "traffic management": ("Python",),
    "training": ("LLM architecture",),
    "training selection": ("Post-training",),
    "transformer architecture": ("LLM architecture",),
    "transformers": ("LLM architecture",),
    "ui - colours": ("UI",),
    "ui - depth": ("UI",),
    "uncertainty": ("Evaluation",),
    "vectorisation": ("RAG",),
    "web development": ("UI",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Anki search query")
    parser.add_argument("--anki-profile", default="Abu", help="Anki profile name (default: Abu)")
    parser.add_argument("--field", default="Context", help="Field to normalize (default: Context)")
    parser.add_argument("--notetype", default="aBasic (opt rev)", help="Only update this notetype")
    parser.add_argument("--limit", type=int, help="Process at most N matching notes")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    return parser.parse_args()


def ensure_anki_closed() -> None:
    result = subprocess.run(["pgrep", "-x", "Anki"], capture_output=True)
    if result.returncode == 0:
        raise SystemExit("Anki is running. Close it first.")


def resolve_collection_path(profile: str) -> Path:
    col_path = ANKI2_ROOT / profile / "collection.anki2"
    if not col_path.exists():
        raise SystemExit(f"Collection not found: {col_path}")
    return col_path


def backup_collection(col_path: Path) -> Path:
    backup_path = Path(str(col_path) + f".backup_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(col_path, backup_path)
    return backup_path


def normalize_context(raw: str) -> str:
    unescaped = html.unescape(raw or "")
    without_html = HTML_RE.sub(" ", unescaped)
    cleaned = re.sub(r"\s+", " ", without_html.replace("\xa0", " ")).strip()
    return cleaned


def normalize_key(raw: str) -> str:
    cleaned = normalize_context(raw).lower()
    cleaned = cleaned.replace("—", " ")
    cleaned = re.sub(r"[()]", " ", cleaned)
    cleaned = re.sub(r"[:;]+", " ", cleaned)
    cleaned = cleaned.replace("&", "and")
    cleaned = re.sub(r"[^a-z0-9,+/\- ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    return cleaned


def ordered_tags(tags: tuple[str, ...] | list[str]) -> str:
    deduped = []
    seen = set()
    for tag in tags:
        if tag not in seen:
            deduped.append(tag)
            seen.add(tag)
    return ", ".join(sorted(deduped, key=TAG_ORDER.__getitem__))


def classify_context(raw: str) -> str:
    key = normalize_key(raw)
    if not key:
        return ""

    if key in EXACT_MAP:
        return ordered_tags(EXACT_MAP[key])

    if key.startswith("langgraph"):
        return "LangGraph"
    if key.startswith("rag"):
        return "RAG"
    if "claude code" in key:
        return "Claude Code"
    if "agent" in key or key in {"a2a", "lcel"}:
        return "Agents"
    if any(token in key for token in ("mcp", "context engineering")):
        return ordered_tags(("Agents", "Claude Code"))
    if any(token in key for token in ("quantization", "kv", "inference", "sglang", "sampling", "structured generation", "pruning")):
        return "Inference"
    if any(token in key for token in ("semantic caching", "knowledge graph", "embedding", "vector", "retriev", "langchain")):
        return ordered_tags(("RAG", "Inference")) if "semantic caching" in key else "RAG"
    if any(token in key for token in ("fine", "lora", "distillation", "dpo", "grpo", "ppo", "rl", "rlhf", "sft", "reward", "constitutional", "critique", "hyperparameter", "alignment", "synthetic data")):
        return "Post-training"
    if any(token in key for token in ("eval", "error analysis", "pass@k", "production", "uncertainty", "reproducibility")):
        return "Evaluation"
    if any(token in key for token in ("attention", "transformer", "tokenization", "architecture", "llm", "pre-training", "scaling laws", "chinchilla", "causal masking", "cross-attention", "training")):
        return "LLM architecture"
    if any(token in key for token in ("react", "ui", "web development", "deployment")):
        return "UI"
    if key == "git":
        return "Git"
    if any(token in key for token in ("python", "pydantic", "asyncio", "bash", "function", "terminal", "syntax", "testing", "software engineering", "swe", "network", "cloud", "traffic management", "pipeline")):
        return "Python"

    raise ValueError(f"Unmapped context: {raw!r} -> {key!r}")


def main() -> None:
    from anki.collection import Collection

    args = parse_args()
    ensure_anki_closed()
    col_path = resolve_collection_path(args.anki_profile)

    col = Collection(str(col_path))
    try:
        note_ids = col.find_notes(args.query)
        if args.limit:
            note_ids = note_ids[:args.limit]
        print(f"Found {len(note_ids)} matching notes")
        if not note_ids:
            return

        updates: list[tuple[int, str, str]] = []
        skipped_notetype = 0
        skipped_missing_field = 0
        unchanged = 0
        before_counts: Counter[str] = Counter()
        after_counts: Counter[str] = Counter()

        for nid in note_ids:
            note = col.get_note(nid)
            nt = col.models.get(note.mid)
            if nt["name"] != args.notetype:
                skipped_notetype += 1
                continue

            fields = dict(note.items())
            if args.field not in fields:
                skipped_missing_field += 1
                continue

            current = fields[args.field].strip()
            before_counts[current] += 1
            new_value = classify_context(current)
            after_counts[new_value] += 1

            if current == new_value:
                unchanged += 1
                continue

            updates.append((nid, current, new_value))

        print(f"Eligible notes: {sum(before_counts.values())}")
        print(f"Skipped non-target notetype: {skipped_notetype}")
        print(f"Skipped missing field: {skipped_missing_field}")
        print(f"Planned updates: {len(updates)}")
        print(f"Already normalized: {unchanged}")

        print("\nTop source values:")
        for value, count in before_counts.most_common(20):
            label = value or "<empty>"
            print(f"  {count:>3}  {label}")

        print("\nStable tag totals:")
        for value, count in after_counts.most_common():
            label = value or "<empty>"
            print(f"  {count:>3}  {label}")

        print("\nSample rewrites:")
        shown = 0
        seen_pairs = set()
        for _, old, new in updates:
            pair = (old, new)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            print(f"  {old or '<empty>'}  ->  {new or '<empty>'}")
            shown += 1
            if shown >= 25:
                break

        if args.dry_run:
            print("\nDry run only — no changes written.")
            return

        if not updates:
            print("\nNo changes needed.")
            return

        backup_path = backup_collection(col_path)
        print(f"\n✓ Backup saved to: {backup_path}")

        updated_nids: list[int] = []
        for nid, _, new_value in updates:
            note = col.get_note(nid)
            note[args.field] = new_value
            col.update_note(note)
            updated_nids.append(nid)

        if updated_nids:
            col.after_note_updates(updated_nids, mark_modified=True, generate_cards=False)

        print(f"✓ Updated {len(updated_nids)} notes")
    finally:
        col.close()


if __name__ == "__main__":
    main()
