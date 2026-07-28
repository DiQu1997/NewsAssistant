-- 005 · 合成层（阶段 4）：带引用的 running summary、时间线、开放问题
--
-- summary 从 text 升级为 jsonb：综述不是一段散文，是**每句带 claim 级引用**的
-- 结构（最高原则 5：无引用支撑的句子不允许出现 —— 结构上强制，不靠自觉）。
--   summary: {"sentences": [{"text": ..., "claim_ids": [..]}], "model": ...}
--   timeline: [{"when": ..., "what": ..., "claim_ids": [..]}]
--   open_questions: [{"question": ..., "why": ...}]
-- 001 的 summary 列从未被写入过；防御性起见非空旧值保留在 legacy_text。

ALTER TABLE stories
    ALTER COLUMN summary TYPE jsonb USING (
        CASE WHEN summary IS NULL THEN NULL
             ELSE jsonb_build_object('sentences', '[]'::jsonb,
                                     'legacy_text', summary) END),
    ADD COLUMN timeline jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN synthesized_at timestamptz;

-- 待合成候选的扫描路径：活跃、且自上次合成后有新文档
CREATE INDEX stories_synth_idx ON stories (updated_at)
    WHERE state = 'active';
