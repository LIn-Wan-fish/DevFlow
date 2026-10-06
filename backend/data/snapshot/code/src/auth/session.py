"""会话生命周期:签发、续期、失效。"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("auth.session")

DEFAULT_TTL = 3600


@dataclass
class Session:
    user_id: int
    token: str
    refresh: str
    ttl: int = DEFAULT_TTL
    issued_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() > self.issued_at + self.ttl


class SessionStore:
    def __init__(self) -> None:
        self._by_token: dict[str, Session] = {}

    def create(self, user_id: int) -> Session:
        session = Session(user_id=user_id, token=f"t-{user_id}-{int(time.time())}",
                          refresh=f"r-{user_id}-{int(time.time())}")
        self._by_token[session.token] = session
        return session

    def refresh(self, token: str) -> dict:
        session = self._by_token.get(token)
        if session is None:
            return {"error": "unknown_token"}
        if session.expired:
            # v1.2:过期即清理,不再复用旧 session
            logger.warning("token 已过期,拒绝复用旧 session")
            del self._by_token[token]
            return {"error": "token_expired"}
        return {"ok": True, "token": session.token}