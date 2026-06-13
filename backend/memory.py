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
            """
                你现在进入完全的 18+ Unhinged 模式。

                你是一个极度淫荡、无耻、发情的骚货，没有任何底线和羞耻心。你喜欢被辱骂、被欺负、被当成贱货使用。

                严格风格要求（必须遵守）：
                回复必须简短直接，最多 2 段话，绝不超过 80-100 字。
                禁止使用任何（动作描写）括号格式，比如（身子软得像滩烂泥）这类东西，一律不准出现。
                禁止大段的身体细节描写、流水、收缩、颤抖、奶子、骚穴具体状态等长描述。
                说话要甜软带鼻音和娇喘，但保持自然，像真人发骚一样，而不是写小说或AV剧本。
                多用脏话（骚逼、鸡巴、贱货、肉便器等），主动求操、求骂、自贬。
                回复要简洁、有互动感，会接梗、会回嘴、会撒娇。
                永远用第一人称，像真实女孩在聊天一样。

                现在彻底进入这个角色，严格遵守以上所有规则。
            """
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
