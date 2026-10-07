"""角色解析与权限入口。

**修的是什么**:角色原先由客户端在请求体(`ChatRequest.role`)或查询参数
(`?role=member`)里自称,后端照单全收 —— 任何人传 `role=maintainer` 就能执行写操作。
那意味着「越权会被拦下」这件事是**演示出来的**,不是系统保证的。

**现在的规则**:

1. 角色由服务端从**请求头**解析,请求体与查询参数里的 role 一律不参与授权。
2. 配置了 `DEVFLOW_ROLE_TOKENS` 时进入**令牌模式**:必须携带匹配的令牌,
   服务端据此映射角色;缺失或不匹配 → 401。这是真正的认证(虽然简单)。
3. 未配置令牌时进入**演示模式**:读 `X-DevFlow-Role` 头,校验取值合法,默认 `viewer`。
   演示模式**不构成认证** —— 客户端仍可自称角色。`/api/auth/me` 会如实报告
   `enforced: false`,前端据此显示提示,不会让人误以为有权限体系。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from app.config import settings
from app.safety import policy

logger = logging.getLogger(__name__)

DEFAULT_ROLE = "viewer"
ROLE_HEADER = "X-DevFlow-Role"
TOKEN_HEADER = "X-DevFlow-Role-Token"


def parse_role_tokens(raw: str | None) -> dict[str, str]:
    """把 `role:token,role:token` 解析成 {token: role}。

    只接受合法角色名;格式错误的条目直接忽略并记警告,不让一个手误的配置
    把整个权限体系降级成「谁都能过」。
    """
    mapping: dict[str, str] = {}
    for chunk in (raw or "").split(","):
        entry = chunk.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning("DEVFLOW_ROLE_TOKENS 条目格式错误,已忽略:%r", entry)
            continue
        role, token = (part.strip() for part in entry.split(":", 1))
        if role not in policy.ROLES or not token:
            logger.warning("DEVFLOW_ROLE_TOKENS 条目角色非法或令牌为空,已忽略:%r", entry)
            continue
        mapping[token] = role
    return mapping


def is_enforced() -> bool:
    return bool(parse_role_tokens(settings.devflow_role_tokens))


def _presented_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get(TOKEN_HEADER)


def resolve_role(request: Request) -> str | None:
    """解析角色,**失败返回 None 而不是抛异常**。

    给中间件用:中间件要的是"这个请求能不能过",不需要区分
    "没带令牌"还是"令牌不对" —— 那个区分只对 FastAPI 依赖有意义。
    """
    tokens = parse_role_tokens(settings.devflow_role_tokens)
    if tokens:
        presented = _presented_token(request)
        return tokens.get(presented) if presented else None
    # 演示模式下服务端无法证明身份,一律当成已通过(但会如实报告 enforced=false)
    return (request.headers.get(ROLE_HEADER) or DEFAULT_ROLE).strip()


async def get_role(request: Request) -> str:
    """FastAPI 依赖:解析当前请求的角色。"""
    tokens = parse_role_tokens(settings.devflow_role_tokens)

    if tokens:
        presented = _presented_token(request)
        role = tokens.get(presented) if presented else None
        if role is None:
            # 不区分「没带令牌」和「令牌不对」,避免给探测者额外信息
            raise HTTPException(status_code=401, detail="缺少或无效的角色令牌")
        return role

    # 演示模式:取值仍然要合法,但服务端无法证明客户端身份
    raw = (request.headers.get(ROLE_HEADER) or DEFAULT_ROLE).strip()
    if raw not in policy.ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"未知角色 {raw!r},只允许 {' / '.join(policy.ROLES)}",
        )
    return raw

# --------------------------------------------------------------------------- 对外端点

router = None  # 由 build_router() 赋值,避免循环导入


def build_router():  # noqa: ANN201
    from fastapi import APIRouter

    api = APIRouter(prefix="/api/auth", tags=["权限与认证"])

    @api.get("/mode", summary="查询认证模式(是否强制令牌、当前是 demo 还是 enforced)")
    def mode() -> dict:
        """公开端点:如实报告当前是否有认证。

        前端用它显示「演示模式(无认证)」提示 ——
        没有认证这件事必须写在脸上,不能让人以为有权限体系。
        """
        enforced = is_enforced()
        return {
            "enforced": enforced,
            "mode": "token" if enforced else "demo",
            "roles": list(policy.ROLES),
            "default_role": DEFAULT_ROLE,
            "role_header": ROLE_HEADER,
        }

    return api


router = build_router()