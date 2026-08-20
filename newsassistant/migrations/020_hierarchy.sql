-- V2 层级化事件体系（docs/redesign-hierarchy.md）
-- L2 新字段：summary / event_signature / importance / domains
-- L4 层级：nodes（arc/saga，自由递归）+ node_edges（多父 DAG）

-- ── 文档级（L2 单篇分析产出）─────────────────────────────
ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS event_signature text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS importance smallint;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS domains text[] NOT NULL DEFAULT '{}';

-- ── 故事级（L3 聚合：importance=旗下 max，domains=众数序）──
ALTER TABLE stories ADD COLUMN IF NOT EXISTS importance smallint;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS domains text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS stories_importance_idx
    ON stories (importance DESC NULLS LAST, updated_at DESC);

-- ── L4 层级节点（arc/saga 只是习惯叫法，机制不分级）────────
CREATE TABLE IF NOT EXISTS nodes (
    id             bigserial PRIMARY KEY,
    key            text NOT NULL UNIQUE,           -- slug，LLM 起，跨轮稳定
    name           text NOT NULL,                  -- ≤8 字中立命名
    hint           text NOT NULL,                  -- 一句话入簇标准
    domains        text[] NOT NULL DEFAULT '{}',   -- 六大域，第一个为主域
    importance     smallint,                       -- 后代闭包 max（sweep 维护）
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_active_at timestamptz NOT NULL DEFAULT now()
);

-- 多父 DAG 边：child 可以是 story（event 层）或 node（自由递归）
CREATE TABLE IF NOT EXISTS node_edges (
    parent_id  bigint NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    child_kind text NOT NULL CHECK (child_kind IN ('story', 'node')),
    child_id   bigint NOT NULL,
    reason     text,                                -- 归簇判据（审计）
    at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_id, child_kind, child_id)
);
CREATE INDEX IF NOT EXISTS node_edges_child_idx ON node_edges (child_kind, child_id);
