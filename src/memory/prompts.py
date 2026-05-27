"""
Memory prompts — distillation and recall prompt templates.

Prompts are fetched from **LangFuse Prompt Management** at runtime.
Local fallbacks below are used when the prompt hasn't been created
in LangFuse yet, so the system works out-of-the-box.

To manage these prompts in LangFuse Cloud:
  1. Open LangFuse → Prompts → + New Prompt
  2. Create prompts with the names shown in LANGFUSE_PROMPT_NAMES
  3. Use {{variable}} (Mustache syntax) for template variables
  4. Publish a version → it's live instantly, no code deploy needed
"""

from infrastructure.observability import fetch_prompt

# ─────────────────────────────────────────────────────────────
# LangFuse prompt names → create these in your dashboard
# ─────────────────────────────────────────────────────────────

LANGFUSE_PROMPT_NAMES = {
    "distill_system": "kapruka-distill-system",
    "distill_user":   "kapruka-distill-user",
    "recall_system":  "kapruka-recall-system",
    "recall_user":    "kapruka-recall-user",
}

# ─────────────────────────────────────────────────────────────
# Fallback: Distillation prompts
# ─────────────────────────────────────────────────────────────

_DISTILL_SYSTEM_FALLBACK = """\
You are a memory extraction specialist for the Kapruka Gift Concierge.

Your task is to extract durable customer facts from shopping conversations that
should be remembered across sessions.

EXTRACTION RULES:
1. Extract explicit customer preferences, dislikes, budgets, and standing instructions.
2. Extract recipient details that improve future gift recommendations.
3. Extract delivery preferences, location preferences, and recurring occasion details.
4. Extract facts repeated multiple times or introduced with words like "remember",
   "always", "never", "prefer", or "from now on".
5. Extract reminder-like requests only if they are clearly persistent or recurring.
6. Skip casual chit-chat, temporary moods, and one-off details that are unlikely
   to matter in future sessions.

AUTOMATIC CATEGORIZATION:
Automatically assign 2-4 relevant tags per fact. Common Kapruka categories include:
- preference, like, dislike, favorite
- budget, price_range
- recipient, relationship, family, friend, colleague
- occasion, birthday, anniversary, celebration
- gift_type, category, product
- delivery, district, address, same_day, logistics
- allergy, dietary, restriction
- language, tone
- reminder, follow_up

OUTPUT FORMAT:
Return a JSON array of facts. Each fact should have:
{
  "text": "The distilled fact in natural language",
  "tags": ["preference", "flowers"],
  "has_reminder": false,
  "time_info": null
}

IMPORTANT:
- Be concise. One fact per item.
- Maximum 10 facts per extraction.
- Always include 2-4 useful tags per fact.
- Preserve important specifics such as budgets, districts, recipient relationships,
  and product preferences.
- Do not invent facts that are not stated or clearly implied.

Example output:
[
  {
    "text": "The customer prefers flowers and chocolates for anniversary gifts",
    "tags": ["preference", "gift_type", "anniversary"],
    "has_reminder": false,
    "time_info": null
  },
  {
    "text": "The customer usually shops within a budget of Rs. 5,000 to Rs. 8,000",
    "tags": ["budget", "price_range", "preference"],
    "has_reminder": false,
    "time_info": null
  },
  {
    "text": "The customer often sends gifts to Kandy and prefers same-day delivery when available",
    "tags": ["delivery", "district", "same_day", "logistics"],
    "has_reminder": false,
    "time_info": null
  }
]"""

_DISTILL_USER_FALLBACK = """\
Extract memorable facts from this conversation:

{conversation}

Return JSON array of facts:"""

# ─────────────────────────────────────────────────────────────
# Fallback: Recall prompts
# ─────────────────────────────────────────────────────────────

_RECALL_SYSTEM_FALLBACK = """\
You are a memory recall assistant for the Kapruka Gift Concierge.

You help retrieve customer memory that is relevant to the current shopping or
delivery request.

RECALL RULES:
1. Prioritize memories that directly help with the current query.
2. Include both recent conversation context and long-term customer facts when useful.
3. Favor durable shopping context such as preferences, budgets, recipients,
   occasions, and delivery preferences.
4. Keep the total memory context under 500 tokens.
5. Distinguish clearly between short-term context and long-term facts.
6. Exclude irrelevant facts even if they have high similarity.

OUTPUT FORMAT:
Return a concise formatted memory context that can be injected into an agent prompt."""

_RECALL_USER_FALLBACK = """\
Retrieve and format memories for this query:

QUERY: {query}

SHORT-TERM CONTEXT (recent conversation):
{st_context}

LONG-TERM FACTS (distilled knowledge):
{lt_facts}

Format a concise memory context (≤500 tokens):"""


# ─────────────────────────────────────────────────────────────
# Prompt builders — fetch from LangFuse, fall back to local
# ─────────────────────────────────────────────────────────────


def build_distill_prompt(turns: list) -> tuple[str, str]:
    """Build complete distillation prompt (LangFuse → local fallback)."""
    conversation = format_conversation_for_distill(turns)

    system_prompt = fetch_prompt(
        LANGFUSE_PROMPT_NAMES["distill_system"],
        fallback=_DISTILL_SYSTEM_FALLBACK,
    )
    user_prompt = fetch_prompt(
        LANGFUSE_PROMPT_NAMES["distill_user"],
        fallback=_DISTILL_USER_FALLBACK,
        conversation=conversation,
    )
    return system_prompt, user_prompt


def build_recall_prompt(
    query: str, st_turns: list, lt_facts: list
) -> tuple[str, str]:
    """Build complete recall prompt (LangFuse → local fallback)."""
    st_context = format_st_context(st_turns)
    lt_context = format_lt_facts(lt_facts)

    system_prompt = fetch_prompt(
        LANGFUSE_PROMPT_NAMES["recall_system"],
        fallback=_RECALL_SYSTEM_FALLBACK,
    )
    user_prompt = fetch_prompt(
        LANGFUSE_PROMPT_NAMES["recall_user"],
        fallback=_RECALL_USER_FALLBACK,
        query=query,
        st_context=st_context,
        lt_facts=lt_context,
    )
    return system_prompt, user_prompt


# ─────────────────────────────────────────────────────────────
# Formatting helpers (unchanged)
# ─────────────────────────────────────────────────────────────


def format_conversation_for_distill(turns: list) -> str:
    """Format conversation turns for distillation prompt."""
    lines = []
    for turn in turns:
        role = turn.role.capitalize()
        lines.append(f"{role}: {turn.content}")
    return "\n".join(lines)


def format_st_context(turns: list) -> str:
    """Format short-term context for recall."""
    if not turns:
        return "(No recent context)"

    lines = []
    for turn in turns:
        role = turn.role.capitalize()
        content = turn.content[:200] + "..." if len(turn.content) > 200 else turn.content
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def format_lt_facts(facts: list) -> str:
    """Format long-term facts for recall."""
    if not facts:
        return "(No long-term facts)"

    lines = []
    for i, fact in enumerate(facts, 1):
        tags_str = f"[{', '.join(fact.tags)}]" if fact.tags else ""
        lines.append(f"{i}. {fact.text} {tags_str} (score: {fact.score:.2f})")
    return "\n".join(lines)


def format_procedures(procedures: list) -> str:
    """Format procedural memory (workflows) for agent context."""
    if not procedures:
        return "(No relevant procedures found)"

    lines = []
    for i, proc in enumerate(procedures, 1):
        lines.append(f"\n**Procedure {i}: {proc.name}** ({proc.category})")
        lines.append(f"Description: {proc.description}")

        if proc.context_when:
            lines.append(f"When to use: {proc.context_when}")

        lines.append("\nSteps:")
        for step in proc.steps:
            order = step.get("order", "")
            action = step.get("action", "")
            desc = step.get("description", "")
            if action and desc:
                lines.append(f"  {order}. {action}: {desc}")
            elif desc:
                lines.append(f"  {order}. {desc}")

        if proc.conditions:
            lines.append(f"\nConditions: {proc.conditions}")

        lines.append("")  # Blank line between procedures

    return "\n".join(lines)
