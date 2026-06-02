import { toAssetUrl } from "../services/api";

export default function CitationModal({ detail, open, onClose }) {
  if (!open || !detail) {
    return null;
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <span className="eyebrow-dark">Original Chunk</span>
            <h3>引用原文</h3>
            <p>{detail.filename}</p>
          </div>
          <button className="ghost-button" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="modal-meta">
          <span>Chunk ID: {detail.chunk_id}</span>
          <span>页码: {detail.page_no || "无"}</span>
          <span>章节: {detail.section_title || "未标注"}</span>
        </div>
        {detail.image_url ? (
          <img className="modal-image" src={toAssetUrl(detail.image_url)} alt={detail.filename} />
        ) : null}
        <pre className="chunk-content">{detail.content}</pre>
      </div>
    </div>
  );
}
