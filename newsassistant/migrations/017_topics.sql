-- 频道子主题：taxonomy 挂在频道上（数据），故事→子主题的判定结果落表。
-- 一个故事在一个频道内只归一个子主题（判定是"最合适"，不是"全部沾边"）。
ALTER TABLE channels ADD COLUMN IF NOT EXISTS topics JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS story_topics (
    story_id BIGINT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    channel  TEXT   NOT NULL,
    topic    TEXT   NOT NULL,
    at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (story_id, channel)
);
CREATE INDEX IF NOT EXISTS story_topics_channel_idx ON story_topics (channel, topic);
