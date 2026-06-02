const LABELS = {
  uploaded: "已上传",
  parsing: "解析中",
  chunking: "分块中",
  embedding: "向量化中",
  ready: "可检索",
  failed: "失败",
};

export default function StatusBadge({ status }) {
  return <span className={`status status-${status}`}>{LABELS[status] || status}</span>;
}
