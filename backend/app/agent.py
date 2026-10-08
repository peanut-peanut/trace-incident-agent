import json
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import tools
from .model import ModelClient, ModelProviderError, SYSTEM
from .schemas import Decision, Report, redact


class State(TypedDict, total=False):
    run_id: str
    input: dict
    evidence: list[dict]
    report: dict
    metrics: dict
    decision: dict
    ticket_id: str


def validate_report(raw, evidence):
    report = Report.model_validate(raw)
    available = {item["id"] for item in evidence}
    for finding in report.findings:
        if not set(finding.evidence_ids) <= available:
            raise ValueError("Report contains unknown evidence IDs")
        if not any(x.startswith(("LOG-", "DIFF-")) for x in finding.evidence_ids):
            raise ValueError("A runbook alone cannot substantiate an incident finding")
    if not report.findings and not report.missing_information:
        raise ValueError("Report without findings must explain missing information")
    if not report.findings and report.confidence != "low":
        raise ValueError("Report without findings must have low confidence")
    return report.model_dump()


def demo_report(evidence):
    """Transparent deterministic pipeline fixture, NOT an LLM or accuracy benchmark."""
    logs = next((e["content"] for e in evidence if e["id"] == "LOG-01"), "")
    ids = [e["id"] for e in evidence if e["id"] in {"LOG-01", "DIFF-01"}]
    hypothesis, verification = "", ""
    if "Cannot read properties of null" in logs:
        hypothesis = "订单数据为 null 时访问 order.items，可能触发渲染异常；需复现确认。"
        verification = "用 order=null 重放订单页请求，对照 orders.tsx:42；验证可选链/空状态处理与边界测试。"
    elif "ChunkLoadError" in logs:
        hypothesis = "旧标签页引用的 chunk 已被发布清理，可能造成跨版本资源加载失败。"
        verification = "保留旧标签页后发布新版本，核对请求哈希、CDN 404 和资源保留策略。"
    elif "response.data.map is not a function" in logs:
        hypothesis = "接口 data 从数组变为带 items 的对象，前端旧读取方式可能与 API 契约不兼容。"
        verification = "对照实际响应结构与前端 map 调用，增加响应 schema 校验和契约回归测试。"
    return {"summary": hypothesis or "现有信息不足以形成有证据支持的原因假设，需要补充材料。", "severity": "P2" if hypothesis else "P3", "confidence": "medium" if hypothesis else "low", "findings": [{"hypothesis": hypothesis, "evidence_ids": ids, "verification": verification}] if hypothesis else [], "next_steps": [verification, "由值班人员确认影响范围和优先级，审批后创建排查工单。"] if hypothesis else ["补充错误堆栈、发布差异、影响范围和最小复现。"], "missing_information": ["真实影响范围与复现结果尚未提供；优先级仅为待人工确认的建议。"] if hypothesis else ["缺少可识别的错误堆栈或关联发布证据。"]}


class Agent:
    def __init__(self, store, settings, checkpointer, model=None):
        self.store, self.settings = store, settings
        self.model = model or ModelClient(settings)
        graph = StateGraph(State)
        graph.add_node("investigate", self.investigate)
        graph.add_node("approval", self.approval)
        graph.add_node("create_ticket", self.create_ticket)
        graph.add_edge(START, "investigate")
        graph.add_edge("investigate", "approval")
        graph.add_conditional_edges("approval", lambda state: "create_ticket" if state["decision"]["approved"] else END)
        graph.add_edge("create_ticket", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    def investigate(self, state):
        started = time.monotonic()
        run_id, input_data = state["run_id"], state["input"]
        evidence = {}
        metrics = {"model_calls": 0, "tool_calls": 0, "total_tokens": 0, "token_usage_available": True, "mode": self.settings.app_mode}

        def invoke(name, args):
            if metrics["tool_calls"] >= self.settings.max_tool_calls:
                raise ValueError("Tool budget exceeded")
            metrics["tool_calls"] += 1
            begin = time.monotonic()
            result = tools.execute(name, args, input_data)
            for item in result:
                evidence[item["id"]] = item
            self.store.event(run_id, "tool", f"{name} · {len(result)} 条证据", {"name": name, "arguments": args, "evidence_ids": [e["id"] for e in result], "duration_ms": round((time.monotonic()-begin)*1000)})
            return result

        self.store.event(run_id, "started", "开始调查 · " + ("确定性演示策略（非模型）" if self.settings.app_mode == "demo" else "真实模型 + 只读工具"))
        if self.settings.app_mode == "demo":
            invoke("read_error_logs", {})
            invoke("read_release_diff", {})
            query = (input_data["logs"][:140] or input_data["description"][:140])
            invoke("search_runbooks", {"query": query})
            report = validate_report(demo_report(list(evidence.values())), list(evidence.values()))
        else:
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps({"title": input_data["title"], "description": input_data["description"]}, ensure_ascii=False)}]
            report = None
            for step in range(self.settings.max_model_rounds):
                can_call_tools = step < self.settings.max_model_rounds - 1 and metrics["tool_calls"] < self.settings.max_tool_calls
                message, usage = self.model.complete(messages, allow_tools=can_call_tools)
                metrics["model_calls"] += 1
                if "total_tokens" not in usage:
                    metrics["token_usage_available"] = False
                metrics["total_tokens"] += usage.get("total_tokens", 0)
                calls = message.get("tool_calls") or []
                # 仅保留标准协议字段。
                clean = {"role": "assistant", "content": message.get("content")}
                if calls:
                    clean["tool_calls"] = calls
                messages.append(clean)
                self.store.event(run_id, "model", f"模型调用 #{metrics['model_calls']}", {"tool_requests": len(calls), "total_tokens": usage.get("total_tokens")})
                if calls:
                    if not can_call_tools:
                        raise ValueError("Model ignored tool budget")
                    for call in calls:
                        name = call["function"]["name"]
                        try:
                            args = json.loads(call["function"]["arguments"])
                            result = invoke(name, args)
                        except (ValueError, TypeError):
                            result = {"error": "Tool unavailable, invalid parameters or budget exceeded. Do not invent results."}
                            self.store.event(run_id, "tool_error", "工具请求被拒绝或参数无效", {"tool": redact(str(name))[:100]})
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
                    continue
                try:
                    raw = json.loads(message.get("content") or "")
                    report = validate_report(raw, list(evidence.values()))
                    break
                except (ValueError, TypeError):
                    self.store.event(run_id, "validation", "报告格式或证据校验未通过，要求模型修正")
                    messages.append({"role": "user", "content": "Return valid report JSON. Cite only observed evidence IDs. Findings require log/diff evidence; if evidence is insufficient use findings=[], confidence=low and list missing_information."})
            if report is None:
                raise ValueError("Model exhausted its budget without a validated report")
        metrics["duration_ms"] = round((time.monotonic() - started) * 1000)
        self.store.patch(run_id, report=report, evidence=list(evidence.values()), metrics=metrics)
        self.store.event(run_id, "report", "诊断报告已生成；原因仍待人工验证", {"evidence_count": len(evidence)})
        return {"report": report, "evidence": list(evidence.values()), "metrics": metrics}

    def approval(self, state):
        # interrupt 前不能有副作用，恢复时该节点会重跑。
        value = interrupt({"action": "create_local_ticket", "report": state["report"], "requires_human": True})
        decision = Decision.model_validate(value).model_dump()
        recorded = self.store.get(state["run_id"])["decision"]
        if recorded != decision:
            raise ValueError("Approval must match the decision recorded by the API")
        return {"decision": decision}

    def create_ticket(self, state):
        if not state["decision"]["approved"]:
            raise ValueError("Unapproved write")
        ticket_id = self.store.ticket(state["run_id"], state["decision"], state["report"])
        self.store.event(state["run_id"], "ticket", "本地排查工单已创建（未写入 GitHub / Jira）", {"ticket_id": ticket_id})
        return {"ticket_id": ticket_id}

    def execute(self, run_id, resume=False):
        row = self.store.get(run_id)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 20}
        try:
            if row["mode"] != self.settings.app_mode:
                raise ValueError("Mode changed: restart in the original mode or create a new task")
            snapshot = self.graph.get_state(config)
            if resume and snapshot.values:
                has_interrupt = any(t.interrupts for t in snapshot.tasks)
                if has_interrupt and row["decision"] is not None:
                    graph_input = Command(resume=row["decision"])
                else:
                    graph_input = None
            else:
                graph_input = {"run_id": run_id, "input": row["input"]}
            result = self.graph.invoke(graph_input, config)
            status = "awaiting_approval" if result.get("__interrupt__") else ("completed" if result.get("ticket_id") else "declined")
            self.store.patch(run_id, status=status, error=None)
            self.store.event(run_id, "status", {"awaiting_approval": "等待人工审核，尚未创建工单", "completed": "调查闭环完成", "declined": "已拒绝创建工单"}[status])
        except Exception as exc:
            # 不向控制台返回上游响应正文或凭据。
            safe_error = str(exc) if isinstance(exc, ModelProviderError) else f"执行失败（{type(exc).__name__}）。检查模型配置、网络或工具预算；可重试。"
            self.store.patch(run_id, status="failed", error=safe_error)
            self.store.event(run_id, "failed", safe_error)
