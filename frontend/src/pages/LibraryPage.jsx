import { useMemo, useState } from "react";

import StatusBadge from "../components/StatusBadge";
import { deleteDocument, fetchDocumentChunks, refreshLinkDocument, reindexDocument, toAssetUrl } from "../services/api";

const BLOCK_LABELS = {
  heading: "标题",
  paragraph: "正文",
  list: "列表",
  table: "表格",
};

function formatBlockTypes(types = []) {
  if (!types.length) {
    return "片段";
  }
  return types.map((type) => BLOCK_LABELS[type] || type).join(" / ");
}

export default function LibraryPage({ documents, loading, onRefresh }) {
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunkError, setChunkError] = useState("");

  const selectedDocumentExists = useMemo(
    () => selectedDocument && documents.some((item) => item.id === selectedDocument.id),
    [documents, selectedDocument],
  );

  async function handleReindex(documentId) {
    try {
      await reindexDocument(documentId);
      if (selectedDocument?.id === documentId) {
        setChunks([]);
      }
      onRefresh?.();
    } catch (error) {
      window.alert(error.message);
    }
  }

  async function handleRefreshLink(documentId) {
    try {
      await refreshLinkDocument(documentId);
      if (selectedDocument?.id === documentId) {
        setChunks([]);
      }
      onRefresh?.();
    } catch (error) {
      window.alert(error.message);
    }
  }

  async function handleDelete(documentId, filename) {
    const confirmed = window.confirm(`确认删除文档“${filename}”吗？这会同时删除索引数据。`);
    if (!confirmed) {
      return;
    }
    try {
      await deleteDocument(documentId);
      if (selectedDocument?.id === documentId) {
        setSelectedDocument(null);
        setChunks([]);
      }
      onRefresh?.();
    } catch (error) {
      window.alert(error.message);
    }
  }

  async function handleViewChunks(document) {
    setSelectedDocument(document);
    setChunkError("");
    setChunksLoading(true);
    try {
      const payload = await fetchDocumentChunks(document.id);
      setChunks(payload);
    } catch (error) {
      setChunks([]);
      setChunkError(error.message);
    } finally {
      setChunksLoading(false);
    }
  }

  return (
    <section className="panel">
      <div className="page-header compact">
        <div>
          <span className="eyebrow-dark">Library</span>
          <h2>历史 PRD 文档库</h2>
          <p>查看文档状态、分块数量和每个 chunk 的原文内容，方便调试清洗与切分质量。</p>
        </div>
        <button className="ghost-button" onClick={onRefresh}>
          刷新
        </button>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>类型</th>
              <th>状态</th>
              <th>分块数</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6">加载中...</td>
              </tr>
            ) : documents.length === 0 ? (
              <tr>
                <td colSpan="6">还没有历史 PRD，先上传一份试试。</td>
              </tr>
            ) : (
              documents.map((item) => (
                <tr key={item.id}>
                  <td className="filename-cell">{item.filename}</td>
                  <td>{item.file_type}</td>
                  <td>
                    <StatusBadge status={item.status} />
                    {item.error_message ? <p className="error-text">{item.error_message}</p> : null}
                  </td>
                  <td>{item.chunk_count}</td>
                  <td>{new Date(item.updated_at).toLocaleString("zh-CN")}</td>
                  <td>
                    <div className="table-actions">
                      <button className="ghost-button" onClick={() => handleViewChunks(item)}>
                        查看分块
                      </button>
                      {item.source_url ? (
                        <button className="ghost-button" onClick={() => handleRefreshLink(item.id)}>
                          更新并重建索引
                        </button>
                      ) : (
                        <button className="ghost-button" onClick={() => handleReindex(item.id)}>
                          重建索引
                        </button>
                      )}
                      <button className="ghost-button danger" onClick={() => handleDelete(item.id, item.filename)}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedDocument && selectedDocumentExists ? (
        <div className="chunk-viewer">
          <div className="chunk-viewer-header">
            <div>
              <span className="eyebrow-dark">Chunk Preview</span>
              <h3>{selectedDocument.filename}</h3>
              <p>
                共 {chunks.length} 个分块
                {selectedDocument.chunk_count !== chunks.length ? `，索引记录 ${selectedDocument.chunk_count} 个` : ""}
              </p>
            </div>
            <button
              className="ghost-button"
              onClick={() => {
                setSelectedDocument(null);
                setChunks([]);
                setChunkError("");
              }}
            >
              关闭
            </button>
          </div>

          {chunksLoading ? <p className="notice">分块加载中...</p> : null}
          {chunkError ? <p className="error-banner">{chunkError}</p> : null}
          {!chunksLoading && !chunkError && chunks.length === 0 ? (
            <p className="notice">当前文档还没有可展示的分块，可能仍在索引中。</p>
          ) : null}

          <div className="chunk-list">
            {chunks.map((chunk, index) => (
              <article className="chunk-preview-card" key={chunk.chunk_id}>
                <div className="chunk-preview-meta">
                  <strong>#{index + 1}</strong>
                  <span>{formatBlockTypes(chunk.block_types)}</span>
                  <span>{chunk.content.length} 字</span>
                  <span>
                    offset {chunk.start_offset}-{chunk.end_offset}
                  </span>
                  {chunk.page_no ? <span>第 {chunk.page_no} 页</span> : null}
                </div>
                {chunk.section_title ? <p className="chunk-section-title">{chunk.section_title}</p> : null}
                {chunk.image_url ? (
                  <img className="chunk-preview-image" src={toAssetUrl(chunk.image_url)} alt={chunk.section_title || "文档图片"} />
                ) : null}
                <pre className="chunk-preview-content">{chunk.content}</pre>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
