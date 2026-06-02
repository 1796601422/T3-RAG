import { useState } from "react";

import { uploadDocument, uploadDocumentUrl } from "../services/api";

export default function UploadPage({ onUploaded }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkTitle, setLinkTitle] = useState("");
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);

  async function handleFileSubmit(event) {
    event.preventDefault();
    if (!selectedFile) {
      setMessage("请选择要上传的 PRD 或需求文档。");
      return;
    }

    setUploading(true);
    setMessage("");
    try {
      const result = await uploadDocument(selectedFile);
      setMessage(`上传成功，文档 ID：${result.document_id}`);
      setSelectedFile(null);
      event.target.reset();
      onUploaded?.();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleLinkSubmit(event) {
    event.preventDefault();
    if (!linkUrl.trim()) {
      setMessage("请输入要解析的链接。");
      return;
    }

    setImporting(true);
    setMessage("");
    try {
      const result = await uploadDocumentUrl({ url: linkUrl.trim(), title: linkTitle.trim() });
      setMessage(`链接导入成功，文档 ID：${result.document_id}`);
      setLinkUrl("");
      setLinkTitle("");
      onUploaded?.();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <section className="panel">
      <div className="page-header compact">
        <div>
          <span className="eyebrow-dark">Import</span>
          <h2>导入历史 PRD</h2>
          <p>支持 PDF、Word、Markdown、TXT，也可以粘贴网页或文档链接导入。</p>
        </div>
      </div>

      <form className="upload-form" onSubmit={handleFileSubmit}>
        <label className="upload-dropzone">
          <input
            type="file"
            accept=".pdf,.docx,.md,.txt"
            onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
          />
          <span>{selectedFile ? selectedFile.name : "选择本地文档"}</span>
          <small>上传后会自动清洗、分块并建立检索索引。</small>
        </label>
        <button type="submit" disabled={uploading}>
          {uploading ? "正在上传..." : "上传并建立索引"}
        </button>
      </form>

      <form className="upload-form link-upload-form" onSubmit={handleLinkSubmit}>
        <label className="field-row">
          <span>文档链接</span>
          <input
            type="url"
            value={linkUrl}
            placeholder="https://example.com/prd.html"
            onChange={(event) => setLinkUrl(event.target.value)}
          />
        </label>
        <label className="field-row">
          <span>文档名称</span>
          <input
            value={linkTitle}
            placeholder="可选，不填会自动获取在线文档名"
            onChange={(event) => setLinkTitle(event.target.value)}
          />
        </label>
        <button type="submit" disabled={importing}>
          {importing ? "正在解析链接..." : "解析链接并建立索引"}
        </button>
      </form>

      {message ? <p className="notice">{message}</p> : null}
    </section>
  );
}
