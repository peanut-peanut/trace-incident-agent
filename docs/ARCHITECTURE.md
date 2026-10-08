# 架构记录

## 流程

```text
React 控制台
  → POST /api/runs
  → GET /api/runs/{id}/stream
  → POST /api/runs/{id}/decision

FastAPI / Pydantic / SQLAlchemy
  → LangGraph
  START → investigate → approval(interrupt) → create_ticket → END
                         └─ declined ───────────────────→ END
```

`runs`、`events`、`tickets` 是业务数据，供 API 和界面读取；LangGraph checkpoint 用于恢复图状态。两者不是同一个原子事务，恢复代码必须处理两边状态不一致的情况。

## 组件边界

调查节点由一个受限的 Agent 执行。模型在 Live 模式可选择三个只读工具：`read_error_logs`、`read_release_diff`、`search_runbooks`。审批和工单写入由服务端代码控制，模型没有写入能力。

Demo 是确定性规则流程，不使用模型，也不把自身描述为自主规划。

## 恢复与幂等

- `thread_id` 等于 `run_id`，checkpointer 保存图状态。
- `approval` 在 `interrupt()` 前不执行副作用；恢复时节点入口会再次运行。
- 人工决定先写入业务表，再通过 `Command(resume=decision)` 恢复图。
- 决定值需与业务表记录匹配，避免绕开审批数据。
- 启动时会将先前处于 `running`、`approving`、`queued` 的任务标记为 `interrupted`，由用户显式恢复。
- 只支持单进程。没有租约和心跳，不能增加 uvicorn worker 或直接横向扩容。
- checkpoint 位于节点边界。重试会重复调用只读工具或模型，不能提供 exactly-once 执行保证。

审批 API 使用状态条件更新获取写入权。相同审批内容返回既有结果；内容不同返回 409。`tickets.run_id` 的唯一约束避免本地工单重复创建。该保护不覆盖未来的 GitHub、Jira 等远程写入，远程副作用需要独立的回执、幂等和补偿设计。

## 校验与安全范围

- 工具参数经过 Pydantic 校验；未知工具和多余参数被拒绝。
- 报告需符合 schema，引用 ID 必须来自本次工具结果；runbook 不能单独证明故障事实。
- 上述校验只检查结构和引用存在性，不验证结论是否正确。
- 提示词中的防注入要求不是隔离机制。当前依赖无写工具、无 Shell、无任意路径入口和人工审批降低风险。
- 默认绑定 localhost。`CONSOLE_TOKEN` 是共享访问令牌，不是身份认证、RBAC 或租户隔离。
- 正则脱敏只覆盖部分密钥形式，使用者仍需确认输入数据允许处理。

## 检索与测试

内置 4 篇手册，通过英文词与中文二元片段匹配。它是小规模、可解释的关键词基线，不是向量检索。

工程测试覆盖暂停、权限边界、引用 ID、重复写入和恢复。模型质量需要独立测试原因判断、检索充分性、引用支持度、拒答、完成率与成本。

## 后续工作

1. 独立 worker、数据库租约或队列，解除任务执行与 Web 生命周期的耦合。
2. 记录模型和工具 attempt，限制 Token 与费用。
3. 使用 Alembic 迁移，并实际验证 PostgreSQL。
4. 为真实 GitHub/GitLab 数据实现只读连接器和来源权限控制。
5. 补充外部工单的授权、幂等、回执与补偿。
