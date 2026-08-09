"""L3 合成层 —— 故事的 running summary / 时间线 / 开放问题（docs/architecture.md §5）。

最高原则 5：**综述里无引用支撑的句子不允许出现。**
结构上的落点：模型必须为每句综述、每条时间线注明 claim id；orchestrator
校验引用（id 必须属于本故事、非空），无效引用的句子直接丢弃并计数 ——
引用不是装饰，是句子存在的许可证。

增量维护：上一版综述随 claims 一起喂给模型（"在此基础上更新"），
synthesized_at < updated_at 的故事视为过期。产物廉价可再生 ——
换模型/换提示词后全量重算是设计内操作。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import psycopg

from .llm_extract import DISALLOW_ALL_BUILTIN

log = logging.getLogger(__name__)

MAX_CLAIMS = 40          # 喂给模型的 claim 上限（新到旧）；超长故事先靠这个截断
MIN_DOCS = 2             # 单篇故事不合成：综述只会复述唯一一篇的 claims
COOLDOWN_HOURS = 12      # 重合成冷却，见 _stale_stories；测试传 0 可关掉

# ── 事件层结构化事实 ────────────────────────────────────────
# 数字本来就散在宣称里；这一层做的是**归拢与定型**，不是二次抽取。
# 争议槽位把官方值与估计值存成同级字段 —— NYT 处理超额死亡的做法：
# 官方数与估计数并列，差额自带名字，而不是把一个数塞进正文加脚注。

FACT_PROPS = {
    "type": "object",
    "properties": {
        "key": {"type": "string",
                "description": "槽位稳定标识，蛇形英文（death_toll / tariff_rate / "
                               "displaced）。**沿用上一版已有的 key，不要改名** —— "
                               "改名会让图表每次刷新都重置"},
        "label": {"type": "string", "description": "中文显示名（死亡人数 / 关税税率）"},
        "kind": {"type": "string", "enum": ["single", "disputed", "unknown"],
                 "description": "single=各来源口径一致；disputed=存在两个及以上"
                                "不可调和的口径；unknown=这类事件本该有此数但报道"
                                "尚未给出（会自动成为未解问题）"},
        "unit": {"type": "string", "description": "单位（人 / % / 亿美元），无单位留空"},
        "value": {"type": "number", "description": "kind=single 时的值"},
        "estimates": {"type": "array", "description": "kind=disputed 时的各方口径，"
                                                      "**不要取平均、不要裁决谁对**",
                      "items": {"type": "object", "properties": {
                          "value": {"type": "number"},
                          "source": {"type": "string",
                                     "description": "谁给的这个数（加沙卫生部 / 世卫组织 / "
                                                    "本社测算），必须具名"},
                          "method": {"type": "string",
                                     "description": "怎么算出来的（官方登记 / 超额死亡模型 / "
                                                    "媒体逐例统计），不知道就留空"},
                      }, "required": ["value", "source"]}},
        "gap_label": {"type": "string",
                      "description": "kind=disputed 时给差额本身起的名字"
                                     "（'高于官方通报的部分'），让差额成为可读对象"},
        "scope_excludes": {"type": "string",
                           "description": "该数字明确不覆盖什么（'未计入营养不良与"
                                          "医疗系统崩溃导致的死亡'）。没有就留空"},
        "as_of": {"type": "string", "description": "该值的时点，ISO 日期或原文表述"},
        "claim_ids": {"type": "array", "items": {"type": "integer"},
                      "description": "支撑本槽位的宣称 id（≥1）"},
    },
    "required": ["key", "label", "kind", "claim_ids"],
}

# ── 图元规格 ────────────────────────────────────────────────
# 意图在前、图型在后（FT Visual Vocabulary 的方法）。图型清单只收
# 新闻图表里真正的工作马 —— 桑基/弦图/地图/不确定性锥全部不做，
# 前三者在新闻编辑部里近乎不存在，后者实测有 69% 的读者读反。

VIEW_TYPES = ["numbers", "line_baseline", "bars_rolling", "swimlane", "waffle",
              "matrix", "slope", "dumbbell", "bars", "stacked", "beeswarm",
              "stepper", "revision"]

VIEW_PROPS = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": VIEW_TYPES, "description": """图型：
- numbers 关键数字盘：1-4 个核心读数；争议槽位在这里渲染成官方/估计并列
- line_baseline 折线+基准带：一条量随时间，可带常态基准（超额死亡就是这个）
- bars_rolling 日柱+均线：嘈杂的日频量（新增病例/伤亡），柱是原始、线是均值
- swimlane 泳道时间线：**多方并行**（谈判各方/法律各条线/预警与疏散两条道），
  同时性是重点时用它；每条泳道一个主体，事件有 end 画条、无 end 画点
- waffle 华夫格：每 N 人里有几个，读者要能数出来（≤400 个单位）
- matrix 实体×实体矩阵：双边数值（国家×国家关税/制裁）
- slope 斜率图：**恰好两个时间点**、多个主体、同一刻度（谈判前后、制裁前后）
- dumbbell 哑铃图：同一主体两个值之间的差距，排序后即排名
- bars 排序条：单一指标跨主体比较
- stacked 堆叠贡献：总量由哪些部分构成（≤6 层）
- beeswarm 蜂群图：一个点一个主体，看分布同时能找到特定那个（≥20 个点）
- stepper 阶段进度：有程序节点的事（谈判轮次/立法进程/停火分阶段）
- revision 修订史：同一个数字被反复上修的轨迹（伤亡数字最典型）——
  与其画一条我们无法校准的置信带，不如画出它自己被改过几次"""},
        "intent": {"type": "string",
                   "enum": ["随时间变化", "偏离", "排名", "分布", "量级",
                            "部分与整体", "相关", "流动"],
                   "description": "这张图要表达的数据关系。先定意图再选图型"},
        "title": {"type": "string",
                  "description": "**标题即发现**：用动词说出这张图证明了什么"
                                 "（'伤亡数字四天里被上修了三次'），不要写"
                                 "'伤亡情况统计'这种标签式标题。读者记住的是标题"
                                 "不是图，所以标题只能断言图上看得见的东西"},
        "unit": {"type": "string", "description": "数值单位，必填（无单位写'次'等）"},
        "note": {"type": "string", "description": "口径与来源说明，一句话"},
        "annotations": {"type": "array", "description": "标注 2-3 个关键点——"
                                                        "标注层比图型更重要",
                        "items": {"type": "object", "properties": {
                            "at": {"type": "string", "description": "锚点（x 值或主体名）"},
                            "text": {"type": "string", "description": "这一点为何重要"},
                        }, "required": ["at", "text"]}},
        "baseline": {"type": "number", "description": "line_baseline 的常态基准值"},
        "baseline_label": {"type": "string", "description": "基准的名字（'往年同期均值'）"},
        "points": {"type": "array", "description": "line_baseline/bars_rolling/"
                                                   "revision 的数据点",
                   "items": {"type": "object", "properties": {
                       "x": {"type": "string", "description": "时间/序号"},
                       "y": {"type": "number"},
                       "source": {"type": "string", "description": "revision 用：谁改的"},
                   }, "required": ["x", "y"]}},
        "items": {"type": "array", "description": "bars/dumbbell/waffle/beeswarm/"
                                                  "stacked/slope 的条目",
                  "items": {"type": "object", "properties": {
                      "label": {"type": "string"},
                      "value": {"type": "number"},
                      "value2": {"type": "number",
                                 "description": "dumbbell/slope 的第二个值（后期值）"},
                      "group": {"type": "string", "description": "分组/分层名"},
                  }, "required": ["label", "value"]}},
        "x_labels": {"type": "array", "items": {"type": "string"},
                     "description": "slope/dumbbell 的两端名称（如 ['加税前','加税后']）"},
        "lanes": {"type": "array", "description": "swimlane 的泳道，一个主体一条",
                  "items": {"type": "object", "properties": {
                      "actor": {"type": "string", "description": "主体（国家/机构/当事方）"},
                      "events": {"type": "array", "items": {"type": "object",
                                 "properties": {
                                     "start": {"type": "string"},
                                     "end": {"type": "string",
                                             "description": "有持续时间才填；"
                                                            "**瞬时事件必须留空**，"
                                                            "填了就是在虚构持续时间"},
                                     "label": {"type": "string"},
                                 }, "required": ["start", "label"]}},
                  }, "required": ["actor", "events"]}},
        "matrix": {"type": "object", "description": "matrix 的数据",
                   "properties": {
                       "rows": {"type": "array", "items": {"type": "string"}},
                       "cols": {"type": "array", "items": {"type": "string"}},
                       "cells": {"type": "array", "items": {"type": "object",
                                 "properties": {
                                     "r": {"type": "string"}, "c": {"type": "string"},
                                     "v": {"type": "number"},
                                 }, "required": ["r", "c", "v"]}},
                   }},
        "steps": {"type": "array", "description": "stepper 的阶段",
                  "items": {"type": "object", "properties": {
                      "label": {"type": "string"},
                      "status": {"type": "string",
                                 "enum": ["done", "current", "pending", "failed"]},
                      "at": {"type": "string"},
                  }, "required": ["label", "status"]}},
        "fact_keys": {"type": "array", "items": {"type": "string"},
                      "description": "numbers 引用的 facts 槽位 key"},
        "unit_icon": {"type": "string", "enum": ["person", "square"],
                      "description": "waffle 的单位图形；人命相关用 person"},
        "unit_each": {"type": "number",
                      "description": "waffle 每个图形代表多少（1 个=N 人）"},
        "claim_ids": {"type": "array", "items": {"type": "integer"},
                      "description": "支撑本图数据的宣称 id（≥1）"},
    },
    "required": ["type", "intent", "title", "claim_ids"],
}

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string", "description": "一句综述，中立、具体"},
            "claim_ids": {"type": "array", "items": {"type": "integer"},
                          "description": "支撑这句话的 claim id（≥1，必须出自给定列表）"},
        }, "required": ["text", "claim_ids"]}},
        "timeline": {"type": "array", "items": {"type": "object", "properties": {
            "when": {"type": "string",
                     "description": "时间锚点，ISO 日期或原文的时间表述"},
            "what": {"type": "string", "description": "该时点发生的状态变化，一句话"},
            "claim_ids": {"type": "array", "items": {"type": "integer"}},
        }, "required": ["when", "what", "claim_ids"]}},
        "open_questions": {"type": "array", "items": {"type": "string"},
                           "description": "现有报道未回答的具体问题（不超过 5 条）"},
        "facts": {"type": "array", "items": FACT_PROPS},
        "views": {"type": "array", "items": VIEW_PROPS},
    },
    "required": ["summary", "timeline", "open_questions", "facts", "views"],
}

SYNTH_PROMPT = """你是情报系统的合成器。给你一个故事的标题、按时间排列的宣称
（每条带 id、立场、来源），可能还有上一版综述。你必须调用 submit_synthesis
工具一次性提交产物，除此之外不做任何事。

规则：
- **每句综述、每条时间线必须在 claim_ids 里注明支撑它的宣称 id**。
  没有宣称支撑的话一个字都不能写 —— 无引用的句子会被系统直接丢弃。
- 只综合给定宣称的内容，不引入外部知识，不推测。
- 来源之间有分歧时**呈现分歧**（"A 称 X，B 称 Y"），不要裁决谁对。
- 综述 3-6 句：先事件核心（发生了什么、主体、时间地点），再最新进展，
  再分歧或未证实之处。有上一版时在其基础上更新，不推倒重写。
- 时间线只收**状态变化**（伤亡数字更新、立场转变、程序节点），
  不收纯背景；when 用宣称里的时间表述，没有就不编。
- open_questions 是现有报道**明确缺失**的具体信息（"死者身份尚未公布"），
  不是泛泛的"事态将如何发展"。

facts（事件层结构化事实）：
- 数字已经散在宣称里，你的活是**归拢定型**，不是重新发明。只收这个事件
  真正的关键量（伤亡、金额、税率、轮次、影响人数），3-8 个为宜。
- **key 必须复用上一版已有的**。同一个槽位这次叫 death_toll 下次叫 fatalities，
  图表就会每次刷新都重置。上一版给了什么 key，就接着用什么。
- 各来源口径不一致时 kind='disputed'，把每一方的数、**谁给的、怎么算的**
  分别列进 estimates。**绝不取平均，绝不裁决谁对** —— 分歧本身就是信息。
- 这类事件本该有、但报道还没给的数，写成 kind='unknown'（不要编数）。
  空槽位会自动变成未解问题，这比你去猜一个数有用得多。
- scope_excludes：如果某个数明确不覆盖某类情况，写出来。
- 每个槽位都要 claim_ids —— 没有出处的数字会被系统丢弃。

views（图元规格）：
- **先定意图，再选图型**：这张图要表达的是"随时间变化"还是"排名"还是
  "部分与整体"？意图定了，图型基本就定了。
- **标题即发现**：用动词写出这张图证明了什么，而不是给图贴标签。读者
  记住的是标题不是图，所以标题只能断言图上**看得见**的东西——如果你想说的
  是一个细微拐点而图上最扎眼的是前面那个尖峰，读者会丢掉标题记住尖峰。
- **标注 2-3 个关键点**。标注层比选对图型更重要：在散点上标三个点，
  不熟悉散点图的人也读懂了；不标注，就是"数据在这儿，你自己看吧"。
- **宁可不画**：数据撑不起图就别出。硬性下限——折线/柱状至少 3 个点，
  斜率图恰好 2 个时间点且至少 3 个主体，泳道至少 2 个主体，蜂群至少 20 个点，
  矩阵至少 2×2，堆叠最多 6 层，华夫格总数不超过 400。达不到就不要这张图，
  时间线和宣称墙本来就够好。**两个数据点的折线图比不画更糟。**
- **趋势要慎言**：少于 10 个点不要在标题里断言趋势。"连续几期上升"是最不
  可靠的判据，别用它下结论。
- **累计值会抹掉好消息**：读者不会自己做微分，你画什么他信什么。伤亡/病例
  这类量默认画**日增**（bars_rolling），累计数放进 numbers 盘里当一个大数字。
- 一个事件 1-3 张图，宁少勿滥。真的没什么可画的就给空数组——
  大多数事件确实没有值得画的图，硬画出来的图是噪声。
- 每张图都要 claim_ids、unit、note（口径与来源）。"""


@dataclass
class Synthesis:
    summary: list[dict] = field(default_factory=list)      # {text, claim_ids}
    timeline: list[dict] = field(default_factory=list)     # {when, what, claim_ids}
    open_questions: list[str] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)        # 类型化槽位
    views: list[dict] = field(default_factory=list)        # 图元规格
    model: str = "unknown"
    usage: dict | None = None
    error: str | None = None


@dataclass
class StoryView:
    id: int
    title: str
    claims: list[dict] = field(default_factory=list)   # {id, text, stance, source, at}
    prev_summary: list[dict] | None = None
    prev_facts: list[dict] | None = None    # 槽位 key 复用：喂回去防改名


class Synthesizer(Protocol):
    async def synthesize(self, story: StoryView) -> Synthesis: ...


class ClaudeSynthesizer:
    """Agent SDK 实现 —— 唯一工具强 schema，捕获状态 per-call（并发竞态教训）。"""

    def __init__(self, model: str | None = None):
        from claude_agent_sdk import query   # 仅探测依赖可导入
        self._model = model

    @staticmethod
    def _render(s: StoryView) -> str:
        parts = [f"## 故事：{s.title}", "\n## 宣称（旧→新）"]
        parts += [f"[{c['id']}] {c['text']}（立场 {c['stance']:+d}，"
                  f"源 {c['source']}，{c['at']}）" for c in s.claims]
        if s.prev_summary:
            parts += ["\n## 上一版综述（在此基础上更新）"]
            parts += [x.get("text", "") for x in s.prev_summary]
        if s.prev_facts:
            # 槽位 key 复用：不喂回去，模型每轮换个名字，图表就永远在重置
            parts += ["\n## 上一版事实槽位（**沿用这些 key**，有新值就更新）"]
            parts += [f"{f.get('key')} = {f.get('label')}（{f.get('kind')}）"
                      for f in s.prev_facts if isinstance(f, dict)]
        return "\n".join(parts)

    async def synthesize(self, story: StoryView) -> Synthesis:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                                      ResultMessage, create_sdk_mcp_server,
                                      query, tool)
        captured: dict = {}

        @tool("submit_synthesis", "一次性提交综述/时间线/开放问题", SYNTH_SCHEMA)
        async def submit(args):
            captured.clear()
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        server = create_sdk_mcp_server(name="synth", version="1.0", tools=[submit])
        options = ClaudeAgentOptions(
            system_prompt=SYNTH_PROMPT,
            mcp_servers={"sy": server},
            allowed_tools=["mcp__sy__submit_synthesis"],
            disallowed_tools=DISALLOW_ALL_BUILTIN,
            model=self._model,
            max_turns=6,
        )
        model, usage, err = self._model or "unknown", None, None
        async for msg in query(prompt=self._render(story), options=options):
            if isinstance(msg, AssistantMessage):
                model = msg.model or model   # ResultMessage 无 model 字段，只能从这里拿
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None) or {}
                if msg.is_error:
                    err = str(msg.result)[:500]
        if not captured and not err:
            err = "model did not call submit_synthesis"
        return Synthesis(
            summary=[x for x in captured.get("summary", []) if isinstance(x, dict)],
            timeline=[x for x in captured.get("timeline", []) if isinstance(x, dict)],
            open_questions=[q for q in captured.get("open_questions", [])
                            if isinstance(q, str)][:5],
            facts=[x for x in captured.get("facts", []) if isinstance(x, dict)],
            views=[x for x in captured.get("views", []) if isinstance(x, dict)],
            model=model, usage=usage, error=err)


# ── 选取与渲染输入 ──────────────────────────────────────────

def _stale_stories(conn: psycopg.Connection, limit: int,
                   min_docs: int = MIN_DOCS,
                   cooldown_hours: int = COOLDOWN_HOURS) -> list[StoryView]:
    """待合成 = 活跃、多篇、且从未合成或合成后又有更新的故事，按文档数降序。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id, s.title, s.summary, s.facts
            FROM stories s
            WHERE s.state='active'
              AND (s.synthesized_at IS NULL OR s.updated_at > s.synthesized_at)
              -- 重合成冷却：热故事每 2h 吸新文档，无冷却会被整天反复重写
              -- （实测单故事一天 6 次，占掉 synthesize 八成 opus 消耗）
              AND (s.synthesized_at IS NULL
                   OR s.synthesized_at < now() - make_interval(hours => %s))
              AND (SELECT count(*) FROM story_documents sd
                   WHERE sd.story_id=s.id) >= %s
            ORDER BY (s.scalars->>'docs')::int DESC NULLS LAST, s.id
            LIMIT %s""", (cooldown_hours, min_docs, limit))
        stories = [StoryView(id=r[0], title=r[1], prev_summary=r[2],
                             prev_facts=r[3])
                   for r in cur.fetchall()]
        for s in stories:
            cur.execute("""
                SELECT c.id, c.text, coalesce(c.stance,0), src.key,
                       coalesce(to_char(d.published_at,'YYYY-MM-DD'), '?')
                FROM claims c
                JOIN documents d ON d.id=c.document_id
                JOIN sources src ON src.id=d.source_id
                WHERE c.story_id=%s
                ORDER BY d.published_at NULLS LAST, c.id
                LIMIT %s""", (s.id, MAX_CLAIMS))
            s.claims = [{"id": r[0], "text": r[1], "stance": r[2],
                         "source": r[3], "at": r[4]} for r in cur.fetchall()]
    return stories


# 每种图型的最小数据量。低于此就不画 —— 两个数据点的折线图比不画更糟，
# 而模型判断"数据够不够"并不可靠（实测：渲染成功但语义错误的比例是
# 渲染失败的六倍），所以门槛写在规则层，不写在提示词里。
_VIEW_GATES: dict[str, callable] = {
    "line_baseline": lambda v: len(v.get("points") or []) >= 3,
    "bars_rolling": lambda v: len(v.get("points") or []) >= 3,
    "revision": lambda v: len(v.get("points") or []) >= 2,
    # 斜率图的定义就是恰好两个时点、多个主体共享一把刻度
    "slope": lambda v: (len(v.get("x_labels") or []) == 2
                        and len([i for i in (v.get("items") or [])
                                 if i.get("value2") is not None]) >= 3),
    "dumbbell": lambda v: len([i for i in (v.get("items") or [])
                               if i.get("value2") is not None]) >= 2,
    "bars": lambda v: len(v.get("items") or []) >= 2,
    "stacked": lambda v: (len(v.get("items") or []) >= 2
                          and len({i.get("group") for i in v["items"]}) <= 6),
    # 蜂群图低于 20 个点就是画得很差的点图，直接用 bars
    "beeswarm": lambda v: len(v.get("items") or []) >= 20,
    "waffle": lambda v: (v.get("items")
                         and 0 < sum(max(i.get("value") or 0, 0)
                                     for i in v["items"]) <= 400),
    "matrix": lambda v: (len((v.get("matrix") or {}).get("rows") or []) >= 2
                         and len((v.get("matrix") or {}).get("cols") or []) >= 2
                         and (v.get("matrix") or {}).get("cells")),
    # 泳道的全部理由是"同时性"，单主体没有同时性可言
    "swimlane": lambda v: (len(v.get("lanes") or []) >= 2
                           and sum(len(l.get("events") or [])
                                   for l in v["lanes"]) >= 3),
    "stepper": lambda v: len(v.get("steps") or []) >= 2,
    "numbers": lambda v: bool(v.get("fact_keys") or v.get("items")),
}
# 需要单位的图型（stepper/swimlane 画的是事件不是量，无单位合法）
_NEEDS_UNIT = {"line_baseline", "bars_rolling", "revision", "slope", "dumbbell",
               "bars", "stacked", "beeswarm", "waffle", "matrix"}


def _enforce_facts(facts: list[dict], valid_ids: set[int]
                   ) -> tuple[list[dict], int]:
    """事实槽位校验：出处必须有效；有值的槽位必须真的有值；
    disputed 必须给出 ≥2 个具名口径（只有一个口径就不叫争议）。"""
    kept, dropped = [], 0
    seen_keys: set[str] = set()
    for f in facts:
        key, kind = f.get("key"), f.get("kind")
        ids = [i for i in f.get("claim_ids", []) if isinstance(i, int)]
        if not (key and f.get("label") and kind in ("single", "disputed", "unknown")):
            dropped += 1
            continue
        if key in seen_keys or not ids or not set(ids) <= valid_ids:
            dropped += 1
            continue
        ests = [e for e in (f.get("estimates") or [])
                if isinstance(e, dict) and e.get("value") is not None
                and e.get("source")]
        if kind == "single" and f.get("value") is None:
            dropped += 1
            continue
        if kind == "disputed" and len(ests) < 2:
            dropped += 1        # 单一口径不是争议，退不回 single 就丢弃
            continue
        seen_keys.add(key)
        out = {k: f[k] for k in ("key", "label", "kind", "unit", "value",
                                 "gap_label", "scope_excludes", "as_of")
               if f.get(k) not in (None, "")}
        out["claim_ids"] = ids
        if kind == "disputed":
            out["estimates"] = ests
        kept.append(out)
    return kept, dropped


def _enforce_views(views: list[dict], valid_ids: set[int], fact_keys: set[str]
                   ) -> tuple[list[dict], int]:
    """图元校验：类型合法、出处有效、标题非空、单位齐备、数据量过门槛。
    任何一条不过就丢弃这张图 —— 图表比散文更容易被当成权威，
    所以宁可不画。"""
    kept, dropped = [], 0
    for v in views:
        t = v.get("type")
        ids = [i for i in v.get("claim_ids", []) if isinstance(i, int)]
        if t not in _VIEW_GATES or not v.get("title") or not v.get("intent"):
            dropped += 1
            continue
        if not ids or not set(ids) <= valid_ids:
            dropped += 1
            continue
        if t in _NEEDS_UNIT and not v.get("unit"):
            dropped += 1
            continue
        try:
            ok = _VIEW_GATES[t](v)
        except (TypeError, AttributeError, KeyError):
            ok = False
        if not ok:
            dropped += 1
            continue
        if t == "numbers":
            # 只保留真的存在的槽位引用，全空则这张图没有内容
            fk = [k for k in (v.get("fact_keys") or []) if k in fact_keys]
            if not fk and not v.get("items"):
                dropped += 1
                continue
            v = {**v, "fact_keys": fk}
        v = {**v, "claim_ids": ids,
             "annotations": [a for a in (v.get("annotations") or [])
                             if isinstance(a, dict) and a.get("at")
                             and a.get("text")]}
        kept.append({k: x for k, x in v.items() if x not in (None, "", [])})
    return kept, dropped


def _enforce_citations(items: list[dict], valid_ids: set[int],
                       keys: tuple[str, ...]) -> tuple[list[dict], int]:
    """引用校验：claim_ids 必须非空且全部属于本故事。违规条目丢弃。"""
    kept, dropped = [], 0
    for it in items:
        ids = [i for i in it.get("claim_ids", []) if isinstance(i, int)]
        if ids and set(ids) <= valid_ids and all(it.get(k) for k in keys):
            kept.append({**{k: it[k] for k in keys}, "claim_ids": ids})
        else:
            dropped += 1
    return kept, dropped


# ── orchestrator ────────────────────────────────────────────

async def run_synthesis(conn: psycopg.Connection, synthesizer: Synthesizer,
                        limit: int = 10, min_docs: int = MIN_DOCS,
                        cooldown_hours: int = COOLDOWN_HOURS) -> dict:
    stats = {"stories": 0, "sentences": 0, "facts": 0, "views": 0,
             "dropped": 0, "errors": 0}
    for story in _stale_stories(conn, limit, min_docs, cooldown_hours):
        res = await synthesizer.synthesize(story)
        with conn.cursor() as cur:
            # 审计先行：调用本身（含失败）永远落库
            cur.execute("""INSERT INTO llm_calls (purpose, model, input, output)
                           VALUES ('synthesize',%s,%s,%s)""",
                        (res.model,
                         psycopg.types.json.Json({
                             "story_id": story.id,
                             "claims": [c["id"] for c in story.claims]}),
                         psycopg.types.json.Json({
                             "summary": res.summary, "timeline": res.timeline,
                             "open_questions": res.open_questions,
                             "facts": res.facts, "views": res.views,
                             "usage": res.usage, "error": res.error})))
            if res.error:
                conn.commit()
                stats["errors"] += 1
                log.warning("story %s: synthesis error: %s", story.id, res.error)
                continue

            valid = {c["id"] for c in story.claims}
            summary, drop_s = _enforce_citations(res.summary, valid, ("text",))
            timeline, drop_t = _enforce_citations(res.timeline, valid,
                                                  ("when", "what"))
            if not summary:
                # 全部句子引用无效 = 本次合成不可用；不覆盖旧版
                conn.commit()
                stats["errors"] += 1
                log.warning("story %s: all %d sentences dropped (bad citations)",
                            story.id, len(res.summary))
                continue

            facts, drop_f = _enforce_facts(res.facts, valid)
            views, drop_v = _enforce_views(res.views, valid,
                                           {f["key"] for f in facts})
            # 空槽位即未解问题：schema 说这类事件本该有的数还没有 —— 比模型
            # 自己联想出来的问题更硬，因为它来自结构
            open_qs = list(res.open_questions)
            for f in facts:
                if f["kind"] == "unknown":
                    q = f"{f['label']}尚未有可引用的数字"
                    if q not in open_qs:
                        open_qs.append(q)

            cur.execute("""UPDATE stories SET summary=%s, timeline=%s,
                           open_questions=%s, facts=%s, views=%s,
                           synthesized_at=now() WHERE id=%s""",
                        (psycopg.types.json.Jsonb(summary),
                         psycopg.types.json.Jsonb(timeline),
                         psycopg.types.json.Jsonb(open_qs),
                         psycopg.types.json.Jsonb(facts),
                         psycopg.types.json.Jsonb(views), story.id))
            cur.execute("""INSERT INTO story_events (story_id, kind, payload)
                           VALUES (%s,'synthesized',%s)""",
                        (story.id, psycopg.types.json.Jsonb({
                            "model": res.model, "sentences": len(summary),
                            "timeline": len(timeline), "facts": len(facts),
                            "views": len(views),
                            "dropped": drop_s + drop_t + drop_f + drop_v})))
        conn.commit()
        stats["stories"] += 1
        stats["sentences"] += len(summary)
        stats["facts"] += len(facts)
        stats["views"] += len(views)
        stats["dropped"] += drop_s + drop_t + drop_f + drop_v
        log.info("story %s: %d sentences, %d timeline, %d facts, %d views, "
                 "%d dropped", story.id, len(summary), len(timeline),
                 len(facts), len(views), drop_s + drop_t + drop_f + drop_v)
    return stats
