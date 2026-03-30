import json
import re
from datetime import datetime
from pathlib import Path

import anthropic

from .base import EnhancementWorkflow, WorkflowError

_MODEL = "claude-haiku-4-5-20251001"

# Common fields across Basic, Cloze, and custom notetypes.
# read_notes.py returns "" for fields absent on a notetype — safe to list more than any one type has.
_CANDIDATE_FIELDS = ["Front", "Back", "Question", "Answer", "Context", "Explanation", "Text", "Extra"]

_SYSTEM = """\
You are an expert Anki flashcard designer and spaced-repetition coach. Your job is to \
diagnose why a card has become a leech (failed 8+ times) by identifying flashcard design \
failures and suggesting a concrete revision.

Analyse the card against these failure modes (based on SuperMemo's 20 rules):

1. MINIMUM INFORMATION — The card tests more than one independent fact. Each card should \
test exactly one atomic piece of knowledge.

2. AMBIGUOUS QUESTION — The question has multiple valid answers, or the phrasing does not \
uniquely determine the expected answer.

3. MISSING CONTEXT — The card relies on knowledge not present on the card itself \
(orphaned material). Without surrounding context, the question is unanswerable or \
meaningless in isolation.

4. SET/ENUMERATION — The card asks the learner to recall a list or set of items. Sets are \
notoriously hard to memorise; each item should become its own card or use cloze deletion.

5. PASSIVE RECOGNITION — The phrasing makes it too easy to recognise the answer without \
actively recalling it (e.g. yes/no questions, fill-in-the-blank where only one word \
grammatically fits).

6. OVER-COMPLEXITY — The card is too wordy, technical, or abstract. Simpler phrasing \
reduces cognitive load and improves retention.

7. INTERFERENCE (suspected) — The card is very similar in surface form to other cards, \
likely causing confusion during review. Flag only if the wording strongly suggests it; \
you cannot confirm without seeing other cards.

Output a single JSON object — no markdown fences, no explanation outside the JSON:

{
  "issues": ["<short description of each problem, one string per issue>"],
  "severity": "<high|medium|low>",
  "revised_front": "<improved question, or original if no change needed>",
  "revised_back": "<improved answer, or original if no change needed>",
  "rationale": "<one paragraph: diagnosis and why the revision helps>"
}

Severity guide:
- high   — the design flaw is almost certainly the primary cause of leech status
- medium — a significant contributor, but other factors may be involved
- low    — minor polish; card may be leech for content-difficulty reasons, not design

If all fields are empty or near-empty, set issues to ["Insufficient content to analyse"] \
and severity to "low".\
"""


class LeechReviewWorkflow(EnhancementWorkflow):
    WORKFLOW_NAME = "leech_review"
    INPUT_FIELDS = _CANDIDATE_FIELDS
    OUTPUT_FIELDS = []
    REQUIRED_ENV_KEYS = ["ANTHROPIC_API_KEY"]
    DEFAULT_ADD_TAG = "leech-reviewed"
    DEFAULT_REMOVE_TAG = ""

    def __init__(self, config: dict):
        super().__init__(config)
        self._client = anthropic.Anthropic(api_key=config["anthropic_api_key"])
        self._results: list[dict] = []
        self._query: str = config.get("query", "")
        self._run_ts: datetime = datetime.now()

    def process_note(self, note_id: str, fields: dict[str, str]) -> dict[str, str]:
        parts = [
            f"{field}: {fields[field].strip()}"
            for field in self._input_fields
            if fields.get(field, "").strip()
        ]
        if not parts:
            raise WorkflowError("All candidate input fields are empty — cannot analyse")

        try:
            msg = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": "\n".join(parts)}],
            )
        except anthropic.APIError as e:
            raise WorkflowError(f"Claude API error: {e}")

        raw = msg.content[0].text.strip()
        data = self._parse_json(raw)

        severity = str(data.get("severity", "low")).strip().upper()
        if severity not in ("HIGH", "MEDIUM", "LOW"):
            severity = "LOW"

        front_val = next(
            (fields.get(f, "").strip() for f in ("Front", "Question", "Text") if fields.get(f, "").strip()),
            next((v.strip() for v in fields.values() if not v.startswith("__") and v.strip()), ""),
        )
        back_val = next(
            (fields.get(f, "").strip() for f in ("Back", "Answer", "Explanation", "Extra") if fields.get(f, "").strip()),
            "",
        )

        self._results.append({
            "note_id": note_id,
            "severity": severity,
            "front": front_val,
            "back": back_val,
            "issues": data.get("issues") or [],
            "revised_front": str(data.get("revised_front", "")).strip(),
            "revised_back": str(data.get("revised_back", "")).strip(),
            "rationale": str(data.get("rationale", "")).strip(),
        })

        return {}  # nothing to write back to Anki fields

    def teardown(self) -> None:
        if not self._results:
            print("leech_review: no results to write")
            return
        out_path = Path.home() / "Downloads" / f"leech_review_{self._run_ts.strftime('%Y%m%d_%H%M%S')}.md"
        out_path.write_text(self._render_markdown(), encoding="utf-8")
        print(f"\nLeech review report: {out_path}")

    def _parse_json(self, raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            raise WorkflowError(f"Could not parse JSON from Claude response:\n{raw[:300]}")

    def _render_markdown(self) -> str:
        severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        sorted_results = sorted(self._results, key=lambda r: severity_order.get(r["severity"], 3))

        lines = [
            f"# Leech Review — {self._run_ts.strftime('%Y-%m-%d')}",
            "",
            f"**Generated:** {self._run_ts.strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**Query:** {self._query}  ",
            f"**Total reviewed:** {len(self._results)}  ",
            "",
            "---",
            "",
        ]
        for r in sorted_results:
            front = r["front"] or "(empty)"
            back = r["back"] or "(empty)"
            revised_front = r["revised_front"] or front
            revised_back = r["revised_back"] or back
            issues = r["issues"] or []
            issues_lines = [f"{i + 1}. {issue}" for i, issue in enumerate(issues)] or ["(none identified)"]

            lines += [
                f"## Card {r['note_id']} — {r['severity']}",
                "",
                f"**Front:** {front}  ",
                f"**Back:** {back}  ",
                "",
                "### Issues",
                *issues_lines,
                "",
                "### Suggested Revision",
                f"**New Front:** {revised_front}  ",
                f"**New Back:** {revised_back}  ",
                "",
                f"**Rationale:** {r['rationale'] or '(none provided)'}",
                "",
                "---",
                "",
            ]
        return "\n".join(lines)
