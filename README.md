# FormGuide: A Conversational Preparation Assistant for Universal Credit

A conversational AI agent that helps UK residents prepare a Universal Credit application — gathering the right information in plain English, validating it, and producing a clean reference document to use on the official GOV.UK application.

Built for the **5-Day AI Agents: Intensive Vibe Coding Course with Google** capstone (Concierge Agents track).

## The problem

Universal Credit's online application asks dense, jargon-heavy questions across multiple sections (housing, income, savings, childcare, health), with conditional logic that's easy to get wrong, and a hard eligibility cliff-edge (£16,000 in savings) that can derail an application halfway through if discovered too late. For people with limited literacy, low confidence with bureaucratic systems, or simply a stressful financial situation, this creates a real barrier to claiming support they're entitled to.

FormGuide doesn't replace the official application — it prepares the applicant for it, conversationally, in plain English, and flags issues before they reach GOV.UK.

## What it does

1. Asks the real Universal Credit question set, one question at a time, in natural conversation
2. Validates UK postcodes against a live external data source before accepting them
3. Checks the £16,000 savings eligibility threshold deterministically — never an LLM guess
4. Restates everything gathered and requires explicit user confirmation before producing any output
5. Generates a structured, plain-English PDF summary document, with contextual guidance (e.g. earnings taper rate, Local Housing Allowance caps, Work Capability Assessment outcomes) added per section

## Architecture


<img width="2800" height="3040" alt="formguide_architecture_v2" src="https://github.com/user-attachments/assets/ffcfac78-19eb-42cf-87d5-544f7415570e" />

### Why this design

- **Skills carry domain knowledge, the orchestrator stays generic.** `universal-credit/SKILL.md` declares the question sections, conditional logic, and the eligibility rule. The orchestrator never hardcodes anything Universal-Credit-specific — adding a second form (e.g. PIP) would mean writing a new skill, not touching `agent.py`.
- **Hard rules are checked in code, never inferred.** The £16,000 savings threshold is read from the skill's declared `rules` section and checked deterministically in `orchestrator_before_agent`, so the LLM is never asked to judge eligibility itself.
- **The conversational flow is a verified state machine, not free-form chat.** Every turn, Python decides what should happen next (ask the next question, halt for ineligibility, present the declaration, or generate the summary) and hands the LLM a precise instruction — rather than relying on the model to remember where it is in a long conversation.
- **Data minimization by design.** FormGuide never asks for a name, date of birth, National Insurance number, or bank details — fields the real GOV.UK application requires but this preparation tool doesn't need. The one free-text field (health condition description) is sanitized for accidentally-included NI numbers, phone numbers, or emails before being stored or shown back, as a defense-in-depth safeguard.
- **No data persistence.** All information exists only in the active session's memory. Nothing is written to disk except the final PDF generated for the user.

## Key concepts demonstrated

| Concept | Where |
|---|---|
| Agent / ADK | `app/agent.py` — ADK 2.0 graph-based agent with a deterministic `before_agent_callback` state machine |
| MCP Server | `app/postcode_mcp_server.py` — custom MCP server wrapping the postcodes.io API, wired via `McpToolset` |
| Antigravity | Entire project built and debugged in Antigravity IDE / CLI |
| Security features | Deterministic eligibility gate, data minimization, PII sanitization (input + output), explicit confirmation gate before any output is generated |
| Agent skills | `.agents/skills/universal-credit/SKILL.md` — declarative question structure, conditional logic, and eligibility rules, loaded dynamically at runtime |

Deployability was deliberately scoped out given submission timeline constraints — see [Limitations](#limitations) below. Local testing in ADK's web playground was prioritized instead, alongside this documentation and the demo video.

## Setup

**Requirements:** Python 3.11–3.13, a Gemini API key from [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

```bash
git clone <this-repo-url>
cd formguide
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt  # or: uv sync

# Set your API key
$env:GEMINI_API_KEY = "your-key-here"      # PowerShell
$env:GOOGLE_API_KEY = "your-key-here"      # also required by the underlying SDK
```

```bash
adk web
```

Open the printed local URL, select **app**, and start a session with:

> *"I need help with my Universal Credit application."*

## Testing performed

- **Happy path:** full conversation, all four sections, eligible savings amount, confirmation, PDF generated correctly
- **Ineligibility path:** savings entered above £16,000 — conversation correctly halts immediately with the rule-driven message, no further questions asked
- **Conditional logic:** `housing_costs` only asked when renting/mortgaging; `health_details` only asked when a health condition is declared
- **MCP tool verification:** postcode validated via live API call before being recorded (confirmed in ADK's Events/Traces panel)
- **PII handling:** a user volunteering an NI number outside its intended field was correctly declined and re-prompted; sanitization also applied as a defense-in-depth layer on the final summary text

## Limitations

- **Not deployed to a live public endpoint.** Tested thoroughly in ADK's local web playground; a `Dockerfile` and Cloud Run-ready FastAPI entry point (`app/fast_api_app.py`) are included and scaffolded correctly, but an actual deployment was scoped out given submission timeline constraints. ADK's local playground demo is shown in full in the accompanying video.
- **Testing was manual, not automated.** The eligibility paths, conditional logic, MCP tool firing, and PII handling were all verified through direct, repeated manual testing in the ADK web playground rather than an automated evaluation harness.
- **Conversational, not authenticated.** FormGuide does not log into GOV.UK or submit anything on the user's behalf — it produces a preparation document the user reviews and uses themselves, by design (see Architecture).
- **Single form.** Only Universal Credit is implemented. The architecture is designed to support additional UK government forms as new skills without changing the orchestrator, but no second form has been built yet.
- **Postcode data source.** Validation uses the open-data postcodes.io API. For full address-line lookup at production scale, a licensed dataset (e.g. Royal Mail) would be more complete.

## Future extensions

- Additional UK government forms (PIP, Council Tax Support) as new skills, reusing the existing orchestrator
- Cloud Run deployment for a publicly accessible instance
- A lightweight semantic validation layer (a second LLM check on *why* an action was taken, not just whether it was structurally valid) alongside the existing deterministic checks

## Course concepts applied

Built across the 5-Day AI Agents: Intensive Vibe Coding Course — vibe-coded in Antigravity (Day 1), MCP tool integration (Day 2), agent skills and progressive disclosure (Day 3), security guardrails and deterministic validation (Day 4), and spec-driven development practices (Day 5).
