import { useEffect, useMemo, useState } from "react";

import CitationModal from "../components/CitationModal";
import MarkdownText from "../components/MarkdownText";
import { askQuestion, fetchChunk, streamQuestion, toAssetUrl } from "../services/api";

const EXAMPLES = [
  "历史 PRD 里，产品背景一般怎么写？",
  "AI 外呼策略配置的功能规则怎么描述？",
  "新线索二次、三次呼叫应该参考哪些历史写法？",
];

function stripThinkBlocks(text) {
  return text.replace(/<think>[\s\S]*?<\/think>\s*/g, "").replace(/<think>[\s\S]*$/g, "");
}

function getBlockLabel(item) {
  if (!item?.block_types?.length) {
    return "片段";
  }
  const labels = {
    heading: "标题",
    paragraph: "正文",
    list: "列表",
    table: "表格",
  };
  return item.block_types.map((type) => labels[type] || type).join(" / ");
}

export default function ChatPage({ documents = [] }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [meta, setMeta] = useState(null);
  const [topK, setTopK] = useState(4);
  const [useStreaming, setUseStreaming] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [chunkDetail, setChunkDetail] = useState(null);
  const [eventSource, setEventSource] = useState(null);

  useEffect(() => {
    return () => {
      eventSource?.close();
    };
  }, [eventSource]);

  const citationCount = meta?.citations?.length || 0;
  const confidenceText = useMemo(() => {
    if (!meta) {
      return "等待检索";
    }
    return typeof meta.confidence === "number" ? meta.confidence.toFixed(2) : meta.confidence;
  }, [meta]);

  async function handleOpenCitation(chunkId) {
    try {
      const detail = await fetchChunk(chunkId);
      setChunkDetail(detail);
      setModalOpen(true);
    } catch (fetchError) {
      setError(fetchError.message);
    }
  }

  function runQuestion(nextQuestion) {
    const value = nextQuestion ?? question;
    if (!value.trim()) {
      setError("请输入你正在写的 PRD 问题或需求点");
      return;
    }
    eventSource?.close();
    setQuestion(value);
    setError("");
    setAnswer("");
    setMeta(null);
    setStreaming(true);

    if (!useStreaming) {
      askQuestion({ question: value, topK })
        .then((payload) => {
          setAnswer(payload.answer || "");
          setMeta(payload);
          setStreaming(false);
          setEventSource(null);
        })
        .catch((requestError) => {
          setError(requestError.message);
          setStreaming(false);
          setEventSource(null);
        });
      return;
    }

    const source = streamQuestion({
      question: value,
      topK,
      onToken: ({ content }) => {
        setAnswer((current) => current + content);
      },
      onMeta: (payload) => {
        setMeta(payload);
      },
      onError: (message) => {
        setError(message);
        setStreaming(false);
        setEventSource(null);
      },
      onDone: () => {
        setAnswer((current) => stripThinkBlocks(current).trim());
        setStreaming(false);
        setEventSource(null);
      },
    });

    setEventSource(source);
  }

  function handleAsk(event) {
    event.preventDefault();
    runQuestion();
  }

  return (
    <section className="workbench">
      <div className="workbench-main">
        <header className="page-header">
          <div>
            <span className="eyebrow-dark">PRD 写作参谋台</span>
            <h2>从历史 PRD 里找可复用写法</h2>
            <p>输入一个需求点，系统会检索历史文档，整理参考表达，并展示每条结论背后的原文片段。</p>
          </div>
          <div className="header-metrics">
            <div>
              <strong>{documents.length}</strong>
              <span>可检索 PRD</span>
            </div>
            <div>
              <strong>{citationCount}</strong>
              <span>命中片段</span>
            </div>
          </div>
        </header>

        <form className="query-box" onSubmit={handleAsk}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="输入你正在写的需求点，例如：司机取消订单后的补偿规则怎么写？历史 PRD 里怎么描述新线索筛选策略？"
          />
          <div className="example-row">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="example-chip" onClick={() => runQuestion(example)}>
                {example}
              </button>
            ))}
          </div>
          <div className="query-controls">
            <label className="setting-item">
              <span>引用数量</span>
              <input
                type="range"
                min="1"
                max="10"
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
              />
              <strong>{topK}</strong>
            </label>
            <label className="setting-item checkbox-item">
              <input
                type="checkbox"
                checked={useStreaming}
                onChange={(event) => setUseStreaming(event.target.checked)}
              />
              <span>流式生成</span>
            </label>
            <button type="submit" disabled={streaming}>
              {streaming ? "正在查历史写法..." : "查历史写法"}
            </button>
          </div>
        </form>

        {error ? <p className="error-banner">{error}</p> : null}

        <article className="answer-card">
          <div className="answer-header">
            <div>
              <span className="eyebrow-dark">历史写法总结</span>
              <h3>参考回答</h3>
            </div>
            <span className="confidence-badge">置信度 {confidenceText}</span>
          </div>
          <MarkdownText
            fallback="这里会根据历史 PRD 总结可复用的背景描述、规则表达、功能拆解和引用来源。"
            text={answer}
          />
          {meta?.fallback_reason ? <p className="notice">{meta.fallback_reason}</p> : null}
        </article>
      </div>

      <aside className="evidence-panel">
        <div className="evidence-header">
          <div>
            <span className="eyebrow-dark">Evidence</span>
            <h3>命中片段</h3>
          </div>
          <span>{citationCount} 条</span>
        </div>

        <div className="citation-list">
          {(meta?.citations || []).length === 0 ? (
            <p className="empty-text">检索后会在这里显示历史 PRD 的原文分块。</p>
          ) : (
            meta.citations.map((item, index) => (
              <button key={item.chunk_id} className="citation-card" onClick={() => handleOpenCitation(item.chunk_id)}>
                <div className="citation-card-top">
                  <strong>#{index + 1}</strong>
                  <span>score {item.score}</span>
                </div>
                <h4 title={item.filename}>{item.filename}</h4>
                <div className="citation-tags">
                  <span>{getBlockLabel(item)}</span>
                  {item.section_title ? <span>{item.section_title}</span> : null}
                  {item.page_no ? <span>第 {item.page_no} 页</span> : null}
                </div>
                {item.image_url ? (
                  <img className="citation-image" src={toAssetUrl(item.image_url)} alt={item.filename} />
                ) : null}
                <p>{item.excerpt}</p>
              </button>
            ))
          )}
        </div>
      </aside>

      <CitationModal detail={chunkDetail} open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}
