"""L1 抽取层 —— Claude Agent SDK（走 Claude Code CLI 登录态，计费到订阅）。

并发模型：LLM 调用批内并发（Semaphore 限流），DB 写永远在主协程串行 ——
psycopg 连接不是 task-safe 的，把并发限制在无共享状态的 extract 调用上。

强 schema 靠工具调用：给模型唯一一个 `submit_extraction` 工具（带 JSON
schema），不给任何文件/网络工具，要求把结构化结果作为工具参数提交 ——
schema 校验发生在工具层，比"请输出 JSON"可靠。

Extractor 是协议：orchestrator 只依赖它，测试用 FakeExtractor，
生产用 ClaudeExtractor。每次调用（含失败）都落 llm_calls —— 可审计是底线。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .config import Config
from .contentstore import ContentStore

log = logging.getLogger(__name__)

MAX_CHARS = 12000          # 超长正文截断（抽取要的是断言，不是全文复读）

# 会话里除了我们的提交工具，其余一律禁用 —— 每个内置/平台工具的定义都进系统
# 提示。实测（2026-07-27 探针）：默认注册 34 个工具、会话 input 侧 ~68k tokens；
# 全禁后剩 1 个工具、~8k tokens，降 8.6 倍。
# 清单来自 init 消息的实测枚举；新环境可能带新工具，发现漏网就补进来
# （判断方法：SystemMessage init 的 data["tools"] 里除 mcp__ 前缀外不应有任何条目）。
DISALLOW_ALL_BUILTIN = [
    "Task", "Bash", "Glob", "Grep", "ExitPlanMode", "Read", "Edit", "MultiEdit",
    "Write", "NotebookEdit", "WebFetch", "TodoWrite", "WebSearch", "BashOutput",
    "KillShell", "SlashCommand", "Skill", "ListMcpResourcesTool",
    "ReadMcpResourceTool", "CronCreate", "CronDelete", "CronList", "DesignSync",
    "EnterWorktree", "ExitWorktree", "ListConnectors", "ListPlugins", "ListSkills",
    "Monitor", "PushNotification", "ReportFindings", "ScheduleWakeup",
    "SearchMcpRegistry", "SearchPlugins", "SearchSkills", "SendMessage",
    "SendUserFile", "ShowOnboardingRolePicker", "SuggestConnectors",
    "SuggestPluginInstall", "SuggestSkills", "TaskCreate", "TaskGet", "TaskList",
    "TaskOutput", "TaskStop", "TaskUpdate", "ToolSearch", "Workflow", "Artifact",
    "AskUserQuestion", "EnterPlanMode",
]

# 单篇结果的 schema 片段；批量模式下包在 documents 数组里
_DOC_PROPS = {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text":  {"type": "string", "description": "断言的一句话陈述，保留可核查的具体性（数字、日期、机构名）"},
            "who":   {"type": "string"}, "did": {"type": "string"},
            "whom":  {"type": "string"}, "when": {"type": "string"},
            "where": {"type": "string"},
            "stance": {"type": "integer", "minimum": -2, "maximum": 2,
                       "description": "本文对该断言的立场：-2 否认/反驳 -1 质疑 0 中性转述 +1 支持 +2 强支持"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "required": ["text", "stance", "confidence"]}},
        "entities": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "description": "实体的规范名（全称，不带头衔）"},
            "kind": {"type": "string",
                     "enum": ["org", "person", "product", "place", "event", "other"]},
        }, "required": ["name", "kind"]}},
        "lang": {"type": "string", "description": "正文主要语言，ISO 639-1"},
        "is_opinion": {"type": "boolean", "description": "评论/观点文，而非事实报道"},
}

# 批量提交：每次 SDK 调用都是一整个 Claude Code 会话（系统提示 + 工具定义
# ≈ 40k tokens 底盘），单篇调用的开销是文章本身的 ~60 倍（审计表实测）。
# 一次调用打包 N 篇，把底盘摊薄 N 倍。
BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {"type": "array", "items": {"type": "object", "properties": {
            "doc_index": {"type": "integer",
                          "description": "对应输入里的文档编号，从 0 开始，必须逐一对应"},
            **_DOC_PROPS,
        }, "required": ["doc_index", "claims", "entities", "lang", "is_opinion"]}},
    },
    "required": ["documents"],
}

_RULES = """抽取原则：
- claim 是**可核查的断言**：谁/做了什么/对谁/何时/何地。保留数字、日期、机构名。
- 只抽文档实际主张或转述的断言，不做推断、不补外部知识。
- stance 是**本文**对断言的立场（转述别人的否认 → 记否认方的断言，stance 按本文口吻）。
- 实体用规范全称；同一实体出现多次只提交一次。国家与机构一律用完整正式名
  （United Kingdom 而非 UK/Britain；United States Department of Commerce 而非
  U.S. Commerce Department）；头衔指称解析为实际人名。
- 断言每篇 3–10 条为宜；空洞的套话（"各方表示关切"）不算断言。
- 每篇文档独立抽取：不要把 A 篇的实体或断言混进 B 篇。"""

SYSTEM_PROMPT = """你是新闻情报系统的抽取器。给你若干篇编号的文档正文，你必须调用
submit_extraction 工具**一次性**提交全部文档的结构化抽取结果（documents 数组，
每篇一个元素，doc_index 与输入编号逐一对应），除此之外不做任何事、不输出任何散文。

""" + _RULES

CODEX_PROMPT = """你是新闻情报系统的抽取器。给你若干篇编号的文档正文，把全部文档的
结构化抽取结果作为**最终答复**输出：仅一个符合约定 schema 的 JSON 对象
（documents 数组，每篇一个元素，doc_index 与输入编号逐一对应），不输出任何其他文字、
不使用任何工具、不读写任何文件。

""" + _RULES


@dataclass
class ExtractionResult:
    claims: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    lang: str | None = None
    is_opinion: bool = False
    model: str = "unknown"
    tokens_in: int | None = None
    tokens_out: int | None = None
    usage: dict | None = None      # SDK 返回的完整 usage（含缓存命中），整体入审计
    error: str | None = None


class Extractor(Protocol):
    async def extract_batch(
        self, docs: list[tuple[str, str | None]]) -> list[ExtractionResult]:
        """docs: [(text, title)] → 与输入等长的结果列表（失败时整批同一 error）。"""
        ...


class ClaudeExtractor:
    """Agent SDK 实现。CLI 未登录时首次调用即失败，错误早暴露。

    捕获状态必须是**每次调用局部的**：工具 handler 写入的 dict、SDK server、
    options 全部在 extract() 内构造 —— 教训（2026-07-27）：实例级共享
    captured dict 在并发批下发生竞态，88/202 篇结果被并发任务清掉，
    且存在 A 文档挂上 B 文档结果的串号风险，整批回滚重抽。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    async def extract_batch(
            self, docs: list[tuple[str, str | None]]) -> list[ExtractionResult]:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        captured: dict = {}                  # per-call，无共享

        @tool("submit_extraction", "一次性提交全部文档的结构化抽取结果", BATCH_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="extract", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"ex": server},
            allowed_tools=["mcp__ex__submit_extraction"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=6,     # 3 偶发不够：模型先说一句再调工具就到限，SDK 把到限当 error
        )
        per = max(2000, MAX_CHARS // max(len(docs), 1))
        prompt = "\n\n".join(
            f"===== 文档 {i} =====\n标题：{t or '(无)'}\n正文：\n{x[:per]}"
            for i, (x, t) in enumerate(docs))
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                model = msg.model or model   # ResultMessage 无 model 字段，只能从这里拿
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        got = {d.get("doc_index"): d for d in captured.get("documents", [])
               if isinstance(d, dict)}
        if not got and not err:
            err = "model did not call submit_extraction"
        out: list[ExtractionResult] = []
        for i in range(len(docs)):
            d = got.get(i)
            if d is None:
                out.append(ExtractionResult(model=model, usage=usage,
                                            error=err or f"doc_index {i} missing"))
            else:
                out.append(ExtractionResult(
                    claims=d.get("claims", []), entities=d.get("entities", []),
                    lang=d.get("lang"), is_opinion=d.get("is_opinion", False),
                    model=model, usage=usage if i == 0 else None,  # usage 只记一次，避免重复计数
                    error=None))
        return out


def _strictify(node):
    """OpenAI 结构化输出的严格模式：object 必须 additionalProperties:false
    且全字段 required —— 原本可选的字段转为 nullable。"""
    if isinstance(node, list):
        return [_strictify(x) for x in node]
    if not isinstance(node, dict):
        return node
    n = {k: _strictify(v) for k, v in node.items()}
    if n.get("type") == "object" and "properties" in n:
        req = set(n.get("required", []))
        for k, v in n["properties"].items():
            if k not in req and isinstance(v, dict) and isinstance(v.get("type"), str):
                v["type"] = [v["type"], "null"]
        n["required"] = list(n["properties"].keys())
        n["additionalProperties"] = False
    return n


CODEX_SCHEMA = _strictify(BATCH_SCHEMA)


async def codex_structured(prompt: str, schema: dict,
                           model: str = "gpt-5.6-luna", effort: str = "low",
                           timeout: int = 600) -> tuple[dict | None, str | None]:
    """codex exec 的通用结构化调用：--output-schema 强制输出形状。
    返回 (payload, error)。任何引擎无关的调用方（抽取、阅读版本…）共用。"""
    import asyncio
    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="na-codex-") as td:
        schema_path = os.path.join(td, "schema.json")
        out_path = os.path.join(td, "out.json")
        with open(schema_path, "w") as f:
            json.dump(_strictify(schema), f)
        cmd = ["codex", "exec",
               "-m", model,
               "-c", f'model_reasoning_effort="{effort}"',
               "--ignore-user-config", "--ephemeral",
               "--skip-git-repo-check", "-s", "read-only",
               "--color", "never",
               "--output-schema", schema_path, "-o", out_path, "-"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE, cwd=td)
            _, stderr = await asyncio.wait_for(
                proc.communicate(prompt.encode()), timeout=timeout)
            if proc.returncode != 0:
                return None, (f"codex exit {proc.returncode}: "
                              f"{stderr.decode(errors='replace')[-300:]}")
        except (TimeoutError, asyncio.TimeoutError):
            proc.kill()
            return None, f"codex timeout ({timeout}s)"
        except Exception as e:
            return None, f"codex spawn: {type(e).__name__}: {e}"
        try:
            with open(out_path) as f:
                return json.load(f), None
        except Exception as e:
            return None, f"codex output parse: {type(e).__name__}: {e}"


class CodexExtractor:
    """OpenAI Codex CLI 实现（codex exec 非交互模式，走 ChatGPT 订阅登录态）。

    结构化靠 --output-schema：CLI 在响应层强制最终输出符合 BATCH_SCHEMA。
    --ignore-user-config 保证行为与用户本地 codex 配置解耦（auth 不受影响）；
    --ephemeral 不落会话文件；沙箱 read-only、禁写盘。"""

    def __init__(self, model: str = "gpt-5.6-luna", effort: str = "low"):
        import shutil
        if not shutil.which("codex"):
            raise RuntimeError("codex CLI not found on PATH")
        self._model, self._effort = model, effort
        self.label = f"codex:{model}@{effort}"

    async def extract_batch(
            self, docs: list[tuple[str, str | None]]) -> list[ExtractionResult]:
        per = max(2000, MAX_CHARS // max(len(docs), 1))
        prompt = CODEX_PROMPT + "\n\n" + "\n\n".join(
            f"===== 文档 {i} =====\n标题：{t or '(无)'}\n正文：\n{x[:per]}"
            for i, (x, t) in enumerate(docs))

        payload, err = await codex_structured(prompt, BATCH_SCHEMA,
                                              self._model, self._effort)
        got: dict = {}
        if payload:
            got = {d.get("doc_index"): d for d in payload.get("documents", [])
                   if isinstance(d, dict)}
        if not got and not err:
            err = "codex returned no documents"

        out: list[ExtractionResult] = []
        for i in range(len(docs)):
            d = got.get(i)
            if d is None:
                out.append(ExtractionResult(model=self.label,
                                            error=err or f"doc_index {i} missing"))
            else:
                out.append(ExtractionResult(
                    claims=d.get("claims", []), entities=d.get("entities", []),
                    lang=d.get("lang"), is_opinion=d.get("is_opinion", False),
                    model=self.label, usage=None, error=None))
        return out


class SplitExtractor:
    """把批次轮流分给多个引擎（'分一半'的实现）。批为单位轮转，
    两边各自的失败由 run_extraction 的熔断与重试统一兜底。"""

    def __init__(self, subs: list):
        self._subs, self._i = subs, 0

    async def extract_batch(self, docs):
        sub = self._subs[self._i % len(self._subs)]
        self._i += 1
        return await sub.extract_batch(docs)


def make_extractor(spec: str | None):
    """模型 spec → Extractor。
    None/别名/'claude:xx' → ClaudeExtractor（订阅 Claude）
    'codex:MODEL[@effort]' → CodexExtractor（订阅 ChatGPT）
    'split:A,B[,C]'        → 批次轮转"""
    if spec and spec.startswith("split:"):
        return SplitExtractor([make_extractor(p.strip())
                               for p in spec[6:].split(",")])
    if spec and spec.startswith("codex:"):
        model, _, eff = spec[6:].partition("@")
        return CodexExtractor(model=model, effort=eff or "low")
    if spec and spec.startswith("claude:"):
        spec = spec[7:]
    return ClaudeExtractor(model=spec)


# ── orchestrator ────────────────────────────────────────────

def _pending_docs(conn: psycopg.Connection, limit: int) -> list[tuple]:
    # 新闻优先（id 降序）：态势感知系统里"今天的头条不可见"比"旧闻晚入库"
    # 致命得多。积压是闲时慢慢消化的档案，不是挡在队头的墙。
    with conn.cursor() as cur:
        cur.execute("""SELECT d.id, d.title, d.content_ref FROM documents d
                       JOIN sources s ON s.id = d.source_id
                       WHERE d.status='ok' AND d.extracted_at IS NULL
                         AND d.content_ref IS NOT NULL
                         AND s.section = 'news'
                       ORDER BY d.id DESC LIMIT %s""", (limit,))
        return cur.fetchall()


def _upsert_entity(cur: psycopg.Cursor, name: str, kind: str) -> int:
    cur.execute("""SELECT id FROM entities
                   WHERE lower(canonical_name)=lower(%s) AND kind=%s
                     AND merged_into IS NULL""", (name, kind))
    r = cur.fetchone()
    if r:
        return r[0]
    cur.execute("INSERT INTO entities (canonical_name, kind) VALUES (%s,%s) RETURNING id",
                (name, kind))
    return cur.fetchone()[0]


async def run_extraction(conn: psycopg.Connection, cfg: Config,
                         extractor: Extractor, limit: int = 20,
                         concurrency: int = 2, batch_size: int = 8) -> dict:
    import asyncio

    store = ContentStore(cfg.data_dir, cfg.drive_remote)
    stats = {"docs": 0, "claims": 0, "entities": 0, "errors": 0}

    pending = []
    for doc_id, title, ref in _pending_docs(conn, limit):
        try:
            pending.append((doc_id, title, store.get(ref)))
        except OSError:
            log.warning("doc %s: content file missing", doc_id)
            stats["errors"] += 1

    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    sem = asyncio.Semaphore(concurrency)

    # 熔断：连续失败通常是订阅限额窗口耗尽（真实事故：189 连败），
    # 尽早停止，失败文档下轮自动重试。批量模式下以批为单位计数。
    breaker = {"consecutive": 0, "tripped": False}

    async def _one_batch(batch):
        if breaker["tripped"]:
            return [ExtractionResult(error="skipped: circuit open")] * len(batch)
        async with sem:
            try:
                res = await extractor.extract_batch([(t, ti) for _, ti, t in batch])
            except Exception as e:
                log.exception("batch of %d: extractor raised", len(batch))
                res = [ExtractionResult(error=f"exception: {e}")] * len(batch)
        if all(r.error for r in res):
            breaker["consecutive"] += 1
            if breaker["consecutive"] >= 3:
                breaker["tripped"] = True
                log.error("circuit breaker tripped after %d consecutive failed "
                          "batches (likely rate limit)", breaker["consecutive"])
        else:
            breaker["consecutive"] = 0
        return res

    batch_results = await asyncio.gather(*(_one_batch(b) for b in batches))

    flat = [(doc_id, title, text, res)
            for batch, results in zip(batches, batch_results)
            for (doc_id, title, text), res in zip(batch, results)]

    for doc_id, title, text, res in flat:
        if res.error == "skipped: circuit open":
            continue                     # 未调用：不写审计，不计数，下轮重试

        with conn.cursor() as cur:
            # 审计先行：调用本身（含失败）永远落库（DB 写在主协程串行）
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output,
                           tokens_in, tokens_out) VALUES ('extract',%s,%s,%s,%s,%s)""",
                        (res.model,
                         psycopg.types.json.Json({"document_id": doc_id,
                                                  "chars": len(text)}),
                         psycopg.types.json.Json({
                             "claims": res.claims, "entities": res.entities,
                             "lang": res.lang, "is_opinion": res.is_opinion,
                             "usage": res.usage, "error": res.error}),
                         res.tokens_in, res.tokens_out))
            if res.error:
                conn.commit()
                log.warning("doc %s: extract error: %s", doc_id, res.error)
                stats["errors"] += 1
                continue

            for cl in res.claims:
                struct = {k: cl.get(k) for k in ("who", "did", "whom", "when", "where")
                          if cl.get(k)}
                cur.execute("""INSERT INTO claims (document_id, text, struct, stance,
                               confidence, model_ver) VALUES (%s,%s,%s,%s,%s,%s)""",
                            (doc_id, cl["text"], psycopg.types.json.Json(struct),
                             cl["stance"], cl["confidence"], res.model))
            for ent in res.entities:
                eid = _upsert_entity(cur, ent["name"].strip(), ent["kind"])
                cur.execute("""INSERT INTO document_entities (document_id, entity_id)
                               VALUES (%s,%s) ON CONFLICT DO NOTHING""", (doc_id, eid))
            cur.execute("""UPDATE documents SET extracted_at=now(), extract_model=%s,
                           lang=coalesce(lang,%s),
                           meta = meta || %s
                           WHERE id=%s""",
                        (res.model, res.lang,
                         psycopg.types.json.Jsonb({"is_opinion": res.is_opinion}),
                         doc_id))
        conn.commit()
        stats["docs"] += 1
        stats["claims"] += len(res.claims)
        stats["entities"] += len(res.entities)
        log.info("doc %s: %d claims, %d entities", doc_id, len(res.claims),
                 len(res.entities))
    return stats
