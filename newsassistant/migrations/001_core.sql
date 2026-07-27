-- 001_core · 核心 schema（docs/architecture.md §2）
-- 原则：硬编码结构，永不硬编码主题。这里只有通用类型，没有任何领域词汇。
-- 向量列（pgvector）留待 002，避免开发环境没有扩展时起不来。

-- ── 源注册表（docs/sources.md）─────────────────────────────
CREATE TABLE sources (
    id              serial PRIMARY KEY,
    key             text NOT NULL UNIQUE,          -- 稳定标识，如 "guardian-world"
    name            text NOT NULL,
    kind            text NOT NULL,                 -- rss | api | sitemap | bulk | crawl
    url             text NOT NULL,
    evidence_tier   smallint NOT NULL CHECK (evidence_tier BETWEEN 1 AND 7),
    cadence_minutes integer NOT NULL DEFAULT 60,   -- 期望拉取间隔
    revises         boolean NOT NULL DEFAULT false,-- 是否事后修订（统计数据会，判决不会）
    lang            text,
    region          text,
    legal           jsonb NOT NULL DEFAULT '{}',   -- 许可 / robots / 速率 / 可否再分发
    notes           text,
    enabled         boolean NOT NULL DEFAULT true,
    -- 拉取状态（条件请求缓存）
    etag            text,
    last_modified   text,
    last_fetch_at   timestamptz,
    last_status     text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ── L0 · 文档（正文存文件，库里存指针）──────────────────────
CREATE TABLE documents (
    id              bigserial PRIMARY KEY,
    source_id       integer NOT NULL REFERENCES sources(id),
    url             text NOT NULL,
    url_canonical   text NOT NULL UNIQUE,
    title           text,
    author          text,
    published_at    timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    content_ref     text,                          -- 内容寻址路径（sha256 前缀分桶）
    content_sha256  text,                          -- 精确去重
    simhash         bigint,                        -- 近重 / 转述候选
    lang            text,
    status          text NOT NULL DEFAULT 'ok',    -- ok | dup_exact | near_dup | fetch_failed | extract_failed
    near_dup_of     bigint REFERENCES documents(id),
    syndication_of  bigint REFERENCES documents(id), -- 转述溯源（阶段 3 裁决后填写）
    meta            jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX documents_source_idx    ON documents (source_id, fetched_at DESC);
CREATE INDEX documents_published_idx ON documents (published_at DESC);
CREATE INDEX documents_sha_idx       ON documents (content_sha256);
CREATE INDEX documents_simhash_idx   ON documents (simhash);

-- ── L1 · 抽取原子（阶段 2 开始写入；结构先建全）─────────────
CREATE TABLE entities (
    id              bigserial PRIMARY KEY,
    canonical_name  text NOT NULL,
    kind            text NOT NULL,                 -- org | person | product | place | ...
    aliases         text[] NOT NULL DEFAULT '{}',
    merged_into     bigint REFERENCES entities(id),-- 消歧合并指向
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX entities_name_idx ON entities (canonical_name);

CREATE TABLE claims (
    id              bigserial PRIMARY KEY,
    document_id     bigint NOT NULL REFERENCES documents(id),
    story_id        bigint,                        -- FK 加在 stories 建表后
    text            text NOT NULL,
    struct          jsonb NOT NULL DEFAULT '{}',   -- who / did / to-whom / when / where
    stance          smallint CHECK (stance BETWEEN -2 AND 2),
    confidence      real,
    extracted_at    timestamptz NOT NULL DEFAULT now(),
    model_ver       text
);
CREATE INDEX claims_document_idx ON claims (document_id);

-- ── L2 · Story 状态（event-sourcing）────────────────────────
CREATE TABLE stories (
    id              bigserial PRIMARY KEY,
    state           text NOT NULL DEFAULT 'active',-- active | dormant | archived
    title           text NOT NULL,
    summary         text,
    open_questions  jsonb NOT NULL DEFAULT '[]',
    scalars         jsonb NOT NULL DEFAULT '{}',   -- velocity / breadth / consensus / novelty / uncertainty / stage
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE claims ADD CONSTRAINT claims_story_fk
    FOREIGN KEY (story_id) REFERENCES stories(id);

CREATE TABLE story_documents (
    story_id    bigint NOT NULL REFERENCES stories(id),
    document_id bigint NOT NULL REFERENCES documents(id),
    added_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (story_id, document_id)
);
CREATE TABLE story_entities (
    story_id  bigint NOT NULL REFERENCES stories(id),
    entity_id bigint NOT NULL REFERENCES entities(id),
    role      text,
    PRIMARY KEY (story_id, entity_id)
);
-- append-only 更新日志：系统必须能回答"为什么这篇被归到这个故事"
CREATE TABLE story_events (
    id       bigserial PRIMARY KEY,
    story_id bigint NOT NULL REFERENCES stories(id),
    kind     text NOT NULL,        -- created | absorbed | split | merged | anchored | updated
    payload  jsonb NOT NULL DEFAULT '{}',
    at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX story_events_story_idx ON story_events (story_id, at);

-- ── 审计：每次 LLM 调用全落库（可审计是底线，不是加分项）────
CREATE TABLE llm_calls (
    id         bigserial PRIMARY KEY,
    purpose    text NOT NULL,      -- extract | assign | synthesize | ...
    model      text NOT NULL,
    input      jsonb NOT NULL,
    output     jsonb,
    tokens_in  integer,
    tokens_out integer,
    at         timestamptz NOT NULL DEFAULT now()
);

-- ── 采集可观测 ──────────────────────────────────────────────
CREATE TABLE fetch_log (
    id          bigserial PRIMARY KEY,
    source_id   integer NOT NULL REFERENCES sources(id),
    at          timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    outcome     text NOT NULL,     -- ok | not_modified | error
    new_docs    integer NOT NULL DEFAULT 0,
    dup_docs    integer NOT NULL DEFAULT 0,
    note        text
);
CREATE INDEX fetch_log_source_idx ON fetch_log (source_id, at DESC);
