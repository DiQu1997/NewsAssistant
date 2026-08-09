-- 事件层结构化事实与视图规格（docs/redesign-facts.md）。
--
-- facts：事件的类型化槽位（伤亡数、关税率、谈判轮次…），每个槽位的每个值
--   都带 claim_ids —— 没有出处的数字进不了库，沿用综述的最高原则 5。
--   争议槽位（多口径）把官方值与估计值存成同级字段，差额自带名字。
-- views：图元规格（FT Visual Vocabulary 九类意图 → 图型），标题即发现。
--   两者都是廉价可再生产物，随 synthesized_at 一起过期重算。

ALTER TABLE stories ADD COLUMN IF NOT EXISTS facts jsonb;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS views jsonb;
