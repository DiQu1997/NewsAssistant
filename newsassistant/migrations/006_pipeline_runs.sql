-- 管线运行记录（服务化）：每个阶段每次执行一行。
-- 存在的理由有三个，都不是"日志好看"：
--   1. 节奏判定要跨进程重启存活 —— "上次成功跑 ingest 是什么时候"必须查库，
--      放进程内存里一崩溃就退化成"每次启动全跑一遍"。
--   2. 失败要可见 —— 阶段级隔离意味着一个阶段挂了整轮继续，
--      不落库就没人知道 synthesize 已经连续失败了六轮。
--   3. "这一轮做了什么"是运维的第一个问题，stats 直接存各阶段的返回统计。
-- cycle 把同一轮的各阶段串起来（nextval 取自 pipeline_cycle_seq）。

CREATE SEQUENCE IF NOT EXISTS pipeline_cycle_seq;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          bigserial PRIMARY KEY,
    cycle       bigint      NOT NULL,
    stage       text        NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    stats       jsonb,
    error       text
);

-- 节奏判定的唯一热查询：某阶段最近一次成功开始于何时
CREATE INDEX IF NOT EXISTS pipeline_runs_stage_idx
    ON pipeline_runs (stage, started_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_runs_cycle_idx
    ON pipeline_runs (cycle);
