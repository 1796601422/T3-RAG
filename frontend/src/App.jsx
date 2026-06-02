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
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);

  async function loadDocuments() {
    setLoading(true);
    try {
      const items = await fetchDocuments();
      setDocuments(items);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDocuments();
    const timer = window.setInterval(loadDocuments, 4000);
    return () => window.clearInterval(timer);
  }, []);

  const readyDocuments = useMemo(() => documents.filter((item) => item.status === "ready"), [documents]);
  const chunkCount = documents.reduce((total, item) => total + (item.chunk_count || 0), 0);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="eyebrow">T3 PRD Knowledge Base</span>
          <h1>T3 出行 PRD 历史知识库</h1>
          <p>查历史写法、看命中片段、复用产品口径。</p>
        </div>

        <div className="sidebar-stats" aria-label="知识库统计">
          <div>
            <strong>{documents.length}</strong>
            <span>历史文档</span>
          </div>
          <div>
            <strong>{chunkCount}</strong>
            <span>知识分块</span>
          </div>
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

        <section className="sidebar-docs" aria-label="历史文档">
          <div className="sidebar-section-title">
            <span>历史 PRD</span>
            <button className="text-button" onClick={loadDocuments} disabled={loading}>
              刷新
            </button>
          </div>
          <div className="document-list">
            {readyDocuments.length === 0 ? (
              <p className="empty-text">暂无可检索文档</p>
            ) : (
              readyDocuments.slice(0, 12).map((item) => (
                <article className="document-pill" key={item.id}>
                  <strong title={item.filename}>{item.filename}</strong>
                  <span>{item.chunk_count || 0} 个分块</span>
                </article>
              ))
            )}
          </div>
        </section>
      </aside>

      <main className="content">
        {activeTab === "chat" ? <ChatPage documents={readyDocuments} /> : null}
        {activeTab === "library" ? (
          <LibraryPage documents={documents} loading={loading} onRefresh={loadDocuments} />
        ) : null}
        {activeTab === "upload" ? <UploadPage onUploaded={loadDocuments} /> : null}
        {activeTab === "key" ? <KeyConfigPage /> : null}
      </main>
    </div>
  );
}
