from dataclasses import dataclass, field


@dataclass
class SessionData:
    summary: str = ""
    messages: list = field(default_factory=list)


sessions: dict[str, SessionData] = {}


def get_or_create(session_id: str) -> SessionData:
    if session_id not in sessions:
        sessions[session_id] = SessionData()
    return sessions[session_id]


def add_message(session_id: str, role: str, content: str) -> None:
    get_or_create(session_id).messages.append({"role": role, "content": content})


def build_context(session_id: str) -> list[dict]:
    session = get_or_create(session_id)
    summary_line = f"\nConversation so far:\n{session.summary}" if session.summary else ""
    system = {
        "role": "system",
        "content": (
            "You are a helpful conversational AI assistant. "
            "Speak naturally and be concise unless detail is asked for. "
            "Stay consistent and maintain the flow of conversation."
            + summary_line
        ),
    }
    # Last 8 messages only — keeps context tight for a 13B model
    return [system] + session.messages[-8:]


def should_summarize(session_id: str, threshold: int) -> bool:
    return len(get_or_create(session_id).messages) > threshold


def pop_old_messages(session_id: str, keep_recent: int) -> list[dict]:
    """Remove and return the oldest messages, leaving only keep_recent."""
    session = get_or_create(session_id)
    old = session.messages[:-keep_recent]
    session.messages = session.messages[-keep_recent:]
    return old


def apply_summary(session_id: str, summary: str) -> None:
    get_or_create(session_id).summary = summary
