-- 簇词表：频道子主题自下而上涌现，词表持久化保地图稳定（与实体消歧同构）。
-- yaml 里的 predefined 清单降级为冷启动种子（seeded=true）；之后系统自己长。
CREATE TABLE IF NOT EXISTS channel_topics (
    channel      TEXT NOT NULL,
    key          TEXT NOT NULL,     -- 稳定 slug，趋势按它积累
    name         TEXT NOT NULL,
    hint         TEXT NOT NULL DEFAULT '',   -- 一句话入簇标准（判定与展示共用）
    seeded       BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (channel, key)
);
