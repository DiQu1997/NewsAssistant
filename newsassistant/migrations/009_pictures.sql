-- 态势图：分析员每日产出的完整 picture（剧场/观点/自我修正），整份 JSON 存档。
-- 观点账本就在历史 payload 里 —— 下一次生成时取最近一份的 opinions 做对照复盘。
CREATE TABLE IF NOT EXISTS pictures (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    model   text,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS pictures_at_idx ON pictures (at DESC);
