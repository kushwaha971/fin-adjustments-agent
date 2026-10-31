"""Turn findings into plain English for a finance user.

This is the only place an LLM is used, and it only writes the wording.
It never sees the decision as something it can change, and its output is
checked: if it mentions a number that is not in the findings, we throw the
text away and use the template instead. A wrong explanation is worse than
a dull one.
"""

import os
import re
from typing import List

from .checks import Finding

MODEL = os.environ.get("ADJUSTER_MODEL", "claude-haiku-5-5")

# What a controller should do next, per finding code.
NEXT_STEP = {
    "JE_UNBALANCED": "Correct the line amounts so debits equal credits and resubmit.",
    "JE_UNKNOWN_ACCOUNT": "Confirm the right account (or ask for it to be added to the COA), then resubmit.",
    "JE_CIRCULAR": "Confirm with the intercompany team what this settlement should move; as written it changes nothing.",
    "JE_FX_MISMATCH": "Send the reval calculation so we can see which rate the balance is carried at.",
    "JE_FX_UNVERIFIABLE": "Provide the missing rate or balance so the revaluation can be checked.",
    "JE_OUT_OF_PERIOD": "Confirm the entry belongs to this period.",
    "JE_POSTS_TO_HEADER": "Post to a child account instead of the header.",
    "JE_LINE_BOTH_SIDES": "Split the line into a debit line and a credit line.",
    "JE_NEGATIVE_AMOUNT": "Use the other side instead of a negative amount.",
    "JE_DUPLICATE_ID": "Give the entry a unique id.",
    "JE_MATERIAL": "No action needed - flagged for reviewer attention because of its size.",
}

VERDICT_WORDS = {
    "accept": "was accepted and posted",
    "quarantine": "is on hold until someone reviews it",
    "reject": "was rejected and was not posted",
}


def template_explanation(entry_id: str, description: str, decision: str,
                         findings: List[Finding]) -> str:
    parts = [f"{entry_id} ({description}) {VERDICT_WORDS[decision]}."]
    for f in findings:
        parts.append(f"- {f.message[0].upper()}{f.message[1:]}.")
        step = NEXT_STEP.get(f.code)
        if step:
            parts.append(f"  What to do: {step}")
        if f.facts.get("suggestions"):
            parts.append("  Possible accounts: " + "; ".join(f.facts["suggestions"]))
    return "\n".join(parts)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip("0").rstrip(".") for n in _NUM.findall(text)}


def _llm_explanation(entry_id, description, decision, findings) -> str:
    import anthropic  # optional dependency, only imported when used

    facts = "\n".join(f"- [{f.code}] {f.message} {f.facts}" for f in findings)
    prompt = (
        "You are writing a note to an accountant about one journal entry.\n"
        f"Entry: {entry_id} - {description}\n"
        f"Outcome (already decided, do not question it): {VERDICT_WORDS[decision]}\n"
        f"Findings:\n{facts}\n\n"
        "Write 2-4 short sentences in plain English: what is wrong, why it matters "
        "for the books, and what they should do next. Only use numbers that appear "
        "in the findings. No headings, no bullet points."
    )
    client = anthropic.Anthropic()
    msg = client.messages.create(model=MODEL, max_tokens=300,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


def explain(entry_id: str, description: str, decision: str,
            findings: List[Finding], use_llm: bool) -> dict:
    template = template_explanation(entry_id, description, decision, findings)
    if not use_llm or not findings:
        return {"text": template, "by": "template"}
    try:
        text = _llm_explanation(entry_id, description, decision, findings)
    except Exception as e:  # no key, no network, SDK missing - all fine
        return {"text": template, "by": "template", "llm_error": type(e).__name__}

    allowed = _numbers(template + " " + " ".join(str(f.facts) for f in findings) + entry_id)
    invented = _numbers(text) - allowed
    if invented:
        return {"text": template, "by": "template",
                "llm_rejected": f"mentioned numbers not in the findings: {sorted(invented)}"}
    return {"text": text, "by": MODEL, "template": template}
