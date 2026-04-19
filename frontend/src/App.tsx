import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Role = "user" | "assistant";

interface Msg {
  id: string;
  role: Role;
  content: string;
}

interface SessionRow {
  session_id: string;
  title: string;
  updated_at: string;
  preview: string;
}

function formatInline(text: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("`") && p.endsWith("`")) {
      return (
        <code
          key={i}
          className="rounded bg-ink-800 px-1.5 py-0.5 text-ember-400 text-[0.9em]"
        >
          {p.slice(1, -1)}
        </code>
      );
    }
    const lines = p.split("\n");
    return lines.map((line, li) => (
      <span key={`${i}-${li}`}>
        {li > 0 ? <br /> : null}
        {line}
      </span>
    ));
  });
}

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{
    chroma_ready: boolean;
    status?: string;
  } | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadSessions = useCallback(async () => {
    try {
      const r = await fetch("/api/sessions");
      if (!r.ok) return;
      const data = await r.json();
      setSessions(data.sessions ?? []);
    } catch {
      setSessions([]);
    }
  }, []);

  const loadHealth = useCallback(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ chroma_ready: false }));
  }, []);

  useEffect(() => {
    loadHealth();
    void loadSessions();
  }, [loadHealth, loadSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const startNewSession = useCallback(async (): Promise<string | null> => {
    setError(null);
    try {
      const r = await fetch("/api/sessions", { method: "POST" });
      if (!r.ok) throw new Error("Could not start a new session");
      const data = await r.json();
      const sid = data.session_id as string;
      setSessionId(sid);
      setMessages([]);
      sessionStorage.setItem("rag_session_id", sid);
      await loadSessions();
      return sid;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create session");
      return null;
    }
  }, [loadSessions]);

  useEffect(() => {
    const saved = sessionStorage.getItem("rag_session_id");
    if (!saved) return;
    setSessionId(saved);
    fetch(`/api/sessions/${saved}`)
      .then((r) => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      })
      .then((data: { messages: { role: string; content: string }[] }) => {
        setMessages(
          data.messages.map((m, i) => ({
            id: `${saved}-${i}`,
            role: m.role as Role,
            content: m.content,
          }))
        );
      })
      .catch(() => {
        sessionStorage.removeItem("rag_session_id");
        setSessionId(null);
      });
  }, []);

  const selectSession = useCallback(
    async (sid: string) => {
      setError(null);
      try {
        const r = await fetch(`/api/sessions/${sid}`);
        if (!r.ok) throw new Error("Session not found");
        const data = await r.json();
        setSessionId(data.session_id);
        sessionStorage.setItem("rag_session_id", data.session_id);
        setMessages(
          data.messages.map(
            (m: { role: string; content: string }, i: number) => ({
              id: `${sid}-${i}`,
              role: m.role as Role,
              content: m.content,
            })
          )
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load chat");
      }
    },
    []
  );

  const deleteSession = useCallback(
    async (sid: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!confirm("Delete this conversation?")) return;
      try {
        const r = await fetch(`/api/sessions/${sid}`, { method: "DELETE" });
        if (!r.ok) throw new Error("Delete failed");
        if (sessionId === sid) {
          sessionStorage.removeItem("rag_session_id");
          setSessionId(null);
          setMessages([]);
        }
        await loadSessions();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [loadSessions, sessionId]
  );

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    let sid =
      sessionId ??
      sessionStorage.getItem("rag_session_id") ??
      (await startNewSession());
    if (!sid) return;

    setInput("");
    setError(null);

    const userMsg: Msg = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    setMessages((m) => [...m, userMsg]);
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sid,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail ?? res.statusText)
        );
      }
      setSessionId(data.session_id);
      sessionStorage.setItem("rag_session_id", data.session_id);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.reply ?? "",
        },
      ]);
      await loadSessions();
      loadHealth();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      setMessages((m) => m.filter((x) => x.id !== userMsg.id));
    } finally {
      setLoading(false);
    }
  }, [
    input,
    loading,
    sessionId,
    loadSessions,
    loadHealth,
    startNewSession,
  ]);

  const onPickPdf = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Please choose a PDF file.");
        return;
      }
      setUploading(true);
      setUploadMsg(null);
      setError(null);
      const fd = new FormData();
      fd.append("file", file);
      try {
        const res = await fetch("/api/upload", { method: "POST", body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : JSON.stringify(data.detail ?? res.statusText)
          );
        }
        setUploadMsg(
          `Indexed ${data.chunk_count ?? "?"} chunks from ${data.pdf_count ?? "?"} PDF(s).`
        );
        loadHealth();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [loadHealth]
  );

  const chromaReady = health?.chroma_ready ?? false;

  return (
    <div className="min-h-screen font-sans text-slate-200 flex">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={onFileChange}
      />

      {/* Sidebar — history */}
      <aside
        className={`${
          historyOpen ? "flex" : "hidden"
        } md:flex w-full md:w-72 shrink-0 border-r border-white/5 bg-ink-950/90 flex-col max-h-screen sticky top-0`}
      >
        <div className="p-3 border-b border-white/5 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-display text-sm font-semibold text-white/90">
              History
            </h2>
            <button
              type="button"
              className="md:hidden text-xs text-mist"
              onClick={() => setHistoryOpen(false)}
            >
              Close
            </button>
          </div>
          <button
            type="button"
            onClick={() => void startNewSession()}
            className="w-full text-sm py-2 rounded-lg bg-ember-500/20 border border-ember-500/30 text-amber-100 hover:bg-ember-500/30 transition-colors"
          >
            + New chat
          </button>
          <button
            type="button"
            onClick={onPickPdf}
            disabled={uploading}
            className="w-full text-sm py-2 rounded-lg border border-white/15 text-slate-200 hover:border-ember-500/40 hover:bg-ember-500/10 transition-colors disabled:opacity-50"
          >
            {uploading ? "Indexing…" : "Upload PDF"}
          </button>
        </div>
        <nav className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 && (
            <p className="text-xs text-mist/80 px-2 py-4 text-center">
              No saved chats yet. Start one or upload a PDF.
            </p>
          )}
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`relative group rounded-xl border transition-colors ${
                sessionId === s.session_id
                  ? "border-ember-500/40 bg-ember-500/10"
                  : "border-transparent hover:border-white/10 hover:bg-white/5"
              }`}
            >
              <button
                type="button"
                onClick={() => void selectSession(s.session_id)}
                className="w-full text-left px-3 py-2.5 pr-8"
              >
                <span className="block text-sm text-white/90 line-clamp-2">
                  {s.title || "Chat"}
                </span>
                <span className="text-[11px] text-mist/70 mt-0.5">
                  {new Date(s.updated_at).toLocaleString()}
                </span>
              </button>
              <button
                type="button"
                title="Delete"
                onClick={(e) => void deleteSession(s.session_id, e)}
                className="absolute right-2 top-2 z-10 opacity-0 group-hover:opacity-100 text-mist hover:text-red-400 text-xs p-1"
              >
                ✕
              </button>
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col min-h-screen min-w-0">
        <header className="border-b border-white/5 bg-ink-900/80 backdrop-blur-md sticky top-0 z-10 shadow-glow">
          <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                className="md:hidden shrink-0 px-2 py-1 rounded border border-white/15 text-sm text-mist"
                onClick={() => setHistoryOpen(true)}
              >
                Menu
              </button>
              <div className="min-w-0">
                <h1 className="font-display text-xl font-semibold tracking-tight text-white truncate">
                  Personal RAG Researcher
                </h1>
                <p className="text-mist text-sm mt-0.5 hidden sm:block">
                  PDF library + web · Ollama + optional Cerebras
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {health && (
                <span
                  className={`text-xs px-2 py-1 rounded-full border ${
                    chromaReady
                      ? "border-emerald-500/40 text-emerald-400/90 bg-emerald-500/10"
                      : "border-amber-500/40 text-amber-300/90 bg-amber-500/10"
                  }`}
                >
                  {chromaReady ? "Index ready" : "Upload PDF"}
                </span>
              )}
              <button
                type="button"
                onClick={() => void startNewSession()}
                className="text-sm px-3 py-1.5 rounded-lg border border-white/10 text-mist hover:text-white hover:border-ember-500/50 hover:bg-ember-500/10 transition-colors hidden sm:inline-block"
              >
                New chat
              </button>
            </div>
          </div>
        </header>

        <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 flex flex-col gap-4 min-h-0">
          {!chromaReady && (
            <div className="rounded-2xl border border-amber-500/25 bg-amber-950/30 px-4 py-3 text-amber-100/90 text-sm">
              Add at least one PDF to build the search index. Use{" "}
              <strong>Upload PDF</strong> in the sidebar (or{" "}
              <code className="text-ember-400">python ingest.py</code>
              ).
            </div>
          )}
          {uploadMsg && (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/30 px-4 py-2 text-emerald-100/90 text-sm">
              {uploadMsg}
            </div>
          )}

          {messages.length === 0 && !loading && (
            <div className="rounded-2xl border border-white/5 bg-ink-800/40 p-8 text-center">
              <p className="font-display text-lg text-white/90 mb-2">
                Ask about your documents
              </p>
              <p className="text-mist text-sm max-w-md mx-auto leading-relaxed">
                Chats are saved to <strong>History</strong>. Upload PDFs from the
                sidebar to expand your library—they are indexed automatically.
              </p>
            </div>
          )}

          <div className="flex-1 overflow-y-auto space-y-4 pr-1 min-h-[40vh]">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed ${
                    m.role === "user"
                      ? "bg-ember-500/20 text-amber-50 border border-ember-500/25"
                      : "bg-ink-800/90 text-slate-200 border border-white/8 shadow-lg"
                  }`}
                >
                  <span className="text-xs uppercase tracking-wider opacity-50 block mb-1.5">
                    {m.role === "user" ? "You" : "Assistant"}
                  </span>
                  <div className="whitespace-pre-wrap">
                    {formatInline(m.content)}
                  </div>
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl px-4 py-3 bg-ink-800/60 border border-white/8">
                  <span className="inline-flex gap-1 items-center text-mist text-sm">
                    <span className="size-2 rounded-full bg-ember-500 animate-pulse" />
                    Thinking…
                  </span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {error && (
            <div
              className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-red-200 text-sm"
              role="alert"
            >
              {error}
            </div>
          )}

          <div className="rounded-2xl border border-white/10 bg-ink-900/60 p-2 flex gap-2 items-end shadow-glow">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder={
                chromaReady
                  ? "Ask a question…"
                  : "Upload a PDF first to enable answers from your library…"
              }
              rows={2}
              disabled={loading || !chromaReady}
              className="flex-1 resize-none bg-transparent border-0 rounded-xl px-3 py-2 text-slate-100 placeholder:text-mist/60 focus:outline-none focus:ring-0 text-[15px] min-h-[44px] max-h-40 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => void send()}
              disabled={loading || !input.trim() || !chromaReady}
              className="shrink-0 mb-0.5 px-5 py-2.5 rounded-xl font-medium bg-gradient-to-br from-ember-500 to-ember-600 text-ink-950 hover:from-ember-400 hover:to-ember-500 disabled:opacity-40 disabled:pointer-events-none transition-all shadow-md"
            >
              Send
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
