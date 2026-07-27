-- 004_api_sources · API 类源（阶段 1.5）的两个源属性
--
-- adapter：kind='api' 的源，响应格式由哪个适配器解析（newsassistant/apisources.py）。
--   url 里的查询参数（要哪种表单、哪个窗口）是数据，适配器只管协议形状 ——
--   接入方式是源的结构属性，不是主题先验。
--
-- fetch_via：走哪条 HTTP 通道。真实教训：SEC 在 TLS 指纹层拒绝 httpx，
--   同 UA 下 curl 可过（云端 MITM 代理会掩盖这个差异，本机部署会撞上）。
--   'auto' = httpx 优先，遇网络错误/403 回退 curl。同样是结构属性（传输层），
--   放注册表，不写死在代码里按 host 分支。

ALTER TABLE sources ADD COLUMN adapter text;
ALTER TABLE sources ADD COLUMN fetch_via text NOT NULL DEFAULT 'httpx'
    CHECK (fetch_via IN ('httpx', 'curl', 'auto'));
ALTER TABLE sources ADD CONSTRAINT sources_api_needs_adapter
    CHECK (kind <> 'api' OR adapter IS NOT NULL);
