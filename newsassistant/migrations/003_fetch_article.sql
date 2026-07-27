-- 003_fetch_article · 源属性：feed 本身即载荷的源不抓文章页
--
-- 真实数据第一课（2026-07-27 首轮采集）：Federal Register 的 feed 正常，
-- 但 50 个文档页全部返回同一张反爬拦截页 —— 被当成正文入库成了 49 篇
-- "dup_exact" 垃圾。USGS/arXiv 的页面是 JS 应用，抽取也只能退化回摘要。
-- 这类源的 feed 条目本身就是全部载荷，抓页面纯属浪费且引入脏数据。
-- 这是源的**结构属性**（载荷位置），不是主题先验，放注册表。

ALTER TABLE sources ADD COLUMN fetch_article boolean NOT NULL DEFAULT true;
