# 登录接口

## 概述

登录接口负责校验用户凭据并签发访问令牌。所有需要鉴权的接口都依赖这里签发的 token。

## 请求

    POST /api/auth/login
    Content-Type: application/json

    {"email": "user@example.com", "password": "..."}

## 响应

成功返回 200 与 token:

    {"token": "...", "expires_in": 3600, "refresh_token": "..."}

## v1.2 变更

v1.2 起新增 `refresh_token` 字段,token 过期后可以用它换取新的访问令牌,不必让用户重新登录。
同时,**过期 token 不再复用旧 session**,服务端会先清理再签发。

调用方需要处理的情况:

- token 过期:用 `refresh_token` 走 `POST /api/auth/refresh`
- `refresh_token` 也过期:跳回登录页
- 密码错误:返回 401,不要重试

## 错误码

| 状态码 | 含义 | 处理建议 |
|---|---|---|
| 400 | 请求体缺字段 | 检查 email / password |
| 401 | 凭据错误或 token 过期 | 提示用户重新输入,或用 refresh_token 续期 |
| 429 | 触发登录频率限制 | 退避后重试 |
| 500 | 服务端异常 | 记录 trace_id 后联系后端 |

## 安全说明

密码比较必须使用常量时间比较函数,禁止明文比较 —— 明文比较会因提前返回而泄露密码前缀。