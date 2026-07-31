-- 行情信号层：K 线缓存 + 每轮的派生快照（指标/信号/期权面）。
-- 快照保留历史（信号出现/消失本身就是信息），页面读各 symbol 最新一条。
CREATE TABLE IF NOT EXISTS market_bars (
    symbol text NOT NULL,
    day    date NOT NULL,
    open   double precision, high double precision,
    low    double precision, close double precision,
    volume bigint,
    PRIMARY KEY (symbol, day)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    symbol  text NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS market_snapshots_sym_at_idx
    ON market_snapshots (symbol, at DESC);
