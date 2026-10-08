# DeepSeek 接入记录

日期：2026-10-06。

## 配置

- Provider：`deepseek`
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-flash`
- Mode：`live`
- `thinking`：关闭，使用非思考工具调用协议
- HTTP 超时：60 秒
- 最大模型轮次：6；单轮最多 2,200 tokens；工具调用最多 10 次
- 网络错误、429、5xx 最多重试一次

这些限制不是账户金额上限，调用仍按服务商规则计费。

## 密钥

密钥保存在本机 `backend/.env`，文件权限为 `0600`。`.gitignore`、`.dockerignore` 和源码归档不包含实际环境文件；`Settings` 的 `repr` 不显示密钥。

密钥如曾出现在聊天记录，应在 DeepSeek 控制台轮换。程序不会回显密钥，但无法撤回已有副本。更新 `LLM_API_KEY` 后重启服务。

密钥通过 HTTPS Authorization 头发送至配置的官方 API，不会加入提示词或工具结果。仍需确保业务输入已授权且已脱敏。

## 单次联调

- `GET /models` 返回 200，列表包含配置模型。
- 输入：订单页发布后白屏（合成数据）。
- 模型调用：3 轮。
- 工具调用：读取日志、读取发布差异、检索手册两次。
- usage：5,535 total tokens。
- 耗时：8,838 ms。
- 最终状态：`awaiting_approval`。
- 未审批，未创建工单。

原始结果：`deepseek-smoke-result.json`。这是单个链路检查，不是准确率、稳定性或成本结论。首次报告曾将影响范围写成未经证实的“全量白屏”；当前只校验结构和证据 ID，不能据此认定结论正确。

## 错误映射

- 401：密钥无效，不返回上游正文。
- 402：余额不足。
- 429：重试后仍限流。
- 400/422：模型参数或 schema 不兼容。
- 5xx：重试后仍不可用。
- 输出截断：拒绝不完整报告，提示缩小范围。

## 参考

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/list-models
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/guides/tool_calls

模型名以官方文档和该账号的实际模型列表为准，不保证其他账号或未来版本可用。
