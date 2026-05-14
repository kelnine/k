"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const suggestions = [
  "What is the RSI indicator and how do I use it?",
  "Explain the difference between calls and puts",
  "How should I size my positions for risk management?",
  "What is dollar-cost averaging?",
  "Explain support and resistance levels",
  "What causes IV crush in options?",
  "How do I read a candlestick chart?",
  "What is the Bitcoin halving and why does it matter?",
];

function AiTutorContent() {
  const searchParams = useSearchParams();
  const lessonParam = searchParams.get("lesson");

  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: lessonParam
        ? `Hi! I see you're studying **"${lessonParam}"**. I'm here to help you go deeper. What would you like to understand better about this topic?`
        : "Welcome to InvestIQ AI Tutor! 👋\n\nI'm powered by Claude and can help you understand:\n\n• **Crypto** — Bitcoin, DeFi, altcoins, on-chain analysis\n• **Forex** — Currency pairs, sessions, order flow\n• **Stocks** — Fundamentals, valuation, portfolio building\n• **Options** — Greeks, strategies, IV, spreads\n• **Psychology** — Mindset, biases, discipline\n• **Risk Management** — Position sizing, drawdown, stop losses\n\nWhat would you like to learn today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;

    const userMsg: Message = { role: "user", content };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: newMessages }),
      });
      const data = await res.json() as { message?: string; error?: string };
      if (data.message) {
        setMessages([...newMessages, { role: "assistant", content: data.message }]);
      }
    } catch {
      setMessages([...newMessages, { role: "assistant", content: "Sorry, I couldn't connect right now. Please try again in a moment." }]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  function formatMessage(text: string) {
    const lines = text.split("\n");
    return lines.map((line, i) => {
      const formatted = line
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`(.+?)`/g, '<code class="px-1 py-0.5 rounded text-xs bg-white/10 font-mono">$1</code>');
      if (line.startsWith("• ") || line.startsWith("- ")) {
        return <li key={i} className="ml-4 mb-1 list-none flex gap-2"><span className="text-purple-400 shrink-0">•</span><span dangerouslySetInnerHTML={{ __html: formatted.slice(2) }} /></li>;
      }
      if (line.startsWith("# ")) {
        return <h3 key={i} className="font-bold text-white mt-3 mb-1 text-base" dangerouslySetInnerHTML={{ __html: formatted.slice(2) }} />;
      }
      if (!line.trim()) return <div key={i} className="h-2" />;
      return <p key={i} className="mb-1 leading-relaxed" dangerouslySetInnerHTML={{ __html: formatted }} />;
    });
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="glass border-b border-white/5 px-4 py-3 flex items-center gap-3 shrink-0">
        <div className="w-9 h-9 rounded-xl gradient-options flex items-center justify-center text-white font-bold text-sm">AI</div>
        <div>
          <div className="font-semibold text-white text-sm">InvestIQ AI Tutor</div>
          <div className="text-xs text-gray-500">Powered by Claude · Always learning</div>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse-soft" />
          <span className="text-xs text-gray-500">Online</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-3xl mx-auto w-full">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="w-7 h-7 rounded-full gradient-options flex items-center justify-center text-xs text-white font-bold shrink-0 mt-1">AI</div>
            )}
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${msg.role === "user" ? "chat-bubble-user rounded-tr-sm text-gray-100" : "chat-bubble-ai rounded-tl-sm text-gray-200"}`}>
              {msg.role === "assistant" ? formatMessage(msg.content) : <p className="leading-relaxed">{msg.content}</p>}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="w-7 h-7 rounded-full gradient-options flex items-center justify-center text-xs text-white font-bold shrink-0">AI</div>
            <div className="chat-bubble-ai rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1 items-center">
                <div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions (show when few messages) */}
      {messages.length <= 2 && (
        <div className="px-4 pb-3 max-w-3xl mx-auto w-full">
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => void sendMessage(s)}
                className="text-xs px-3 py-1.5 rounded-full glass border border-white/10 text-gray-400 hover:text-white hover:border-white/20 transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="glass border-t border-white/5 px-4 py-3 shrink-0">
        <div className="max-w-3xl mx-auto flex gap-3 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything about investing, trading, or markets..."
            rows={1}
            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-purple-500/50 transition-colors"
            style={{ minHeight: "44px", maxHeight: "120px" }}
          />
          <button
            onClick={() => void sendMessage()}
            disabled={!input.trim() || loading}
            className="w-11 h-11 rounded-xl flex items-center justify-center text-white transition-all disabled:opacity-30"
            style={{ background: "linear-gradient(135deg, #6366f1, #a855f7)" }}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
        <p className="text-xs text-gray-600 text-center mt-2">Educational purposes only — not financial advice. DYOR before investing.</p>
      </div>
    </div>
  );
}

export default function AiTutorPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-[calc(100vh-64px)] text-gray-400">Loading AI Tutor...</div>}>
      <AiTutorContent />
    </Suspense>
  );
}
