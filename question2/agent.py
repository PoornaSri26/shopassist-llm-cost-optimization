from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import article_ids, load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

from question1.agent import parse_resolution


@dataclass
class TicketResolution:
    action: str
    kb_article: str


def _triage_code(ticket: dict, order: dict, thread: str) -> str:
    """Deterministic summary of ticket facts in code (zero LLM calls)."""
    ptype = order.get("product_type", "unknown")
    facts = [
        f"product_type: {ptype}",
        f"delivered_days_ago: {order.get('delivered_days_ago')}",
        f"subscription_age_days: {order.get('subscription_age_days')}",
        f"opened: {order.get('opened')}",
        f"license_revealed: {order.get('license_revealed')}",
        f"customized: {order.get('customized')}",
        f"damage_reported: {order.get('damage_reported')}",
    ]
    return f"FACTS:\n" + "\n".join(facts) + f"\nCUSTOMER_THREAD:\n{thread}"


def _retrieve_articles_code(order: dict, thread: str) -> list[tuple[str, str]]:
    """
    Code-based retrieval: rank articles by keyword overlap and domain signals.
    Loads only relevant articles, avoiding the 210k-token expanded blob.
    """
    all_ids = article_ids()
    scores: dict[str, float] = {aid: 0.0 for aid in all_ids}
    thread_lower = thread.lower()

    # Domain signal boosts
    ptype = order.get("product_type")
    if ptype == "subscription" or "subscription" in thread_lower or "cancel" in thread_lower:
        scores["subscription-cooling-off"] = scores.get("subscription-cooling-off", 0.0) + 15.0

    if order.get("license_revealed") or "license" in thread_lower or "digital" in thread_lower or "ebook" in thread_lower:
        scores["digital-license-no-refund"] = scores.get("digital-license-no-refund", 0.0) + 12.0

    if order.get("customized") or "custom" in thread_lower or "engrav" in thread_lower:
        scores["custom-items-no-replace"] = scores.get("custom-items-no-replace", 0.0) + 12.0

    if order.get("damage_reported") or "damaged" in thread_lower or "cracked" in thread_lower or "broken" in thread_lower or "replacement" in thread_lower or "replace" in thread_lower:
        scores["damage-replacement-7-days"] = scores.get("damage-replacement-7-days", 0.0) + 10.0

    if "refund" in thread_lower or "return" in thread_lower or ptype == "physical":
        scores["returns-within-30-days"] = scores.get("returns-within-30-days", 0.0) + 5.0

    # Keyword overlap
    for aid in all_ids:
        text = load_article(aid).lower()
        words = re.findall(r"\w+", text)
        for w in set(words):
            if len(w) > 3 and w in thread_lower:
                scores[aid] += 1.0

    # Sort descending and take top 2
    sorted_articles = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_ids = [aid for aid, score in sorted_articles[:2]]
    return [(aid, load_article(aid)) for aid in top_ids]


class SupportPipeline:
    """
    Refactored production pipeline:
    - triage (code)
    - retrieve (code)
    - compose (single lean LLM decision call)
    - audit (code validation)
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = format_thread(ticket)
        compact_snapshot = json.dumps(order, separators=(",", ":"))

        # Node 1: Triage (Code)
        triage_summary = _triage_code(ticket, order, thread)

        # Node 2: Retrieve (Code)
        retrieved = _retrieve_articles_code(order, thread)
        retrieved_blob = "\n\n".join(f"--- {aid} ---\n{body}" for aid, body in retrieved)

        # Node 3: Compose (LLM)
        messages = [
            ChatMessage(
                "system",
                "You are ShopAssist support copilot. Determine ticket resolution.\n"
                "Output JSON with action, kb_article, customer_reply.\n\n"
                f"RELEVANT KNOWLEDGE ARTICLES:\n{retrieved_blob}",
            ),
            ChatMessage(
                "user",
                f"TICKET: {ticket_id}\n"
                f"TRIAGE:\n{triage_summary}\n"
                f"ORDER_SNAPSHOT:\n{compact_snapshot}\nEND_SNAPSHOT",
            ),
        ]
        completion = self.llm.chat("compose", messages)
        parsed = parse_resolution(completion)

        # Node 4: Audit (Code Validation)
        action = parsed.action
        kb_article = parsed.kb_article
        valid_actions = {"REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2"}
        top_retrieved_id = retrieved[0][0] if retrieved else "returns-within-30-days"

        if action not in valid_actions or kb_article not in article_ids():
            # Safer fallback: escalate to Tier-2 citing the top retrieved context article
            action = "ESCALATE_TIER2"
            kb_article = top_retrieved_id

        return TicketResolution(action, kb_article)
