-- desk：同一素材的多个输出维度（general 态势图 / markets 市场分析），
-- 各 desk 有独立的观点账本（复盘只对照本 desk 的上一份）。
ALTER TABLE pictures ADD COLUMN IF NOT EXISTS desk text NOT NULL DEFAULT 'general';
CREATE INDEX IF NOT EXISTS pictures_desk_at_idx ON pictures (desk, at DESC);
