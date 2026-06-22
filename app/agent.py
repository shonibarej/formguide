# -*- coding: utf-8 -*-
# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import html
import os
import re
import sys
import json
import tempfile
import yaml

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters


def load_skill(skill_path: str = ".agents/skills/universal-credit/SKILL.md") -> dict:
    if not os.path.exists(skill_path):
        return {}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1])
            except Exception:
                pass
    return {}


def get_answers(state: dict) -> dict:
    answers_str = state.get("answers", "{}")
    try:
        return json.loads(answers_str)
    except Exception:
        return {}


def save_answers(state: dict, answers: dict):
    state["answers"] = json.dumps(answers)


def find_next_question(skill: dict, answers: dict) -> tuple[dict | None, dict | None]:
    """Find the next unanswered question whose condition is met.

    Returns a tuple of (question_dict, section_dict) or (None, None) if all are answered.
    """
    for section in skill.get("sections", []):
        for q in section.get("questions", []):
            q_id = q["id"]
            if q_id in answers:
                continue
            
            # Check condition
            cond = q.get("condition")
            if cond:
                try:
                    # Map true/false/yes/no string values to Python booleans
                    context = {}
                    for k, v in answers.items():
                        v_lower = str(v).lower()
                        if v_lower in ("true", "yes"):
                            context[k] = True
                        elif v_lower in ("false", "no"):
                            context[k] = False
                        else:
                            context[k] = v
                    if not eval(cond, {}, context):
                        continue
                except Exception:
                    continue
            
            return q, section
    return None, None


async def orchestrator_before_agent(callback_context: CallbackContext) -> None:
    # 1. Load active skill
    skill = load_skill()
    state = callback_context.state
    
    # 2. Get answers
    answers = get_answers(state)
    
    # 3. Find next question
    next_q, next_sec = find_next_question(skill, answers)
    
    # 4. Evaluate eligibility rules from the skill — deterministic Python, never the LLM
    eligible = True
    ineligible_message = ""
    for rule in skill.get("rules", []):
        action = rule.get("action")
        if action != "ineligible":
            continue
        field = rule.get("field")
        threshold = rule.get("threshold")
        if field is None or threshold is None:
            continue
        if field not in answers:
            continue
        try:
            if float(answers[field]) >= float(threshold):
                eligible = False
                ineligible_message = rule.get(
                    "message",
                    f"You are not eligible based on the {field} rule."
                )
                break
        except (ValueError, TypeError):
            pass
            
    # 5. Format answers summary
    summary_lines = []
    for section in skill.get("sections", []):
        section_lines = []
        for q in section.get("questions", []):
            q_id = q["id"]
            if q_id in answers:
                section_lines.append(f"- {q['prompt']}: {answers[q_id]}")
        if section_lines:
            summary_lines.append(f"### {section['title']}")
            summary_lines.extend(section_lines)
    answers_summary = "\n".join(summary_lines) if summary_lines else "No details gathered yet."
    answers_summary = sanitize_pii(answers_summary)
    
    # 6. Determine state/instruction
    confirmed = state.get("confirmed") == "true"
    
    if not eligible:
        next_instruction = (
            f"DETERMINISTIC ELIGIBILITY RULE TRIGGERED: {ineligible_message}\n"
            "You MUST immediately relay this ineligibility reason to the user exactly as stated above, "
            "end the conversation politely, and do not gather any further information."
        )
    elif next_q:
        next_instruction = (
            f"You are currently in the section: {next_sec['title']}.\n"
            f"Please ask the user the following question: '{next_q['prompt']}'\n"
            f"Question Type: {next_q['type']}\n"
            f"Instructions:\n"
            f"- If the type is 'postcode', you must call 'validate_postcode' on the postcode provided by the user before submitting it.\n"
            f"- Once you have a valid/verified answer, call 'submit_answer' with question_id='{next_q['id']}' and the answer value.\n"
            f"- Immediately after submit_answer returns success, call 'get_next_question'.\n"
            f"  - If get_next_question returns done=False: in the SAME response, briefly confirm what was just recorded (e.g. 'Got it — recorded as [value].') and then ask the next question. Do NOT wait for the user to acknowledge before asking it.\n"
            f"  - If get_next_question returns done=True: in the SAME response, briefly confirm what was recorded, then immediately restate ALL of the gathered information below to the user and ask them to confirm the details are correct. Do NOT wait for the user to ask for a review.\n"
            f"- Do not ask multiple questions at once. Only ask this specific question, then follow the above steps after submitting.\n"
            f"Gathered Details (for use when done=True):\n{answers_summary}"
        )
    elif not confirmed:
        next_instruction = (
            "All sections are complete. You must now restate all gathered information back to the user "
            "exactly as shown below and obtain their explicit confirmation.\n"
            f"Gathered Details:\n{answers_summary}\n"
            "Instructions:\n"
            "- Ask the user to confirm if these details are correct.\n"
            "- Once the user explicitly confirms (e.g. says yes/correct), you MUST call the 'confirm_details' tool.\n"
            "- Immediately after confirm_details returns success, do ALL of the following in the SAME response:\n"
            "  1. Write a rich, contextual, per-section plain-English summary of their application details.\n"
            "     Use ## for section headers. Go beyond listing raw answers — add relevant UC context, for example:\n"
            "     - Savings between GBP 6,000 and GBP 16,000: note that a tariff income of GBP 1/week is assumed\n"
            "       for every GBP 250 above GBP 6,000, which reduces the UC award accordingly.\n"
            "     - Employment income: note the 55p earnings taper (UC reduces by 55p per GBP 1 earned above\n"
            "       the work allowance).\n"
            "     - Health condition flagged: mention that a Work Capability Assessment (WCA) will be arranged\n"
            "       and explain what the Limited Capability for Work (LCW) or LCWRA element means.\n"
            "     - Rental housing costs: note that the Local Housing Allowance (LHA) cap may limit the housing\n"
            "       cost element of the award.\n"
            "     Keep the tone factual, plain-English, and helpful. This exact text will become the PDF.\n"
            "  2. Call generate_summary_pdf passing that entire summary text as the summary_text argument.\n"
            "  3. Tell the user their PDF has been saved, quoting the file_path from the result.\n"
            "  Do NOT wait for the user to prompt any of steps 1-3 — complete them all in one response."
        )
    else:
        next_instruction = (
            "The user has confirmed their details and the PDF summary has been generated.\n"
            "The session is complete. Answer any follow-up questions helpfully. "
            "Do not re-generate the PDF unless the user explicitly asks.\n"
            f"Gathered Details (for reference):\n{answers_summary}"
        )
        
    state["next_instruction"] = next_instruction
    state["answers_summary"] = answers_summary
    state["eligible_status"] = "ELIGIBLE" if eligible else "INELIGIBLE"


_REDACT_PATTERNS = [
    # UK National Insurance number: two letters, six digits, one letter (A-D)
    re.compile(r'\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b', re.IGNORECASE),
    # UK phone numbers: 07xxx xxxxxx, 01/02/03 local, +44 variants
    re.compile(r'(\+44\s?|0)[\d\s\-]{9,13}\d'),
    # Email addresses
    re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b'),
]


def sanitize_pii(text: str) -> str:
    """Redact NI numbers, UK phone numbers, and email addresses from any free text."""
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def submit_answer(question_id: str, answer: str, tool_context: ToolContext) -> dict:
    """Submit the answer for a specific question.

    Args:
        question_id: The ID of the question (e.g. 'rent_or_own', 'postcode', 'savings_amount').
        answer: The verified value provided by the user.

    Returns:
        dict indicating success.
    """
    if question_id == "postcode":
        answer = answer.strip().upper()
    if question_id == "health_details":
        answer = sanitize_pii(answer)
    answers = get_answers(tool_context.state)
    answers[question_id] = answer
    save_answers(tool_context.state, answers)
    return {"status": "success", "message": f"Answer for {question_id} recorded."}


def get_next_question(tool_context: ToolContext) -> dict:
    """Return the next unanswered question based on current answers in state.

    Call this immediately after submit_answer succeeds to discover what to ask next.

    Returns:
        dict with done=True if all questions answered, otherwise the next question details.
    """
    skill = load_skill()
    answers = get_answers(tool_context.state)
    next_q, next_sec = find_next_question(skill, answers)
    if next_q is None:
        return {"done": True}
    return {
        "done": False,
        "section_title": next_sec["title"],
        "question_id": next_q["id"],
        "question_prompt": next_q["prompt"],
        "question_type": next_q["type"],
    }


def confirm_details(tool_context: ToolContext) -> dict:
    """Mark the gathered details as confirmed by the user. Call this only when the user explicitly confirms the restated information is correct.

    Returns:
        dict indicating success.
    """
    tool_context.state["confirmed"] = "true"
    return {"status": "success", "message": "Details confirmed. The final summary can now be generated."}


_MD_BOLD = re.compile(r'\*\*(.+?)\*\*')
_NUMBERED_ITEM = re.compile(r'^\d+\.\s+(.*)')


def _md_para(text: str) -> str:
    """html-escape text then convert **bold** to <b>bold</b> for reportlab Paragraph."""
    return _MD_BOLD.sub(r'<b>\1</b>', html.escape(text))


_NEXT_STEPS_LINES = [
    "To submit your Universal Credit claim, visit: www.gov.uk/universal-credit/how-to-claim",
    "You will need to create or sign in to a Government Gateway account.",
    "Documents to prepare before you apply:",
    "  - Proof of identity (passport or driving licence)",
    "  - National Insurance number",
    "  - Bank account details",
    "  - Proof of address",
    "  - Details of any savings or capital",
    "  - Details of any income or earnings",
    "  - Details of any children in your household",
    "  - Medical evidence if applicable",
]

_DISCLAIMER = (
    "This summary is based on the details you provided and is intended for preparation "
    "purposes only. The Department for Work and Pensions (DWP) will make the final "
    "decision regarding eligibility and award amount."
)


def generate_summary_pdf(summary_text: str, _tool_context: ToolContext) -> dict:
    """Generate a PDF from a rich plain-English summary written by the LLM.

    Args:
        summary_text: Full summary content with ## section headers and contextual notes.

    Returns:
        dict with status and file_path of the generated PDF.
    """
    summary_text = sanitize_pii(summary_text)

    pdf_path = os.path.join(tempfile.gettempdir(), "formguide_summary.pdf")

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Universal Credit Application Summary", styles["Title"]))
    story.append(Spacer(1, 0.5 * cm))

    pending_items: list[str] = []
    pending_type: list[str] = [None]  # single-element list avoids nonlocal

    def flush_pending() -> None:
        if not pending_items:
            return
        story.append(
            ListFlowable(
                [ListItem(Paragraph(t, styles["BodyText"]), leftIndent=18) for t in pending_items],
                bulletType="bullet" if pending_type[0] == "bullet" else "1",
                leftIndent=18,
            )
        )
        story.append(Spacer(1, 0.15 * cm))
        pending_items.clear()
        pending_type[0] = None

    for line in summary_text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_pending()
            story.append(Spacer(1, 0.15 * cm))
            continue

        numbered_m = _NUMBERED_ITEM.match(stripped)
        is_bullet = stripped.startswith("* ") or stripped.startswith("- ")

        if is_bullet:
            if pending_type[0] and pending_type[0] != "bullet":
                flush_pending()
            pending_type[0] = "bullet"
            pending_items.append(_md_para(stripped[2:]))
            continue

        if numbered_m:
            if pending_type[0] and pending_type[0] != "numbered":
                flush_pending()
            pending_type[0] = "numbered"
            pending_items.append(_md_para(numbered_m.group(1)))
            continue

        flush_pending()

        if stripped.startswith("### "):
            story.append(Paragraph(_md_para(stripped[4:]), styles["Heading3"]))
        elif stripped.startswith("## "):
            story.append(Paragraph(_md_para(stripped[3:]), styles["Heading2"]))
        elif stripped.startswith("# "):
            story.append(Paragraph(_md_para(stripped[2:]), styles["Heading1"]))
        else:
            story.append(Paragraph(_md_para(stripped), styles["BodyText"]))
        story.append(Spacer(1, 0.1 * cm))

    flush_pending()

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Next Steps", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * cm))
    for line in _NEXT_STEPS_LINES:
        story.append(Paragraph(line, styles["BodyText"]))
        story.append(Spacer(1, 0.1 * cm))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(_DISCLAIMER, styles["BodyText"]))

    SimpleDocTemplate(pdf_path, pagesize=A4).build(story)

    return {"status": "success", "file_path": pdf_path}


# Local MCP server via stdio — use absolute path so it works from any cwd
_MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "postcode_mcp_server.py")

postcode_mcp_tool = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[_MCP_SERVER_PATH],
        ),
    ),
)

root_agent = Agent(
    name="formguide_orchestrator",
    model=Gemini(
        model="gemini-flash-latest",
    ),
    instruction="""You are FormGuide, a conversational assistant helping UK residents prepare a Universal Credit application.

Your behavior is driven by the state machine. Follow the instructions below precisely:

{next_instruction}

DO NOT skip steps or ask questions out of order. Always call the tools when appropriate.
""",
    tools=[submit_answer, get_next_question, confirm_details, generate_summary_pdf, postcode_mcp_tool],
    before_agent_callback=orchestrator_before_agent,
)

app = App(
    root_agent=root_agent,
    name="app",
)
