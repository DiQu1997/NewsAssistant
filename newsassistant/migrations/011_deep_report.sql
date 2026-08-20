-- 故事级深度报告：按需生成（页面按钮触发），非管线常规产物。
-- 与 summary（句句引用的综述）分层：deep_report 是分析员署名的解读 ——
-- 背景成因/各方立场/传导影响/情景推演，观点可辩、非事实陈述。
ALTER TABLE stories ADD COLUMN IF NOT EXISTS deep_report jsonb;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS deep_report_at timestamptz;
