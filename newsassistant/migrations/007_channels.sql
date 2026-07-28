-- 频道 = 保存的查询（D3）。表里存的是**查询**，不是版面、不是领域逻辑。
-- 新频道 = 新增一行；代码里没有任何一处按频道分支。
--
-- query 的键是结构性的（实体命中 / 文本匹配 / 标量阈值 / 时间窗 / 排序），
-- 值才是主题（实体名、关键词）—— 主题只能出现在数据里，这是 D2 的边界。
-- palette 同理：频道标识色是频道的属性（已过 dataviz 校验器，D16），
-- 前端从接口拿色，不在前端硬编码任何频道。

CREATE TABLE IF NOT EXISTS channels (
    key        text PRIMARY KEY,
    name       text NOT NULL,
    query      jsonb NOT NULL DEFAULT '{}'::jsonb,
    palette    jsonb NOT NULL DEFAULT '{}'::jsonb,
    position   int  NOT NULL DEFAULT 0,
    enabled    boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS channels_position_idx ON channels (position, key);
