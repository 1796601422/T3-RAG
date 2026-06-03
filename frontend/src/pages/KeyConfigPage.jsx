import { useEffect, useState } from "react";

import { fetchApiKeyStatus, fetchMcpConfigStatus, saveApiKey, saveMcpConfig } from "../services/api";

export default function KeyConfigPage() {
  const [apiKey, setApiKey] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [keyStatus, setKeyStatus] = useState({ configured: false, preview: "" });
  const [mcpStatus, setMcpStatus] = useState({ configured: false, preview: "" });
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(false);
  const [savingMcp, setSavingMcp] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function loadStatus() {
      try {
        const [keyData, mcpData] = await Promise.all([fetchApiKeyStatus(), fetchMcpConfigStatus()]);
        if (mounted) {
          setKeyStatus(keyData);
          setMcpStatus(mcpData);
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

  async function handleKeySubmit(event) {
    event.preventDefault();
    setSavingKey(true);
    setMessage("");
    setError("");
    try {
      const data = await saveApiKey(apiKey);
      setKeyStatus(data);
      setApiKey("");
      setMessage("DashScope Key 已保存，后续上传、索引和问答会使用这个 Key。");
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSavingKey(false);
    }
  }

  async function handleMcpSubmit(event) {
    event.preventDefault();
    setSavingMcp(true);
    setMessage("");
    setError("");
    try {
      const data = await saveMcpConfig(mcpUrl);
      setMcpStatus(data);
      setMcpUrl("");
      setMessage("钉钉 MCP 地址已保存，后续链接上传会使用这个 MCP 配置。");
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSavingMcp(false);
    }
  }

  return (
    <section className="panel key-config-panel">
      <header className="page-header">
        <div>
          <span className="eyebrow-dark">Runtime Config</span>
          <h2>运行配置</h2>
          <p>把项目发给别人后，对方可以在这里填写自己的 DashScope Key 和钉钉 MCP 地址。</p>
        </div>
      </header>

      {loading ? <p className="notice">正在读取配置状态...</p> : null}
      {message ? <p className="notice success-notice">{message}</p> : null}
      {error ? <p className="error-banner">{error}</p> : null}

      <form className="key-config-form" onSubmit={handleKeySubmit}>
        <div className="form-section-header">
          <div>
            <span className="eyebrow-dark">API Key</span>
            <h3>DashScope Key</h3>
          </div>
          <span className={keyStatus.configured ? "status status-ready" : "status status-failed"}>
            {keyStatus.configured ? `已配置 ${keyStatus.preview}` : "未配置"}
          </span>
        </div>

        <label className="field-row">
          <span>DashScope API Key</span>
          <input
            type="password"
            value={apiKey}
            placeholder={keyStatus.configured ? "重新输入可替换当前 Key" : "请输入 DashScope API Key"}
            autoComplete="off"
            onChange={(event) => {
              setApiKey(event.target.value);
              setMessage("");
              setError("");
            }}
          />
        </label>

        <div className="form-actions">
          <button type="submit" disabled={savingKey || loading || !apiKey.trim()}>
            {savingKey ? "保存中..." : "保存 Key"}
          </button>
        </div>
      </form>

      <form className="key-config-form" onSubmit={handleMcpSubmit}>
        <div className="form-section-header">
          <div>
            <span className="eyebrow-dark">DingTalk MCP</span>
            <h3>钉钉 MCP 地址</h3>
          </div>
          <span className={mcpStatus.configured ? "status status-ready" : "status status-failed"}>
            {mcpStatus.configured ? `已配置 ${mcpStatus.preview}` : "未配置"}
          </span>
        </div>

        <label className="field-row">
          <span>DINGTALK_MCP_URL</span>
          <input
            type="url"
            value={mcpUrl}
            placeholder={mcpStatus.configured ? "重新输入可替换当前 MCP 地址" : "请输入钉钉 MCP URL"}
            autoComplete="off"
            onChange={(event) => {
              setMcpUrl(event.target.value);
              setMessage("");
              setError("");
            }}
          />
        </label>

        <div className="form-actions">
          <button type="submit" disabled={savingMcp || loading || !mcpUrl.trim()}>
            {savingMcp ? "保存中..." : "保存 MCP 配置"}
          </button>
        </div>
      </form>
    </section>
  );
}
