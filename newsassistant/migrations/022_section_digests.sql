-- 板块综述（section_digest，docs/design-handoff）：每域一段模型写的话，
-- 说这半天发生了什么、共同主题是什么。首页 5a 板块综述行、板块页 5b 板块头共用。
--
-- 廉价可再生：每 12h（搭 synthesize 的 8:00/20:00 车）覆盖重算，随故事合成过期。
-- has_new / new_claims 由确定性活动量（近 12h 新增断言数）算出，不信模型 ——
-- 无新事件必须如实说，模型改不了这个标记，只负责把话写老实。
-- text 每句带 claim_ids，沿用综述的最高原则 5：无出处的句子进不了库。

CREATE TABLE IF NOT EXISTS section_digests (
    domain         text PRIMARY KEY,
    text           jsonb,                         -- [{text, claim_ids}] 每句带引用
    theme          text,                          -- 一句共同主题
    has_new        boolean NOT NULL DEFAULT false, -- 近 12h 是否有新增断言（确定性）
    new_claims     integer NOT NULL DEFAULT 0,     -- 近 12h 新增断言数
    lead_story_id  bigint,                        -- 板块头条指针（软引用，不设 FK）
    generated_at   timestamptz NOT NULL DEFAULT now()
);
