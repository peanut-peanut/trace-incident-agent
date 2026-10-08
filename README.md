# Trace

本地运行的故障排查工作台。输入脱敏后的日志和发布差异，系统通过只读工具收集材料，生成待确认的排查假设；是否创建本地工单由人工决定。

当前版本是本地工程基线，不是生产服务。

## 运行

依赖：Python 3.11+、uv、Node.js 20+、pnpm。

```bash
bash scripts/dev.sh
```

服务启动后访问 `http://127.0.0.1:8000`。脚本会安装后端依赖、构建前端，并在缺少时创建 `backend/.env`。

前端单独开发：

```bash
cd frontend
pnpm dev
```

开发服务器将 `/api` 代理到后端 8000 端口。默认仅监听 `localhost`，不要直接暴露到公网。

## 工作流

1. 选择示例，或粘贴已授权且脱敏的日志、发布差异。
2. 查看报告中的证据引用和调用记录。
3. 在待审批状态修改工单标题和备注。
4. 确认后写入本地工单；拒绝时只保留调查记录。
5. 可导出 JSON，包含报告、证据、事件和执行统计。

报告中的原因均为待验证假设，不表示问题已经复现、修复或发布。

## 模式

- `demo`：使用固定规则和合成数据，不调用模型，用于验证流程。
- `live`：调用兼容 Chat Completions 与 function calling 的模型，并限制为只读工具。

切换模式后请新建任务；不要用 Demo 的检查点继续执行 Live 任务。

## Live 配置

编辑 `backend/.env`，密钥只保存在本地，不能提交到仓库、传到前端或粘贴到聊天：

```dotenv
APP_MODE=live
LLM_BASE_URL=https://YOUR_PROVIDER/API_BASE
LLM_API_KEY=YOUR_LOCAL_SECRET
LLM_MODEL=YOUR_TOOL_CALLING_MODEL
```

要求和限制：

- `LLM_BASE_URL` 不包含 `/chat/completions`，服务端会补充该路径，且必须为 HTTPS。
- 供应商需实际支持 `messages`、`tools`、`tool_choice`、`max_tokens`；“OpenAI-compatible”不足以保证兼容。
- 日志、差异和工具结果可能发送给模型服务商。使用前确认授权与其数据政策。
- 未完成模型配置时，Live 模式会直接报错，不会改用 Demo 规则。

已验证 DeepSeek `deepseek-flash` 的单个合成案例：工具调用、报告生成和审批暂停均可运行。该结果不代表性能或诊断准确率。详见 `docs/DEEPSEEK.md`。

## 检查

```bash
bash scripts/check.sh
```

检查包含审批写入、幂等、恢复、输入和引用校验、工具白名单、访问令牌、SSE、模型协议替身及调用预算。

`backend/evals` 是 6 个确定性回归案例，`StubModel` 也不是真实模型；通过结果不能当作模型准确率。已执行与未执行的检查见 `docs/VERIFICATION.md`。

## Docker 与 PostgreSQL

```bash
cp .env.example .env
docker compose up --build
```

Compose 将业务数据和 LangGraph 检查点存入 PostgreSQL，端口仍绑定到 `127.0.0.1:8000`。

当前机器未运行 Docker daemon，因此只检查了 Compose 配置，没有构建镜像或执行 PostgreSQL 路径测试。生产密码包含 URL 保留字符时需进行 URI 编码；正式部署应使用 Secret 注入和独立连接参数。

## 目录

```text
backend/app/
  main.py       HTTP API、SSE、审批入口和资源生命周期
  agent.py      LangGraph 流程、模型工具循环、interrupt/Command
  tools.py      工具白名单和关键词检索
  model.py      Chat Completions 客户端与协议适配
  store.py      任务、事件、工单的持久化
frontend/src/   React 控制台
docs/           架构、验证、接入和后续工作记录
```

建议从 `backend/app/main.py`、`agent.py`、`tools.py`、`store.py` 和 `backend/tests/test_app.py` 依次阅读。

## 当前范围

已完成：本地任务流程、只读工具、证据引用校验、人工审批、SQLite 检查点恢复、本地工单、SSE 和基础测试。

未完成：真实项目连接器、外部工单写入、生产认证与审计、多进程任务调度、PostgreSQL 实际运行验证，以及真实模型质量评测。

相关记录：

- `docs/ARCHITECTURE.md`
- `docs/DEEPSEEK.md`
- `docs/VERIFICATION.md`
- `docs/ROADMAP.md`
