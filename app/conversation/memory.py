"""
Multi-Turn Conversation Memory — enables follow-up questions.

Maintains a sliding window of the last N query interactions per session,
injecting prior context into subsequent prompts so the user can say
things like "Now break that down by region" or "Show that as a bar chart".
"""

from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

from loguru import logger

from app.llm.prompts import CONVERSATION_CONTEXT_TEMPLATE


@dataclass
class QueryTurn:
    """A single query turn in the conversation."""
    question: str
    sql: str
    result_columns: list[str]
    result_row_count: int
    timestamp: datetime = field(default_factory=datetime.now)


class ConversationMemory:
    """
    Session-based conversation memory.

    Stores the last N turns per session and generates context strings
    for injection into subsequent prompts.
    """

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        # session_id → list of QueryTurn
        self._sessions: dict[str, list[QueryTurn]] = defaultdict(list)

    def add_turn(
        self,
        session_id: str,
        question: str,
        sql: str,
        result_columns: list[str],
        result_row_count: int,
    ) -> None:
        """Record a completed query turn."""
        turn = QueryTurn(
            question=question,
            sql=sql,
            result_columns=result_columns,
            result_row_count=result_row_count,
        )
        self._sessions[session_id].append(turn)

        # Trim to max_turns
        if len(self._sessions[session_id]) > self.max_turns:
            self._sessions[session_id] = self._sessions[session_id][-self.max_turns:]

        logger.debug(
            f"📝 Session {session_id[:8]}... — "
            f"{len(self._sessions[session_id])} turns stored"
        )

    def get_context(self, session_id: str) -> str:
        """
        Build a conversation context string for the current session.

        Returns an empty string if no prior turns exist.
        """
        turns = self._sessions.get(session_id, [])
        if not turns:
            return ""

        # Use the most recent turn for context
        last = turns[-1]

        context = CONVERSATION_CONTEXT_TEMPLATE.format(
            previous_question=last.question,
            previous_sql=last.sql,
            result_rows=last.result_row_count,
            result_columns=", ".join(last.result_columns),
        )

        # If multiple turns, add brief history summary
        if len(turns) > 1:
            history_lines = [
                f"  - \"{t.question}\" ({t.result_row_count} rows)"
                for t in turns[:-1]
            ]
            context += "Earlier questions in this session:\n" + "\n".join(history_lines) + "\n\n"

        return context

    def get_history(self, session_id: str) -> list[dict]:
        """Get query history for a session."""
        turns = self._sessions.get(session_id, [])
        return [
            {
                "question": t.question,
                "sql": t.sql,
                "result_columns": t.result_columns,
                "result_row_count": t.result_row_count,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in turns
        ]

    def clear_session(self, session_id: str) -> None:
        """Clear a session's history."""
        if session_id in self._sessions:
            del self._sessions[session_id]


# Singleton instance
conversation_memory = ConversationMemory()
