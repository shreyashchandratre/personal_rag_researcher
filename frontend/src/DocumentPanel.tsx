import { useCallback, useEffect, useRef, useState } from "react";

export interface DocRecord {
  id: string;
  filename: string;
  file_size: number;
  chunk_count: number;
  status: "processing" | "ready" | "failed";
  uploaded_at: string;
}

interface UploadingFile {
  tempId: string;
  filename: string;
  status: "uploading" | "processing" | "ready" | "failed";
  error?: string;
}

interface Props {
  sessionId: string | null;
  onSessionNeeded: () => Promise<string | null>;
}

function fmt_size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    ready: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
    processing: "bg-amber-500/20 text-amber-300 border-amber-500/30",
    uploading: "bg-blue-500/20 text-blue-300 border-blue-500/30",
    failed: "bg-red-500/20 text-red-300 border-red-500/30",
  };
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium uppercase tracking-wide ${
        map[status] ?? map.processing
      }`}
    >
      {status === "processing" || status === "uploading" ? (
        <span className="inline-flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-current animate-pulse" />
          {status}
        </span>
      ) : (
        status
      )}
    </span>
  );
}

const ALLOWED = [".pdf", ".docx", ".doc", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"];

export default function DocumentPanel({ sessionId, onSessionNeeded }: Props) {
  const [docs, setDocs] = useState<DocRecord[]>([]);
  const [uploading, setUploading] = useState<UploadingFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchDocs = useCallback(async (sid: string) => {
    try {
      const r = await fetch(`/api/documents?session_id=${sid}`);
      if (!r.ok) return;
      const data: DocRecord[] = await r.json();
      setDocs(data);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (sessionId) void fetchDocs(sessionId);
    else setDocs([]);
  }, [sessionId, fetchDocs]);

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      let sid = sessionId;
      if (!sid) {
        sid = await onSessionNeeded();
        if (!sid) return;
      }

      const fileArr = Array.from(files).filter((f) => {
        const ext = "." + f.name.split(".").pop()?.toLowerCase();
        return ALLOWED.includes(ext);
      });

      if (!fileArr.length) {
        setError(`No supported files. Allowed: ${ALLOWED.join(", ")}`);
        return;
      }

      setError(null);

      // Optimistic: add uploading placeholders
      const placeholders: UploadingFile[] = fileArr.map((f) => ({
        tempId: crypto.randomUUID(),
        filename: f.name,
        status: "uploading",
      }));
      setUploading((prev) => [...prev, ...placeholders]);

      // Upload each file individually so we get per-file progress
      await Promise.all(
        fileArr.map(async (file, idx) => {
          const tempId = placeholders[idx].tempId;

          const fd = new FormData();
          fd.append("files", file);
          fd.append("session_id", sid!);

          // Mark as processing
          setUploading((prev) =>
            prev.map((u) => (u.tempId === tempId ? { ...u, status: "processing" } : u))
          );

          try {
            const res = await fetch("/api/upload", { method: "POST", body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              const msg =
                typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? res.statusText);
              setUploading((prev) =>
                prev.map((u) => (u.tempId === tempId ? { ...u, status: "failed", error: msg } : u))
              );
              return;
            }

            const result = data.results?.[0];
            if (result && !result.ok) {
              setUploading((prev) =>
                prev.map((u) =>
                  u.tempId === tempId ? { ...u, status: "failed", error: result.error } : u
                )
              );
              return;
            }

            setUploading((prev) => prev.filter((u) => u.tempId !== tempId));
            await fetchDocs(sid!);
          } catch (e) {
            const msg = e instanceof Error ? e.message : "Upload failed";
            setUploading((prev) =>
              prev.map((u) => (u.tempId === tempId ? { ...u, status: "failed", error: msg } : u))
            );
          }
        })
      );
    },
    [sessionId, onSessionNeeded, fetchDocs]
  );

  const deleteDoc = useCallback(
    async (doc: DocRecord) => {
      if (!sessionId) return;
      if (!confirm(`Delete "${doc.filename}"? This removes its indexed content.`)) return;

      // Optimistic remove
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));

      try {
        const r = await fetch(`/api/documents/${doc.id}?session_id=${sessionId}`, {
          method: "DELETE",
        });
        if (!r.ok) {
          // Restore on failure
          setDocs((prev) => [doc, ...prev]);
          const data = await r.json().catch(() => ({}));
          setError(typeof data.detail === "string" ? data.detail : "Delete failed");
        }
      } catch {
        setDocs((prev) => [doc, ...prev]);
        setError("Delete failed");
      }
    },
    [sessionId]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files);
    },
    [uploadFiles]
  );

  const fileIcon = (filename: string) => {
    const ext = filename.split(".").pop()?.toLowerCase() ?? "";
    if (["png", "jpg", "jpeg", "webp"].includes(ext)) return "🖼️";
    if (["docx", "doc"].includes(ext)) return "📝";
    if (["txt", "md"].includes(ext)) return "📃";
    return "📄";
  };

  const allItems = [
    ...uploading,
    ...docs,
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-white/5">
        <h2 className="font-display text-sm font-semibold text-white/90 mb-2">
          Study Materials
        </h2>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`w-full rounded-xl border-2 border-dashed py-3 px-2 text-center text-xs transition-colors cursor-pointer ${
            dragging
              ? "border-ember-400/70 bg-ember-500/10 text-amber-200"
              : "border-white/10 text-mist/70 hover:border-ember-400/40 hover:bg-ember-500/5 hover:text-amber-200"
          }`}
        >
          <span className="block text-base mb-0.5">📎</span>
          Drop files or click to upload
          <span className="block text-[10px] mt-0.5 opacity-60">
            PDF, DOCX, TXT, MD, images
          </span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ALLOWED.join(",")}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) void uploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="mx-3 mt-2 rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-red-200 text-xs">
          {error}
          <button className="ml-2 opacity-60 hover:opacity-100" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* Document list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1 min-h-0">
        {allItems.length === 0 && (
          <div className="text-center py-8 px-3">
            <p className="text-2xl mb-2">📚</p>
            <p className="text-xs text-mist/60 leading-relaxed">
              No study materials yet. Upload PDFs, docs, or notes to get started.
            </p>
          </div>
        )}

        {/* Uploading placeholders */}
        {uploading.map((u) => (
          <div
            key={u.tempId}
            className="rounded-xl border border-white/8 bg-ink-800/50 px-3 py-2.5"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs text-white/80 truncate">
                  {fileIcon(u.filename)} {u.filename}
                </p>
                {u.error && (
                  <p className="text-[10px] text-red-300 mt-0.5 line-clamp-2">{u.error}</p>
                )}
              </div>
              <StatusBadge status={u.status} />
            </div>
          </div>
        ))}

        {/* Indexed documents */}
        {docs.map((doc) => (
          <div
            key={doc.id}
            className="group rounded-xl border border-white/8 bg-ink-800/50 px-3 py-2.5 hover:border-white/15 transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs text-white/85 truncate" title={doc.filename}>
                  {fileIcon(doc.filename)} {doc.filename}
                </p>
                <p className="text-[10px] text-mist/50 mt-0.5">
                  {fmt_size(doc.file_size)} · {doc.chunk_count} chunks ·{" "}
                  {new Date(doc.uploaded_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <StatusBadge status={doc.status} />
                <button
                  type="button"
                  title="Delete document"
                  onClick={() => void deleteDoc(doc)}
                  className="opacity-0 group-hover:opacity-100 text-mist hover:text-red-400 text-xs p-0.5 transition-opacity"
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
