import { useEffect, useState } from "react";

import { fetchApiKeyStatus, saveApiKey } from "../services/api";

export default function KeyConfigPage() {
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState({ configured: false, preview: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function loadStatus() {
      try {
        const data = await fetchApiKeyStatus();
        if (mounted) {
          setStatus(data);
        }
      } catch (loadError) {
        if (mounted) {
          setError(loadError.message);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    loadStatus();
    return () => {
      mounted = false;
    };
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const data = await saveApiKey(apiKey);
      setStatus(data);
      setApiKey("");
      setMessage("Key 已保存，后续上传、索引和问答会使用这个 Key。");
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel key-config-panel">
      <header className="page-header">
        <div>
          <span className="eyebrow-dark">API Key</span>
          <h2>填写 DashScope Key</h2>
          <p>把项目发给别人后，让对方在这里填自己的 Key；其它配置继续使用项目当前默认值。</p>
        </div>
        <span className={status.configured ? "status status-ready" : "status status-failed"}>
          {status.configured ? `已配置 ${status.preview}` : "未配置"}
        </span>
      </header>

      <form className="key-config-form" onSubmit={handleSubmit}>
        {loading ? <p className="notice">正在读取 Key 状态...</p> : null}
        {message ? <p className="notice success-notice">{message}</p> : null}
        {error ? <p className="error-banner">{error}</p> : null}

        <label className="field-row">
          <span>DashScope API Key</span>
          <input
            type="password"
            value={apiKey}
            placeholder={status.configured ? "重新输入可替换当前 Key" : "请输入 DashScope API Key"}
            autoComplete="off"
            onChange={(event) => {
              setApiKey(event.target.value);
              setMessage("");
              setError("");
            }}
          />
        </label>

        <div className="form-actions">
          <button type="submit" disabled={saving || loading || !apiKey.trim()}>
            {saving ? "保存中..." : "保存 Key"}
          </button>
        </div>
      </form>
    </section>
  );
}
