# 新人上手

## 环境准备

    git clone git@github.com:acme/clowder-ai.git
    make bootstrap
    make dev

## 目录约定

- `src/auth/` 认证与会话,改动需两人 review
- `src/api/` HTTP 路由层,只做参数校验与转发
- `src/ui/` 前端组件
- `docs/` 设计文档与接口文档

## 提交规范

提交信息用 `type(scope): 描述`,type 取 feat / fix / refactor / chore / docs。

## 常见问题

**CI 在本地跑不过但线上能过?** 先确认 Go 版本一致,再确认有没有装 lint 工具。

**登录相关改动怎么测?** 见 `docs/design.md` 的测试策略一节,三条路径都要覆盖。