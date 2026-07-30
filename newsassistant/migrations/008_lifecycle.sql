-- 008_lifecycle · 故事生命周期：active → dormant → archived
-- 活跃故事不可能无限堆积。N 天无新文档 → dormant（休眠），
-- 再 M 天无动静 → archived。archived 故事不再出现在默认查询里，
-- 但数据不删、可以被新文档唤醒回 active。

ALTER TABLE stories ADD COLUMN IF NOT EXISTS dormant_at timestamptz;

CREATE INDEX IF NOT EXISTS stories_state_idx ON stories (state);
CREATE INDEX IF NOT EXISTS stories_updated_idx ON stories (updated_at);
