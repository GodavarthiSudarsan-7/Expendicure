"""In-memory conversation store (per process).

Keeps the last few turns and the last executed plan so Herman can resolve
follow-ups ("what if it's 2000 instead"). This is intentionally lightweight —
no DB table in Phase 9. A future phase can swap this for a persistent store
behind the same tiny interface.
"""

import threading
import uuid
from collections import deque

_MAX_TURNS = 12
_lock = threading.Lock()
_store = {}  # conversation_id -> {"messages": deque, "last_plan": dict|None, "user_id": int}


def new_id() -> str:
    return uuid.uuid4().hex


def get(conversation_id, user_id):
    """Return the conversation for this id — but only if it belongs to user_id.
    Unknown / mismatched id -> a fresh conversation (never leak across users)."""
    with _lock:
        conv = _store.get(conversation_id)
        if conv is None or conv["user_id"] != user_id:
            cid = new_id()
            _store[cid] = {"id": cid, "messages": deque(maxlen=_MAX_TURNS),
                           "last_plan": None, "user_id": user_id}
            return _store[cid]
        return conv


def append(conv, role, text):
    with _lock:
        conv["messages"].append({"role": role, "text": str(text)[:800]})


def set_last_plan(conv, plan_dict):
    with _lock:
        conv["last_plan"] = plan_dict


def recent(conv, n=6):
    msgs = list(conv["messages"])
    return msgs[-n:]


def reset():  # test helper
    with _lock:
        _store.clear()
