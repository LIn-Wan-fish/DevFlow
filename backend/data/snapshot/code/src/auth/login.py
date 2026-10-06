"""凭据校验层。"""

import hmac
import logging

logger = logging.getLogger("auth.login")

SESSION_FILE = "src/auth/session.py"


def verify_password(stored_hash: bytes, provided: bytes) -> bool:
    # 必须用常量时间比较:普通 == 会在首个不同字节提前返回,泄露密码前缀
    return hmac.compare_digest(stored_hash, provided)


def login(email: str, password: str, store) -> dict:
    user = store.find_user_by_email(email)
    if user is None:
        logger.warning("用户不存在 code=401 email=%s", email)
        return {"error": "invalid_credentials", "code": 401}

    if not verify_password(user.password_hash, password.encode()):
        # 对应 CI #512 失败日志里的 src/auth/session.py:88
        logger.warning("密码校验失败 code=401 path=src/auth/session.py:88")
        return {"error": "invalid_credentials", "code": 401}

    session = store.create_session(user.id)
    return {"token": session.token, "expires_in": session.ttl, "refresh_token": session.refresh}