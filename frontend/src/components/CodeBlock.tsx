import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

// Only Python is registered: keeps the bundle small.
SyntaxHighlighter.registerLanguage("python", python);

interface CodeBlockProps {
  code: string;
  language?: "python" | "text";
}

export function CodeBlock({ code, language = "python" }: CodeBlockProps): JSX.Element {
  return (
    <SyntaxHighlighter
      language={language}
      style={oneDark}
      customStyle={{ margin: 0, borderRadius: "0.5rem", fontSize: "12.5px", background: "#020617" }}
      wrapLongLines
    >
      {code}
    </SyntaxHighlighter>
  );
}
