-- 阅读版本：整篇文章的双语重写（不浓缩、分主题小节、框架抽象）。
-- 与 reading_notes（快筛卡片）分层：notes 决定读不读，digest 替你读。
CREATE TABLE IF NOT EXISTS reading_digests (
    document_id bigint PRIMARY KEY REFERENCES documents(id),
    at          timestamptz NOT NULL DEFAULT now(),
    model       text,
    payload     jsonb NOT NULL
);
