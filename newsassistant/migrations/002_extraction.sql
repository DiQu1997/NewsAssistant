-- 002_extraction · 抽取层（阶段 2）
-- documents 增加抽取状态；实体↔文档倒排表（阶段 3 召回的三路之一）。
-- 向量列仍然推迟：留给需要 pgvector 的召回迁移。

ALTER TABLE documents ADD COLUMN extracted_at  timestamptz;
ALTER TABLE documents ADD COLUMN extract_model text;
CREATE INDEX documents_unextracted_idx
    ON documents (id) WHERE status = 'ok' AND extracted_at IS NULL;

-- 简单唯一性：同名同类实体只建一条（真正的消歧 —— 别名、合并 —— 是阶段 3 的
-- 召回 + 裁决；这里只保证抽取端不产生平凡重复）。
CREATE UNIQUE INDEX entities_name_kind_uidx
    ON entities (lower(canonical_name), kind) WHERE merged_into IS NULL;

CREATE TABLE document_entities (
    document_id bigint NOT NULL REFERENCES documents(id),
    entity_id   bigint NOT NULL REFERENCES entities(id),
    PRIMARY KEY (document_id, entity_id)
);
CREATE INDEX document_entities_entity_idx ON document_entities (entity_id);
