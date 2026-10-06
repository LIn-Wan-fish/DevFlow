"""导入所有工具模块,触发注册。

注册靠 import 副作用,所以这里必须把每个模块都列出来 ——
漏掉一个,那个工具就会在运行时「不存在」,而且报错信息很难指向根因。
"""

from app.tools import (  # noqa: F401
    analyze_issue,
    debug_ci,
    draft_action,
    repo_health,
    review_pr,
    run_workflow,
    safety_check,
    search_code,
    search_docs,
    weekly_report,
)
from app.tools.registry import (  # noqa: F401
    REGISTRY,
    ToolContext,
    ToolResult,
    ToolSpec,
    UnknownToolError,
    as_langchain_tools,
    execute,
    names,
    register,
)