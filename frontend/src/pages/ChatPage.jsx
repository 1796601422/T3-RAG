import { useEffect, useMemo, useRef, useState } from "react";

import CitationModal from "../components/CitationModal";
import MarkdownText from "../components/MarkdownText";
import {
  askQuestion,
  clearPrdMemory,
  fetchChunk,
  generatePrd,
  streamPrd,
  streamQuestion,
  toAssetUrl,
} from "../services/api";

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
    image: "图片",
  };
  return item.block_types.map((type) => labels[type] || type).join(" / ");
}

function createPrdSessionId() {
  const existing = window.localStorage.getItem("prd_session_id");
  if (existing) {
    return existing;
  }
  const next = `prd-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem("prd_session_id", next);
  return next;
}

function createMessage(role, content = "") {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
  };
}

function getPrdMessagesKey(sessionId) {
  return `prd_messages_${sessionId}`;
}

function loadPrdMessages(sessionId) {
  try {
    const raw = window.localStorage.getItem(getPrdMessagesKey(sessionId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export default function ChatPage({ onWorkModeChange }) {
  const [workMode, setWorkMode] = useState("rag");
  const [sessionId] = useState(createPrdSessionId);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [prdMessages, setPrdMessages] = useState(() => loadPrdMessages(sessionId));
  const [meta, setMeta] = useState(null);
  const [topK, setTopK] = useState(4);
  const [useRagForPrd, setUseRagForPrd] = useState(true);
  const [useStreaming, setUseStreaming] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [clearingMemory, setClearingMemory] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [chunkDetail, setChunkDetail] = useState(null);
  const [eventSource, setEventSource] = useState(null);
  const runIdRef = useRef(0);

  const isPrdMode = workMode === "prd";

  useEffect(() => {
    onWorkModeChange?.(workMode);
  }, [onWorkModeChange, workMode]);

  useEffect(() => {
    return () => {
      eventSource?.close();
    };
  }, [eventSource]);

  useEffect(() => {
    if (prdMessages.length === 0) {
      window.localStorage.removeItem(getPrdMessagesKey(sessionId));
      return;
    }
    window.localStorage.setItem(getPrdMessagesKey(sessionId), JSON.stringify(prdMessages));
  }, [prdMessages, sessionId]);

  const citationCount = meta?.citations?.length || 0;
  const rejectedChunks = meta?.rejected_chunks || [];
  const confidenceText = useMemo(() => {
    if (!meta) {
      return "等待生成";
    }
    return typeof meta.confidence === "number" ? meta.confidence.toFixed(2) : meta.confidence;
  }, [meta]);

  function resetResult() {
    eventSource?.close();
    setAnswer("");
    setMeta(null);
    setError("");
    setStreaming(false);
    setEventSource(null);
  }

  async function handleClearMemory() {
    runIdRef.current += 1;
    eventSource?.close();
    setClearingMemory(true);
    setError("");
    try {
      await clearPrdMemory(sessionId);
      window.localStorage.removeItem(getPrdMessagesKey(sessionId));
      setPrdMessages([]);
      setQuestion("");
      setAnswer("");
      setMeta(null);
      setStreaming(false);
      setEventSource(null);
    } catch (clearError) {
      setError(clearError.message);
    } finally {
      setClearingMemory(false);
    }
  }

  async function handleOpenCitation(chunkId) {
    try {
      const detail = await fetchChunk(chunkId);
      setChunkDetail(detail);
      setModalOpen(true);
    } catch (fetchError) {
      setError(fetchError.message);
    }
  }

  function handleModeChange(nextMode) {
    if (nextMode === workMode) {
      return;
    }
    setWorkMode(nextMode);
    resetResult();
  }

  function updatePrdAssistantMessage(messageId, updater) {
    setPrdMessages((current) =>
      current.map((item) =>
        item.id === messageId
          ? {
              ...item,
              content: typeof updater === "function" ? updater(item.content) : updater,
            }
          : item
      )
    );
  }

  function appendPrdExchange(userContent, assistantContent = "") {
    const userMessage = createMessage("user", userContent);
    const assistantMessage = createMessage("assistant", assistantContent);
    setPrdMessages((current) => [...current, userMessage, assistantMessage]);
    return assistantMessage.id;
  }

  function runQuestion(nextQuestion) {
    const value = nextQuestion ?? question;
    if (!value.trim()) {
      setError(isPrdMode ? "请输入要生成或继续补充的 PRD 需求。" : "请输入要检索的知识库问题。");
      return;
    }

    eventSource?.close();
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    setQuestion(isPrdMode ? "" : value);
    setError("");
    setAnswer("");
    setMeta(null);
    setStreaming(true);

    let assistantMessageId = null;
    if (isPrdMode) {
      assistantMessageId = appendPrdExchange(value, "");
    }

    if (!useStreaming) {
      const request = isPrdMode
        ? generatePrd({ sessionId, requirement: value, useRag: useRagForPrd, topK })
        : askQuestion({ question: value, topK });

      request
        .then((payload) => {
          if (runIdRef.current !== runId) {
            return;
          }
          const nextAnswer = payload.answer || payload.prd || "";
          setAnswer(nextAnswer);
          if (isPrdMode && assistantMessageId) {
            updatePrdAssistantMessage(assistantMessageId, nextAnswer);
          }
          setMeta(payload);
          setStreaming(false);
          setEventSource(null);
        })
        .catch((requestError) => {
          if (runIdRef.current !== runId) {
            return;
          }
          if (isPrdMode && assistantMessageId) {
            updatePrdAssistantMessage(assistantMessageId, "本轮生成失败，请调整需求后重试。");
          }
          setError(requestError.message);
          setStreaming(false);
          setEventSource(null);
        });
      return;
    }

    const streamHandlers = {
      onToken: ({ content }) => {
        if (runIdRef.current !== runId) {
          return;
        }
        setAnswer((current) => current + content);
        if (isPrdMode && assistantMessageId) {
          updatePrdAssistantMessage(assistantMessageId, (current) => current + content);
        }
      },
      onMeta: (payload) => {
        if (runIdRef.current !== runId) {
          return;
        }
        setMeta(payload);
      },
      onError: (message) => {
        if (runIdRef.current !== runId) {
          return;
        }
        if (isPrdMode && assistantMessageId) {
          updatePrdAssistantMessage(assistantMessageId, "本轮生成失败，请调整需求后重试。");
        }
        setError(message);
        setStreaming(false);
        setEventSource(null);
      },
      onDone: () => {
        if (runIdRef.current !== runId) {
          return;
        }
        setAnswer((current) => stripThinkBlocks(current).trim());
        if (isPrdMode && assistantMessageId) {
          updatePrdAssistantMessage(assistantMessageId, (current) => stripThinkBlocks(current).trim());
        }
        setStreaming(false);
        setEventSource(null);
      },
    };

    const source = isPrdMode
      ? streamPrd({
          sessionId,
          requirement: value,
          useRag: useRagForPrd,
          topK,
          ...streamHandlers,
        })
      : streamQuestion({
          question: value,
          topK,
          ...streamHandlers,
        });

    setEventSource(source);
  }

  function handleAsk(event) {
    event.preventDefault();
    runQuestion();
  }

  return (
    <section className={isPrdMode ? "workbench prd-workbench" : "workbench"}>
      <div className="workbench-main">
        <form className={isPrdMode ? "query-box prd-chat-box" : "query-box"} onSubmit={handleAsk}>
          <div className="prd-toolbar">
            <div className="mode-switch" aria-label="工作模式">
              <button type="button" className={workMode === "rag" ? "active" : ""} onClick={() => handleModeChange("rag")}>
                知识库问答
              </button>
              <button type="button" className={workMode === "prd" ? "active" : ""} onClick={() => handleModeChange("prd")}>
                PRD 写作
              </button>
            </div>
            {isPrdMode ? (
              <button type="button" className="ghost-button" onClick={handleClearMemory} disabled={streaming || clearingMemory}>
                {clearingMemory ? "清除中..." : "清除历史记忆"}
              </button>
            ) : null}
          </div>

          {isPrdMode ? (
            <div className="prd-chat-panel">
              <div className="conversation-thread">
                {prdMessages.length === 0 ? (
                  <div className="prd-empty-state">
                    <span className="eyebrow-dark">Conversation</span>
                    <h3>开始一轮 PRD 写作</h3>
                    <p>输入初始需求后，可以继续补充约束、改写章节或细化验收标准；本轮对话会作为短期记忆参与后续生成。</p>
                  </div>
                ) : (
                  prdMessages.map((message) => (
                    <div key={message.id} className={`message-row ${message.role}`}>
                      <div className="message-bubble">
                        <div className="message-role">{message.role === "user" ? "你" : "PRD Agent"}</div>
                        {message.role === "assistant" ? (
                          <MarkdownText fallback="正在生成..." text={message.content} />
                        ) : (
                          <p>{message.content}</p>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : null}

          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              isPrdMode
                ? "输入需求或继续追问，例如：补充一下，只针对预约单；把验收标准写细一点。"
                : "输入要检索的知识库问题。"
            }
          />
          <div className="query-controls">
            <label className="setting-item">
              <span>引用数量</span>
              <input type="range" min="1" max="10" value={topK} onChange={(event) => setTopK(Number(event.target.value))} />
              <strong>{topK}</strong>
            </label>
            <label className="setting-item checkbox-item">
              <input type="checkbox" checked={useStreaming} onChange={(event) => setUseStreaming(event.target.checked)} />
              <span>流式生成</span>
            </label>
            {isPrdMode ? (
              <label className="setting-item checkbox-item">
                <input type="checkbox" checked={useRagForPrd} onChange={(event) => setUseRagForPrd(event.target.checked)} />
                <span>启用 RAG 检索</span>
              </label>
            ) : null}
            <button type="submit" disabled={streaming || clearingMemory}>
              {streaming ? (isPrdMode ? "正在生成..." : "正在检索...") : isPrdMode ? "发送" : "检索回答"}
            </button>
          </div>
        </form>

        {error ? <p className="error-banner">{error}</p> : null}

        {!isPrdMode ? (
          <article className="answer-card">
            <div className="answer-header">
              <div>
                <span className="eyebrow-dark">RAG Answer</span>
                <h3>参考回答</h3>
              </div>
              <span className="confidence-badge">置信度 {confidenceText}</span>
            </div>
            <MarkdownText fallback="这里会根据历史 PRD 总结可复用的背景描述、规则表达、功能拆解和引用来源。" text={answer} />
            {meta?.fallback_reason ? <p className="notice">{meta.fallback_reason}</p> : null}
          </article>
        ) : null}
      </div>

      <aside className="evidence-panel">
        <div className="evidence-header">
          <div>
            <span className="eyebrow-dark">Evidence</span>
            <h3>命中片段</h3>
          </div>
          <span>{citationCount} 条{rejectedChunks.length ? ` / 未合格 ${rejectedChunks.length}` : ""}</span>
        </div>

        <div className="citation-list">
          {(meta?.citations || []).length === 0 ? (
            <p className="empty-text">
              {isPrdMode && !useRagForPrd
                ? "当前未启用历史资料检索，本次 PRD 不展示引用来源。"
                : "检索后会在这里显示历史 PRD 的原文分块。"}
            </p>
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
                {item.image_url ? <img className="citation-image" src={toAssetUrl(item.image_url)} alt={item.filename} /> : null}
                <p>{item.excerpt}</p>
              </button>
            ))
          )}
          {rejectedChunks.length ? (
            <div className="rejected-section">
              <div className="rejected-title">未合格候选</div>
              {rejectedChunks.map((item, index) => (
                <button key={`rejected-${item.chunk_id}`} className="citation-card rejected-card" onClick={() => handleOpenCitation(item.chunk_id)}>
                  <div className="citation-card-top">
                    <strong>未合格 #{index + 1}</strong>
                    <span>score {item.score}</span>
                  </div>
                  <h4 title={item.filename}>{item.filename}</h4>
                  <div className="citation-tags">
                    <span>{getBlockLabel(item)}</span>
                    {item.section_title ? <span>{item.section_title}</span> : null}
                    {item.page_no ? <span>第 {item.page_no} 页</span> : null}
                  </div>
                  {item.image_url ? <img className="citation-image" src={toAssetUrl(item.image_url)} alt={item.filename} /> : null}
                  <p>{item.content}</p>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </aside>

      <CitationModal detail={chunkDetail} open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}
