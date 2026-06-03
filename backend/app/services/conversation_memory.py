from collections import defaultdict, deque
from collections.abc import Iterable
from threading import Lock


class ConversationMemory:
    def __init__(self, max_turns: int = 10) -> None:
        self.max_messages = max_turns * 2
        self._items: defaultdict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=self.max_messages)
        )
        self._versions: defaultdict[str, int] = defaultdict(int)
        self._lock = Lock()

    def get(self, session_id: str) -> list[dict[str, str]]:
        with self._lock:
            return list(self._items[session_id])

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._items.pop(session_id, None)
            self._versions[session_id] += 1

    def version(self, session_id: str) -> int:
        with self._lock:
            return self._versions[session_id]

    def append_turn(self, session_id: str, user_content: str, assistant_content: str) -> None:
        self.append_messages(
            session_id,
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ],
        )

    def append_turn_if_version(
        self,
        session_id: str,
        version: int,
        user_content: str,
        assistant_content: str,
    ) -> bool:
        with self._lock:
            if self._versions[session_id] != version:
                return False
        self.append_turn(session_id, user_content, assistant_content)
        return True

    def append_messages(self, session_id: str, messages: Iterable[dict[str, str]]) -> None:
        with self._lock:
            bucket = self._items[session_id]
            for message in messages:
                role = message.get("role")
                content = str(message.get("content", "")).strip()
                if role in {"user", "assistant"} and content:
                    bucket.append({"role": role, "content": content})


_prd_memory = ConversationMemory(max_turns=10)


def get_prd_memory() -> ConversationMemory:
    return _prd_memory
