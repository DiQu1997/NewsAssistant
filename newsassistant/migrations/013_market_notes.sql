-- 个股分析报告：分析员（opus）按需生成的单票 note —— 评级/论点/setup
-- （触发、失效、目标）/三面解读。保留历史：评级变化本身是信号。
CREATE TABLE IF NOT EXISTS market_notes (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    symbol  text NOT NULL,
    model   text,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS market_notes_sym_at_idx ON market_notes (symbol, at DESC);
