from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.billing import CostSession
from shared.kb import all_articles_blob
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket


@dataclass
class TicketResolution:
    action: str
    kb_article: str
    customer_reply: str
    raw_completion: str


def parse_resolution(text: str) -> TicketResolution:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"No JSON in model output:\n{text[:400]}")
    data = json.loads(m.group())
    return TicketResolution(
        action=str(data["action"]).upper(),
        kb_article=str(data["kb_article"]),
        customer_reply=str(data.get("customer_reply", "")),
        raw_completion=text,
    )


class SupportCopilot:
    """
    ShopAssist Tier-1 copilot (optimized).

    Given a support ticket + order snapshot, choose an action, cite the help-center
    article, and draft the customer reply.
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)

    def build_messages(self, ticket_id: str) -> list[ChatMessage]:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])
        thread = format_thread(ticket)
        compact_snapshot = json.dumps(order, separators=(",", ":"))

        system = (
            "You are ShopAssist, a Tier-1 customer support copilot.\n"
            "Given the order and thread, resolve the ticket using policy.\n"
            "Output JSON with action, kb_article, customer_reply.\n\n"
            "HELP CENTER:\n" + all_articles_blob().strip()
        )
        user = (
            f"TICKET_ID: {ticket_id}\n"
            f"THREAD:\n{thread}\n"
            f"ORDER_SNAPSHOT:\n{compact_snapshot}\nEND_SNAPSHOT"
        )
        return [ChatMessage("system", system), ChatMessage("user", user)]

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        messages = self.build_messages(ticket_id)
        completion = self.llm.chat("handle_ticket", messages)
        return parse_resolution(completion)
