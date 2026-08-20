-- 选股漏斗：全集 → 雷达 → 关注清单。
-- universe：可投资池成分（周度刷新）；radar_hits：每日扫描命中及原因；
-- watchlist：全套监测席位 —— core（配置固定）/ rotating（雷达晋升，
-- 无信号自动衰减）/ banned（永不晋升）。
CREATE TABLE IF NOT EXISTS universe (
    symbol     text PRIMARY KEY,
    name       text NOT NULL,
    sector     text,
    indexes    text[] NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS radar_hits (
    id      bigserial PRIMARY KEY,
    day     date NOT NULL DEFAULT current_date,
    symbol  text NOT NULL,
    score   double precision NOT NULL,
    reasons jsonb NOT NULL,
    promoted boolean NOT NULL DEFAULT false,
    UNIQUE (day, symbol)
);
CREATE INDEX IF NOT EXISTS radar_hits_day_idx ON radar_hits (day DESC, score DESC);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol         text PRIMARY KEY,
    kind           text NOT NULL CHECK (kind IN ('core','rotating','banned')),
    pinned         boolean NOT NULL DEFAULT false,
    reason         text,
    added_at       timestamptz NOT NULL DEFAULT now(),
    last_signal_at timestamptz NOT NULL DEFAULT now()
);
