-- 每个源可选一条 URL 拒绝正则；ingest 在写入库之前就丢弃匹配的条目，
-- 从而在源头掐掉 sports/entertainment/local 这类不属于新闻的品类，
-- 避免它们进入 extract → assign 花下游钱。
ALTER TABLE sources ADD COLUMN IF NOT EXISTS url_deny TEXT;
