import { useEffect, useMemo, useState } from "react";

import ChatPage from "./pages/ChatPage";
import KeyConfigPage from "./pages/KeyConfigPage";
import LibraryPage from "./pages/LibraryPage";
import UploadPage from "./pages/UploadPage";
import { fetchDocuments } from "./services/api";

const TABS = [
  { id: "chat", label: "智能问答", icon: "Q" },
  { id: "library", label: "文档库", icon: "D" },
  { id: "upload", label: "上传", icon: "U" },
  { id: "key", label: "Key 配置", icon: "K" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("chat");
  const [chatWorkMode, setChatWorkMode] = useState("rag");
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);

  async function loadDocuments(options = {}) {
    const silent = Boolean(options.silent);
    if (!silent) {
      setLoading(true);
    }
    try {
      const items = await fetchDocuments();
      setDocuments(items);
    } catch (error) {
      console.error(error);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    loadDocuments();
    const timer = window.setInterval(() => loadDocuments({ silent: true }), 4000);
    return () => window.clearInterval(timer);
  }, []);

  const readyDocuments = useMemo(() => documents.filter((item) => item.status === "ready"), [documents]);
  const prdFocus = activeTab === "chat" && chatWorkMode === "prd";

  return (
    <div className={prdFocus ? "app-shell prd-focus" : "app-shell"}>
      {!prdFocus ? (
        <aside className="sidebar">
          <div className="brand">
            <span className="eyebrow">T3 PRD Knowledge Base</span>
            <h1>T3 出行 PRD 历史知识库</h1>
          </div>

          <nav className="nav-list" aria-label="主导航">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={tab.id === activeTab ? "nav-item active" : "nav-item"}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="nav-icon">{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>

          <div className="sidebar-actions">
            <button className="text-button" onClick={loadDocuments} disabled={loading}>
              刷新知识库
            </button>
          </div>
        </aside>
      ) : null}

      <main className="content">
        {activeTab === "chat" ? <ChatPage documents={readyDocuments} onWorkModeChange={setChatWorkMode} /> : null}
        {activeTab === "library" ? (
          <LibraryPage documents={documents} loading={loading} onRefresh={loadDocuments} />
        ) : null}
        {activeTab === "upload" ? <UploadPage onUploaded={loadDocuments} /> : null}
        {activeTab === "key" ? <KeyConfigPage /> : null}
      </main>
    </div>
  );
}
