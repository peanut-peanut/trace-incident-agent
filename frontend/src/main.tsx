import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronRight, Clock3, Code2, Download, FileCode2, FileText, Fingerprint, GitBranch, LoaderCircle, Plus, Radio, RotateCcw, Search, ShieldCheck, Terminal, X } from 'lucide-react';
import './styles.css';

type Example = { id: string; label: string; tag: string; title: string; description: string; logs: string; diff: string };
type Evidence = { id: string; kind: string; title: string; source: string; content: string };
type Finding = { hypothesis: string; evidence_ids: string[]; verification: string };
type Report = { summary: string; severity: string; confidence: string; findings: Finding[]; next_steps: string[]; missing_information: string[] };
type Run = { id: string; title: string; description: string; status: string; mode: string; created_at: string; report?: Report; evidence?: Evidence[]; metrics?: { model_calls: number; tool_calls: number; total_tokens: number; token_usage_available: boolean; duration_ms: number }; error?: string; ticket?: { id: string; title: string }; decision?: { approved: boolean; title: string; note: string } };
type TraceEvent = { id: number; kind: string; message: string; created_at: string; payload: Record<string, unknown> };
type Config = { mode: string; model: string | null; storage: string; retrieval: string; ticket_target: string };
const statuses: Record<string, string> = { queued: '排队中', running: '调查中', awaiting_approval: '待审核', approving: '处理中', completed: '已完成', declined: '已拒绝', failed: '执行失败', interrupted: '已中断' };
const active = (status: string) => ['running', 'queued', 'approving'].includes(status);
let token = sessionStorage.getItem('trace-token') || '';
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, { ...init, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : '输入格式不符合要求，请检查字段。'; } catch { /* 保留默认错误信息 */ }
    throw new Error(message);
  }
  return response.json();
}
const time = (value: string) => new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z').toLocaleTimeString('zh-CN', { hour12: false });

function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(() => sessionStorage.getItem('trace-selected'));
  const [streamVersion, setStreamVersion] = useState(0);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [exampleId, setExampleId] = useState('null-order');
  const [custom, setCustom] = useState(false);
  const [title, setTitle] = useState('订单页发布后出现白屏');
  const [description, setDescription] = useState('订单页在 v2.8.1 发布后出现白屏，请结合错误日志与代码变更定位可能原因，给出验证步骤。');
  const [logs, setLogs] = useState('');
  const [diff, setDiff] = useState('');
  const [ticketTitle, setTicketTitle] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [authValue, setAuthValue] = useState('');
  const [showConfig, setShowConfig] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const liveSelection = useRef(selected);
  liveSelection.current = selected;

  async function refreshHistory() { setHistory(await api<Run[]>('/runs')); }
  async function boot() {
    try {
      const [c, e, h] = await Promise.all([api<Config>('/config'), api<Example[]>('/examples'), api<Run[]>('/runs')]);
      setConfig(c); setExamples(e); setHistory(h); setError('');
    } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { void boot(); }, []);
  useEffect(() => { if (selected) sessionStorage.setItem('trace-selected', selected); else sessionStorage.removeItem('trace-selected'); }, [selected]);
  useEffect(() => {
    if (!selected) { setRun(null); setEvents([]); return; }
    const controller = new AbortController();
    setError(''); setRun(null); setEvents([]); setNote(''); setExpanded(null);
    let reconnect: ReturnType<typeof setTimeout>;
    async function connect() {
      try {
        const response = await fetch(`/api/runs/${selected}/stream`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal });
        if (!response.ok || !response.body) throw new Error('无法读取任务状态，请检查连接和访问令牌。');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let split: number;
          while ((split = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, split); buffer = buffer.slice(split + 2);
            const data = frame.split('\n').find(line => line.startsWith('data: '));
            if (data && liveSelection.current === selected) {
              const snapshot = JSON.parse(data.slice(6)) as { run: Run; events: TraceEvent[] };
              setRun(snapshot.run); setEvents(snapshot.events);
              if (!active(snapshot.run.status)) await refreshHistory();
            }
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) { setError((e as Error).message); reconnect = setTimeout(() => void connect(), 3000); }
      }
    }
    void connect();
    return () => { controller.abort(); clearTimeout(reconnect); };
  }, [selected, streamVersion]);
  useEffect(() => { if (run) setTicketTitle(run.decision?.title || run.title); }, [run?.id]); // 每个任务只初始化一次草稿。

  function pick(example: Example) { setExampleId(example.id); setTitle(example.title); setDescription(example.description); setCustom(false); }
  function newRun() { setSelected(null); setError(''); }
  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api<{ id: string }>('/runs', { method: 'POST', body: JSON.stringify({ title, description, fixture_id: custom ? null : exampleId, logs: custom ? logs : '', diff: custom ? diff : '' }) });
      setSelected(result.id); await refreshHistory();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function decide(approved: boolean) {
    if (!run) return;
    setBusy(true); setError('');
    try {
      await api(`/runs/${run.id}/decision`, { method: 'POST', body: JSON.stringify({ approved, title: ticketTitle, note }) });
      // 上一个流结束后重新连接。
      setStreamVersion(value => value + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function retry() {
    if (!run) return;
    setBusy(true); setError('');
    try { await api(`/runs/${run.id}/retry`, { method: 'POST' }); setStreamVersion(value => value + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function download() {
    if (!run) return;
    try {
      const data = await api(`/runs/${run.id}/export`);
      const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = href; link.download = `trace-${run.id}.json`; link.click(); URL.revokeObjectURL(href);
    } catch (e) { setError((e as Error).message); }
  }
  const report = run?.report;
  const demo = config?.mode === 'demo';

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); newRun(); }} aria-label="Trace 首页"><span className="brand-mark"><Fingerprint size={27} strokeWidth={1.7} /></span><span>trace<span className="brand-dot">.</span></span><small>WORKSPACE</small></a>
      <div className="workspace"><span className="workspace-avatar">研</span><div>研发效能工作台<small>Incident investigation</small></div><ChevronRight size={14} /></div>
      <button className="new-button" onClick={newRun}><Plus size={17} />新建调查<span>↗</span></button>
      <div className="sidebar-heading">调查记录 <span>{history.length.toString().padStart(2, '0')}</span></div>
      <nav aria-label="调查记录" className="history">
        {history.length ? history.map(item => <button className={`history-item ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelected(item.id)}><span className={`status-dot ${item.status}`} /><span><strong>{item.title}</strong><small>{statuses[item.status]} · {time(item.created_at)}</small></span></button>) : <div className="history-empty">暂无调查记录。</div>}
      </nav>
      <div className="sidebar-bottom"><ShieldCheck size={18} /><div>人工审批<small>写入前需要确认</small></div></div>
      <button className="config-button" onClick={() => setShowConfig(!showConfig)}><span className="online-dot" />运行环境 <span>v0.1 <ChevronRight size={13} /></span></button>
    </aside>

    <main>
      <header className="topbar"><div>工作台 <ChevronRight size={13} /> <strong>{selected ? '故障调查' : '新建调查'}</strong></div><span className={`mode-pill ${!demo && config ? 'live' : ''}`}><Radio size={13} />{!config ? '连接中' : demo ? 'DEMO · 无模型调用' : `LIVE · ${config.model}`}</span></header>
      <div className="main-content">
        <select className="mobile-history" aria-label="切换调查记录" value={selected || ''} onChange={e => setSelected(e.target.value || null)}><option value="">新建调查</option>{history.map(item => <option key={item.id} value={item.id}>{statuses[item.status]} · {item.title}</option>)}</select>
        {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}><X size={16} /></button></div>}
        {showConfig && <section className="config-panel"><div><h3>运行环境</h3><p>Python / FastAPI / LangGraph · {config?.storage || '等待连接'} · 关键词检索 · 本地工单</p><p>切换真实模型：在服务端 .env 设置 APP_MODE=live 和模型连接信息。密钥不进入浏览器。</p><label>控制台访问令牌（仅在服务端配置 CONSOLE_TOKEN 时填写）<input type="password" value={authValue} onChange={e => setAuthValue(e.target.value)} autoComplete="off" /></label></div><button className="secondary" onClick={() => { token = authValue; sessionStorage.setItem('trace-token', token); void boot(); }}>重新连接</button></section>}
        {!config && error && !showConfig && <button className="secondary" onClick={() => setShowConfig(true)}>设置访问令牌 / 检查连接</button>}

        {!selected ? <>
          <section className="page-intro"><div className="eyebrow"><span /> EVIDENCE BEFORE ACTION</div><h1>先找到证据，<br />再决定下一步<span>。</span></h1><p>把错误日志、发布变更和排查经验放在一起。<br className="mobile-hide" />让 Agent 帮你调查，让每一个结论都有出处。</p></section>
          <div className="compose-layout">
            <section className="composer card"><div className="section-title"><div><span className="number">01</span><h2>描述这次故障</h2></div><span className="small-label">READ-ONLY FIRST</span></div>
              <div className="input-mode" role="group" aria-label="数据来源"><button className={!custom ? 'on' : ''} onClick={() => setCustom(false)}>试用演示案例</button><button className={custom ? 'on' : ''} onClick={() => setCustom(true)}>使用自己的证据</button></div>
              {!custom && <div className="example-grid">{examples.map(example => <button key={example.id} className={`example ${exampleId === example.id ? 'chosen' : ''}`} onClick={() => pick(example)}><span>{exampleId === example.id ? <CheckCircle2 size={15} /> : <FileCode2 size={15} />}{example.label}</span><small>{example.tag}</small></button>)}</div>}
              <form onSubmit={create}>
                <label>故障标题<input value={title} onChange={e => setTitle(e.target.value)} required minLength={3} maxLength={160} placeholder="例如：订单页发布后出现白屏" /></label>
                <label>现象与排查目标<textarea value={description} onChange={e => setDescription(e.target.value)} required minLength={8} maxLength={4000} rows={4} /></label>
                {custom && <><label>脱敏错误日志<textarea className="code-input" value={logs} onChange={e => setLogs(e.target.value)} maxLength={12000} rows={4} placeholder="粘贴错误堆栈与必要上下文，不要包含密钥或个人信息" /></label><label>关联代码 / 发布差异<textarea className="code-input" value={diff} onChange={e => setDiff(e.target.value)} maxLength={12000} rows={4} placeholder="可选；无证据时系统应明确说明信息不足" /></label></>}
                <div className="form-footer"><span><ShieldCheck size={14} />{custom ? '请仅使用有权处理的脱敏材料' : '合成测试数据，不包含真实业务信息'}</span><button className="primary" type="submit" disabled={busy || !config}>{busy ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}开始调查<ArrowRight size={16} /></button></div>
              </form>
            </section>
            <aside className="method-card"><div className="method-kicker">A SMALL, COMPLETE LOOP</div><h2>不是再多一个聊天框。<br />是一条完整的证据链。</h2><div className="workflow">
              {[{ icon: <Terminal size={19} />, title: '读取现场', desc: '日志与发布差异', n: '01' }, { icon: <BookOpen size={19} />, title: '关联知识', desc: '检索相关排查手册', n: '02' }, { icon: <GitBranch size={19} />, title: '形成假设', desc: '引用证据，给出验证步骤', n: '03' }, { icon: <ShieldCheck size={19} />, title: '人工确认', desc: '审批后才创建本地工单', n: '04' }].map((step, i) => <React.Fragment key={step.n}><div className="workflow-step"><span className="step-icon">{step.icon}</span><div><strong>{step.title}</strong><small>{step.desc}</small></div><span className="step-number">{step.n}</span></div>{i < 3 && <div className="step-connector"><ArrowDown size={12} /></div>}</React.Fragment>)}
            </div><div className="method-note"><span className="note-dot" /><p>{demo ? '演示模式使用确定性规则验证工程流程，不代表大模型诊断准确率。' : '真实模型按需调用只读工具。诊断仍需人工验证，不会自动修改代码。'}</p></div></aside>
          </div>
          <footer className="page-footer"><span>TRACE / 故障调查记录</span><span>工具白名单 <span>·</span> 审批记录 <span>·</span> 幂等写入</span></footer>
        </> : !run ? <div className="loading-state"><LoaderCircle className="spin" size={23} />正在读取调查记录…</div> : <>
          <div className="run-heading"><div><div className="eyebrow">INVESTIGATION / {run.id.slice(0, 8).toUpperCase()}</div><h1>{run.title}</h1><p>{run.description}</p></div><button className="icon-button" onClick={() => void download()} title="导出完整调查 JSON" aria-label="导出完整调查 JSON"><Download size={19} /></button></div>
          <div className="run-meta"><span className={`run-status ${run.status}`}>{active(run.status) ? <LoaderCircle size={14} className="spin" /> : <span className={`status-dot ${run.status}`} />}{statuses[run.status]}</span><span><Clock3 size={14} />{time(run.created_at)}</span><span>{run.mode === 'demo' ? '演示策略 · 非模型效果' : '真实模型运行'}</span>{run.metrics && <><span>{run.metrics.tool_calls} 次工具调用</span><span>{run.metrics.model_calls} 次模型调用</span><span>{(run.metrics.duration_ms / 1000).toFixed(2)}s</span></>}</div>
          {run.error && <div className="error-banner"><span>{run.error}</span><button className="secondary" onClick={() => void retry()} disabled={busy}><RotateCcw size={14} />恢复 / 重试</button></div>}
          <div className="result-layout">
            <div className="result-main">
              {report ? <section className="report card"><div className="section-title"><div><span className="number">02</span><h2>诊断报告</h2></div><span className="severity">{report.severity} · 建议优先级</span></div><h3 className="report-summary">{report.summary}</h3><p className="confidence">证据把握度：{({ high: '较高', medium: '中等', low: '不足' } as Record<string, string>)[report.confidence]} · 原因假设，不等于已验证根因</p>
                {report.findings.map((finding, i) => <div className="finding" key={i}><h4><GitBranch size={16} />原因假设 {i + 1}</h4><p>{finding.hypothesis}</p><div className="citations">{finding.evidence_ids.map(id => <button key={id} onClick={() => { setExpanded(id); setTimeout(() => document.getElementById(`evidence-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0); }}><FileText size={12} />{id}<ArrowUpRight size={12} /></button>)}</div><div className="verification"><strong>如何验证</strong><p>{finding.verification}</p></div></div>)}
                <h4 className="next-title">下一步行动</h4><ol className="next-steps">{report.next_steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
                {!!report.missing_information.length && <div className="missing"><strong>尚待确认</strong>{report.missing_information.map((text, i) => <p key={i}>{text}</p>)}</div>}
              </section> : <section className="card report pending"><Search size={28} /><h3>正在读取证据</h3><p>工具调用结果会显示在右侧记录中；证据不足时不会生成原因结论。</p></section>}
              {!!run.evidence?.length && <section className="evidence-section"><div className="section-title"><div><span className="number">03</span><h2>证据材料</h2></div><span className="small-label">{run.evidence.length} SOURCES</span></div>{run.evidence.map(item => <div className="evidence-card" id={`evidence-${item.id}`} key={item.id}><button className="evidence-toggle" aria-expanded={expanded === item.id} onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{item.kind === 'diff' ? <Code2 size={18} /> : item.kind === 'runbook' ? <BookOpen size={18} /> : <Terminal size={18} />}<span><strong>{item.title}</strong><small>{item.source}</small></span><code>{item.id}</code><ChevronRight className={expanded === item.id ? 'rotated' : ''} size={16} /></button>{expanded === item.id && <pre>{item.content}</pre>}</div>)}</section>}
            </div>
            <aside className="result-aside">
              <section className="trace-panel card"><div className="section-title"><div><Radio size={16} /><h2>执行轨迹</h2></div><span className="small-label">AUDIT LOG</span></div><p className="trace-description">实际工具调用与状态，不展示或伪造模型思维链。</p><div className="trace-list">{events.map(event => <div className={`trace-event ${event.kind}`} key={event.id}><span className="trace-marker">{event.kind === 'approval' ? <ShieldCheck size={12} /> : event.kind === 'tool' ? <Terminal size={12} /> : <Check size={11} />}</span><div><p>{event.message}</p><time>{time(event.created_at)}</time>{event.kind === 'tool' && <small>{String(event.payload.duration_ms)} ms · READ ONLY</small>}</div></div>)}</div></section>
              {run.status === 'awaiting_approval' && <section className="approval-panel"><ShieldCheck size={24} /><h2>等待审批</h2><p>审核诊断后创建本地排查工单。<br />不会修改代码，也不会写入外部系统。</p><label>工单标题<input value={ticketTitle} onChange={e => setTicketTitle(e.target.value)} minLength={3} maxLength={160} /></label><label>审核备注<textarea rows={2} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} placeholder="例如：先补充复现，再评估修复方案" /></label><button className="primary" onClick={() => void decide(true)} disabled={busy || ticketTitle.trim().length < 3}><Check size={16} />确认并创建工单<ArrowRight size={16} /></button><button className="reject" onClick={() => void decide(false)} disabled={busy || ticketTitle.trim().length < 3}>暂不创建，拒绝本次写入</button></section>}
              {run.ticket && <section className="completed-panel"><CheckCircle2 size={26} /><h2>工单已创建</h2><p>{run.ticket.title}</p><code>LOCAL-{run.ticket.id.slice(0, 8).toUpperCase()}</code><small>本地持久化 · 相同审批不会重复创建</small></section>}
              {run.status === 'declined' && <section className="completed-panel declined-panel"><ShieldCheck size={24} /><h2>写入已拒绝</h2><p>调查记录已保留，没有创建工单。</p></section>}
            </aside>
          </div>
        </>}
      </div>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
