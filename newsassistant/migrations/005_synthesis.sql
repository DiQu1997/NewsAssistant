-- 合成层（阶段 4）：故事的综述 / 时间线 / 开放问题。
-- 三者都是 L3 派生产物（廉价可再生），但因为增量维护（上一版综述是下一版的
-- 输入）而落在 story 行上，不是独立表。每句综述必须带 claim 级引用 ——
-- 结构上体现为 jsonb 里的 claim_ids 数组，写入端强制校验（synth.py）。
--
-- 001 里 summary 是 text、open_questions 有 DEFAULT '[]'：换成可空 jsonb ——
-- 带引用结构的综述不是纯文本，NULL 明确表达"从未合成"（区别于"合成出空产物"）。
-- 两列在 001..004 期间从未被写入，drop+add 无数据损失。

ALTER TABLE stories
    DROP COLUMN IF EXISTS summary,
    DROP COLUMN IF EXISTS open_questions,
    DROP COLUMN IF EXISTS timeline,
    DROP COLUMN IF EXISTS synthesized_at;

ALTER TABLE stories
    ADD COLUMN summary        jsonb,        -- [{text, claim_ids[]}]
    ADD COLUMN timeline       jsonb,        -- [{when, what, claim_ids[]}]
    ADD COLUMN open_questions jsonb,        -- [text]
    ADD COLUMN synthesized_at timestamptz;  -- 与 updated_at 比较判断是否过期
