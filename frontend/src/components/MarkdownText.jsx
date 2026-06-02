function parseInline(text, keyPrefix) {
  const parts = [];
  const pattern = /(\*\*([^*]+)\*\*)/g;
  let lastIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(
      <strong key={`${keyPrefix}-${match.index}`}>
        {match[2]}
      </strong>,
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

export default function MarkdownText({ text, fallback = "" }) {
  const content = text || fallback;
  const lines = content.split(/\r?\n/);

  return (
    <div className="markdown-text">
      {lines.map((line, index) => {
        const bullet = line.match(/^\s*[-*]\s+(.+)$/);
        const numbered = line.match(/^\s*(\d+[.)、])\s+(.+)$/);

        if (!line.trim()) {
          return <div aria-hidden="true" className="markdown-spacer" key={index} />;
        }

        if (bullet) {
          return (
            <p className="markdown-line bullet-line" key={index}>
              <span>•</span>
              <span>{parseInline(bullet[1], index)}</span>
            </p>
          );
        }

        if (numbered) {
          return (
            <p className="markdown-line bullet-line" key={index}>
              <span>{numbered[1]}</span>
              <span>{parseInline(numbered[2], index)}</span>
            </p>
          );
        }

        return (
          <p className="markdown-line" key={index}>
            {parseInline(line, index)}
          </p>
        );
      })}
    </div>
  );
}
