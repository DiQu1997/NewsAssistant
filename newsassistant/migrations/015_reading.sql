-- 阅读板块：论文/博客不是"事件"，不进故事归并 —— 它们是待消化的知识。
-- sources.section 标记板块归属（news 默认 / reading）；reading_notes 存
-- 每篇的预消化结果（摘要/标签/重要度/为什么值得读），一篇一行。
ALTER TABLE sources ADD COLUMN IF NOT EXISTS section text NOT NULL DEFAULT 'news';

CREATE TABLE IF NOT EXISTS reading_notes (
    document_id bigint PRIMARY KEY REFERENCES documents(id),
    at          timestamptz NOT NULL DEFAULT now(),
    model       text,
    payload     jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS reading_notes_at_idx ON reading_notes (at DESC);
