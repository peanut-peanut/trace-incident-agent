# 技术选型参考

核对日期：2026-10-06。

## 参考范围

目标方向为 AI 应用 / Agent 开发，偏后端与全栈实现，不覆盖模型训练岗位或纯前端岗位。

已完整核对的岗位正文来自腾讯，只作为方向参考，不代表行业统计结论。字节的旧招聘链接有重定向，未能完整核对正文，因此未作为选型依据。

当前项目采用 Python 服务端、LangGraph 流程和 React 前端，用于覆盖模型工具调用、状态恢复、人工审批和前后端交付。该选择不表示 Python 是唯一可用语言，也不表示岗位排斥 Node.js、Go 或 Java。

## 已核对岗位

### 腾讯：AI 应用开发工程师，Agent 方向（深圳）

- 详情：https://careers.tencent.com/zh-cn/jobdesc.html?postId=2026845083588001792
- 页面日期：2026-08-26。
- 内容涉及 Agent 规划、记忆、RAG、长任务、安全环境、Skills/MCP、效果评测和工程实现。
- 同时要求模型原理、推理或微调等能力；本项目不能替代相关经验。

### 腾讯：Agent 开发工程师（IEG，深圳）

- 检索入口：https://careers.tencent.com/zh-cn/search.html?keyword=Agent
- 页面日期：2026-09-03。
- 内容涉及前后端实现、工具和知识库、系统集成、Benchmark、Tracing、测试、权限、审计和故障恢复。
- 服务端语言包含 Python、Go、Java、Node.js，前端包含 JavaScript/TypeScript。
- 工作年限和学历要求仍以岗位原文为准，个人项目不能替代。

### 腾讯：应用效能技术部 Agent 开发工程师，平台方向

- 同一检索入口，页面日期：2026-09-09。
- 已核对职责摘要：编排、模型与工具接入、上下文、评测、可观测性和可靠性。
- 未完整核对任职资格，因此不据此推断语言或框架要求。

## 项目映射

| 能力 | 项目实现 | 当前状态 |
|---|---|---|
| Tool calling | 模型只能调用只读工具，服务端限制工具与轮次 | DeepSeek 单案例联调完成，系统评测未做 |
| 业务流程 | 故障材料生成待审批的排查工单 | 本地闭环 |
| 检索与上下文 | 手册检索、证据 ID、非法引用拒绝 | 关键词基线；向量检索未做 |
| 长任务与人工审批 | checkpoint、审批中断和恢复 | SQLite 路径已测试 |
| 可靠性 | 状态 CAS、唯一键、恢复与重试 | 单进程实现 |
| 评测 | 固定输入和流程断言 | 仅工程回归 |
| 可观测性 | 调用事件、耗时、usage、SSE | 本地记录，不是监控平台 |
| 安全 | 白名单、无 Shell、审批、共享令牌 | 无完整 RBAC 或多租户 |
| 前后端交付 | React、Python API、持久化 | 本地验证 |

## 当前取舍

- Python、FastAPI、Pydantic：服务端、模型适配和参数/报告契约。
- LangGraph：需要中断、恢复和显式状态流程。
- PostgreSQL：目标运行数据库；本地未启动 Docker 时使用 SQLite。
- pgvector、reranker：接入真实文档并确认检索收益后再加入。
- Redis、worker：并发或长任务需要时加入。
- MCP：先验证一个真实工具，再决定是否抽象为协议。
- React、TypeScript：提供任务创建、证据查看和审批页面。
- Langfuse 或 OTel：真实模型调用增加后，用于记录成本、错误和延迟。

## 参考资料

- LangGraph overview：https://docs.langchain.com/oss/python/langgraph/overview
- Interrupts：https://docs.langchain.com/oss/python/langgraph/interrupts
- Persistence：https://docs.langchain.com/oss/python/langgraph/persistence
- Function calling：https://developers.openai.com/api/docs/guides/function-calling

后续应根据实际投递的岗位重新核对语言、系统设计和算法要求。
