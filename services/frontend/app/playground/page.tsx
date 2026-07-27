"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Send, Bot, User, Zap, Database, Clock, Loader2,
  Layers, Search, Brain, GitBranch, FileCode,
  MessageSquare, ChevronDown, ChevronRight, BookOpen,
  CheckCircle, XCircle, ArrowRight, History,
  Plus, X,
} from "lucide-react"

// --- Types ---

interface PipelineStep {
  mechanism: string
  action: string
  detail: Record<string, unknown>
  elapsed_ms: number
}

interface Source {
  section_id?: string
  citation?: string
  title?: string
  snippet?: string
  score?: number
  type?: string
  file?: string
  lines?: string
  symbol_name?: string
}

interface TokenUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cached_tokens: number
  tokens_saved: number
  estimated_cost: number
  estimated_savings: number
  model_priced: string
  pricing_updated: string
  pricing_stale: boolean
}

interface Message {
  role: "user" | "assistant"
  content: string
  cached?: boolean
  generation_ms?: number
  cache_key?: string
  model_used?: string
  pipeline_trace?: PipelineStep[]
  sources?: Source[]
  token_usage?: TokenUsage
}

interface ConversationEntry {
  id: string
  user_message: string
  assistant_response: string
  model_used: string
  cache_hit: boolean
  generation_ms: number
  created_at: string
}

interface ConversationSession {
  id: string
  title: string
  messages: Message[]
  created_at: string
  updated_at: string
  message_count: number
}

type SidebarTab = "prompts" | "sessions"

const SESSIONS_KEY = "bitmod-playground-sessions"
const MAX_SESSIONS = 50

function loadSessions(): ConversationSession[] {
  if (typeof window === "undefined") return []
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    return raw ? (JSON.parse(raw) as ConversationSession[]) : []
  } catch {
    return []
  }
}

function saveSessions(sessions: ConversationSession[]) {
  const trimmed = sessions.slice(0, MAX_SESSIONS)
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(trimmed))
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

// --- Helpers ---

const MECHANISM_ICONS: Record<string, typeof Zap> = {
  intent_detection: Brain,
  exact_cache: Database,
  semantic_cache: Search,
  composable_cache: GitBranch,
  fuzzy_cache: Search,
  llm_generation: Zap,
  cache_store: Database,
  skip_llm: Zap,
  role_resolution: Brain,
  project_context: Database,
  agent_reasoning: Brain,
  agent_tool_call: Search,
  agent_role_shift: Brain,
}

const ACTION_COLORS: Record<string, string> = {
  HIT: "text-green-500",
  MISS: "text-yellow-500",
  SKIP: "text-muted-foreground",
  DONE: "text-blue-500",
  STORED: "text-green-500",
  PARTIAL: "text-orange-500",
  THINK: "text-purple-500",
  OK: "text-blue-500",
  UPDATED: "text-cyan-500",
  ERROR: "text-red-500",
  REJECTED: "text-red-500",
}

function formatMechanism(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

// --- Components ---

function PipelineTrace({ trace }: { trace: PipelineStep[] }) {
  const [expanded, setExpanded] = useState(false)
  if (!trace || trace.length === 0) return null

  const hitStep = trace.find((s) => s.action === "HIT")
  const agentCalls = trace.filter((s) => s.mechanism === "agent_tool_call").length
  const summary = hitStep
    ? `${formatMechanism(hitStep.mechanism)} HIT`
    : trace.find((s) => s.mechanism === "llm_generation")
    ? `LLM Generated${agentCalls > 0 ? ` (${agentCalls} tool call${agentCalls !== 1 ? "s" : ""})` : ""}`
    : "Processed"

  return (
    <div className="mt-3 pt-3 border-t border-border/20">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Layers className="h-3 w-3" />
        Pipeline: {summary} ({trace.length} steps)
      </button>

      {expanded && (
        <div className="mt-2 space-y-1">
          {trace.map((step, i) => {
            const Icon = MECHANISM_ICONS[step.mechanism] || Zap
            const colorClass = ACTION_COLORS[step.action] || "text-muted-foreground"
            return (
              <div key={i} className="pl-2">
                <div className="flex items-center gap-2 text-[10px]">
                  <Icon className={`h-3 w-3 shrink-0 ${colorClass}`} />
                  <span className="font-medium">{formatMechanism(step.mechanism)}</span>
                  <ArrowRight className="h-2.5 w-2.5 text-muted-foreground" />
                  <span className={colorClass}>{step.action}</span>
                  {step.elapsed_ms > 0 && (
                    <span className="text-muted-foreground ml-auto">{step.elapsed_ms.toFixed(1)}ms</span>
                  )}
                  {step.action === "HIT" && step.detail && (
                    <CheckCircle className="h-3 w-3 text-green-500 ml-1" />
                  )}
                </div>
                {/* Agent step details */}
                {step.mechanism === "agent_reasoning" && step.detail?.preview ? (
                  <div className="ml-5 mt-0.5 text-[9px] text-purple-400/80 italic truncate max-w-[90%]">
                    &ldquo;{String(step.detail.preview)}&rdquo;
                  </div>
                ) : null}
                {step.mechanism === "agent_tool_call" && step.detail?.tool ? (
                  <div className="ml-5 mt-0.5 text-[9px] text-muted-foreground">
                    <span className="font-mono">{String(step.detail.tool)}</span>
                    {(step.detail.args as Record<string, unknown> | undefined)?.query ? (
                      <span className="ml-1 text-blue-400/70">&ldquo;{String((step.detail.args as Record<string, unknown>).query).slice(0, 60)}&rdquo;</span>
                    ) : null}
                    {step.detail.results_count != null ? (
                      <span className="ml-1">&rarr; {String(step.detail.results_count)} results</span>
                    ) : null}
                    {step.detail.elapsed_ms != null ? (
                      <span className="ml-1 text-muted-foreground">({String(step.detail.elapsed_ms)}ms)</span>
                    ) : null}
                  </div>
                ) : null}
                {step.mechanism === "agent_role_shift" && step.detail ? (
                  <div className="ml-5 mt-0.5 text-[9px] text-cyan-400/80">
                    {String(step.detail.old_role)} &rarr; {String(step.detail.new_role)}
                    {Array.isArray(step.detail.tags) ? (
                      <span className="ml-1 text-muted-foreground">({(step.detail.tags as string[]).join(", ")})</span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function SourceList({ sources }: { sources: Source[] }) {
  const [expanded, setExpanded] = useState(false)
  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-2 pt-2 border-t border-border/20">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <BookOpen className="h-3 w-3" />
        {sources.length} source{sources.length !== 1 ? "s" : ""}
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5">
          {sources.map((src, i) => (
            <div key={i} className="text-[10px] bg-background/50 rounded-md px-2 py-1.5 border border-border/20">
              {src.type === "code" ? (
                <div className="flex items-center gap-1.5">
                  <FileCode className="h-3 w-3 text-blue-400 shrink-0" />
                  <span className="font-mono">{src.file}:{src.lines}</span>
                  {src.symbol_name && (
                    <Badge variant="outline" className="text-[8px] px-1 py-0">{src.symbol_name}</Badge>
                  )}
                </div>
              ) : src.type === "conversation" ? (
                <div className="flex items-center gap-1.5">
                  <MessageSquare className="h-3 w-3 text-purple-400 shrink-0" />
                  <span className="truncate">Past: {(src as Record<string, unknown>).question as string}</span>
                </div>
              ) : (
                <div>
                  {src.citation && <span className="font-medium">{src.citation}</span>}
                  {src.title && <span className="text-muted-foreground"> — {src.title}</span>}
                  {src.score !== undefined && (
                    <span className="text-muted-foreground ml-1">({(src.score * 100).toFixed(0)}%)</span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SidebarHistory({
  tab,
  onTabChange,
  history,
  onReplay,
  sessions,
  activeSessionId,
  onLoadSession,
  onDeleteSession,
}: {
  tab: SidebarTab
  onTabChange: (tab: SidebarTab) => void
  history: ConversationEntry[]
  onReplay: (q: string) => void
  sessions: ConversationSession[]
  activeSessionId: string | null
  onLoadSession: (session: ConversationSession) => void
  onDeleteSession: (id: string) => void
}) {
  return (
    <Card className="border-border/40 bg-card/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <History className="h-3.5 w-3.5" />
          History
        </CardTitle>
        <div className="flex mt-2 rounded-lg border border-border/40 overflow-hidden">
          <button
            onClick={() => onTabChange("prompts")}
            className={`flex-1 px-3 py-1.5 text-[10px] font-medium transition-colors cursor-pointer ${
              tab === "prompts"
                ? "bg-primary/20 text-primary border-r border-primary/40"
                : "bg-transparent text-muted-foreground border-r border-border/40 hover:text-foreground"
            }`}
          >
            Prompts
          </button>
          <button
            onClick={() => onTabChange("sessions")}
            className={`flex-1 px-3 py-1.5 text-[10px] font-medium transition-colors cursor-pointer ${
              tab === "sessions"
                ? "bg-primary/20 text-primary"
                : "bg-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Sessions
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 max-h-[240px] overflow-y-auto">
        {tab === "prompts" ? (
          history.length === 0 ? (
            <p className="text-[10px] text-muted-foreground text-center py-2">No recent prompts</p>
          ) : (
            history.map((conv) => (
              <button
                key={conv.id}
                onClick={() => onReplay(conv.user_message)}
                className="w-full text-left text-[10px] text-muted-foreground hover:text-foreground bg-muted/30 hover:bg-muted/50 rounded-md px-2.5 py-1.5 transition-colors cursor-pointer"
              >
                <div className="flex items-center gap-1.5">
                  <span className="truncate flex-1">{conv.user_message}</span>
                  {conv.cache_hit ? (
                    <Badge variant="accent" className="text-[8px] px-1 py-0 shrink-0">cached</Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[8px] px-1 py-0 shrink-0">{conv.generation_ms}ms</Badge>
                  )}
                </div>
              </button>
            ))
          )
        ) : (
          sessions.length === 0 ? (
            <p className="text-[10px] text-muted-foreground text-center py-2">No saved sessions</p>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                className={`group flex items-center gap-1.5 text-[10px] rounded-md px-2.5 py-1.5 transition-colors cursor-pointer ${
                  session.id === activeSessionId
                    ? "bg-primary/15 text-foreground"
                    : "text-muted-foreground hover:text-foreground bg-muted/30 hover:bg-muted/50"
                }`}
              >
                <button
                  onClick={() => onLoadSession(session)}
                  className="flex-1 text-left min-w-0 cursor-pointer"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="truncate flex-1">{session.title}</span>
                    <Badge variant="secondary" className="text-[8px] px-1 py-0 shrink-0">
                      {session.message_count}
                    </Badge>
                  </div>
                  <div className="text-[9px] text-muted-foreground mt-0.5">
                    {relativeTime(session.updated_at)}
                  </div>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteSession(session.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-red-400 transition-opacity cursor-pointer shrink-0"
                  aria-label={`Delete session: ${session.title}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))
          )
        )}
      </CardContent>
    </Card>
  )
}

// --- Main Page ---

export default function PlaygroundPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<ConversationEntry[]>([])
  const [showDebug, setShowDebug] = useState(true)
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("prompts")
  const [sessions, setSessions] = useState<ConversationSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const getApiUrl = useCallback(
    () => process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    [],
  )

  // Load conversation history
  useEffect(() => {
    const url = getApiUrl()
    const params = new URLSearchParams({ limit: "20" })
    fetch(`${url}/v1/history?${params}`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setHistory(Array.isArray(data) ? data : []))
      .catch(() => {})
  }, [getApiUrl, messages.length])

  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages])

  // Load sessions from localStorage on mount
  useEffect(() => {
    setSessions(loadSessions())
  }, [])

  // Auto-save session to localStorage when messages change
  useEffect(() => {
    if (messages.length === 0) return

    const now = new Date().toISOString()
    const firstUserMsg = messages.find((m) => m.role === "user")
    const title = firstUserMsg
      ? firstUserMsg.content.slice(0, 50) + (firstUserMsg.content.length > 50 ? "..." : "")
      : "Untitled"

    setSessions((prev) => {
      let sessionId = activeSessionId
      if (!sessionId) {
        sessionId = Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
        setActiveSessionId(sessionId)
      }

      const existing = prev.findIndex((s) => s.id === sessionId)
      const session: ConversationSession = {
        id: sessionId,
        title,
        messages,
        created_at: existing >= 0 ? prev[existing].created_at : now,
        updated_at: now,
        message_count: messages.length,
      }

      let next: ConversationSession[]
      if (existing >= 0) {
        next = [...prev]
        next[existing] = session
      } else {
        next = [session, ...prev]
      }

      // Sort by updated_at descending, keep max
      next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      next = next.slice(0, MAX_SESSIONS)

      saveSessions(next)
      return next
    })
  }, [messages, activeSessionId])

  const handleNewConversation = () => {
    setMessages([])
    setActiveSessionId(null)
  }

  const handleLoadSession = (session: ConversationSession) => {
    setMessages(session.messages)
    setActiveSessionId(session.id)
  }

  const handleDeleteSession = (id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id)
      saveSessions(next)
      return next
    })
    if (activeSessionId === id) {
      setMessages([])
      setActiveSessionId(null)
    }
  }

  const handleSend = async (overrideMessage?: string) => {
    const msg = overrideMessage || input.trim()
    if (!msg || loading) return

    if (!overrideMessage) setInput("")
    setMessages((prev) => [...prev, { role: "user", content: msg }])
    setLoading(true)

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 60000)

    try {
      const url = getApiUrl()
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      }
      if (showDebug) headers["X-Bitmod-Debug"] = "true"

      const body: Record<string, unknown> = { message: msg, stream: false }

      const response = await fetch(`${url}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      const data = await response.json()
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || data.error || "No response",
          cached: data.cached,
          generation_ms: data.generation_ms,
          cache_key: data.cache_key,
          model_used: data.model_used,
          pipeline_trace: data.pipeline_trace,
          sources: data.sources,
          token_usage: data.token_usage,
        },
      ])
    } catch (e) {
      const message =
        e instanceof DOMException && e.name === "AbortError"
          ? "Request timed out. Make sure your BitMod gateway is running."
          : "Could not connect to the BitMod API. Make sure the gateway is running on the configured URL."
      setMessages((prev) => [...prev, { role: "assistant", content: message }])
    } finally {
      clearTimeout(timeout)
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="mb-8">
        <Badge variant="accent" className="mb-4">Interactive</Badge>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Playground</h1>
        <p className="mt-2 text-muted-foreground">
          Test your BitMod instance. See every layer of the cache pipeline in real time.
        </p>
      </div>

      <div className="flex flex-col gap-6">
        {/* Chat Area */}
        <Card className="border-border/40 bg-card/50 flex flex-col h-[85vh]">
          <CardHeader className="pb-0 pt-3 px-4 flex flex-row items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5" />
              Chat
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleNewConversation}
              className="h-7 px-2 text-[10px] gap-1"
              aria-label="New conversation"
            >
              <Plus className="h-3 w-3" />
              New
            </Button>
          </CardHeader>
          {/* Messages */}
          <CardContent className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                <div className="text-center">
                  <Bot className="mx-auto h-12 w-12 text-primary/40 mb-4" />
                  <p className="text-lg font-medium">Ask BitMod anything</p>
                  <p className="text-sm mt-1">
                    Cache hits return instantly. Watch the pipeline trace to see every decision.
                  </p>
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
                {msg.role === "assistant" && (
                  <div className="flex-shrink-0 h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                )}
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/50 text-foreground"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>

                  {/* Metadata badges */}
                  {msg.role === "assistant" &&
                    (msg.cached !== undefined || msg.generation_ms !== undefined || msg.model_used) && (
                      <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-border/20">
                        {msg.cached !== undefined && (
                          <Badge variant={msg.cached ? "accent" : "secondary"} className="text-[10px]">
                            {msg.cached ? (
                              <><CheckCircle className="h-2.5 w-2.5 mr-1" />Cached</>
                            ) : (
                              <><XCircle className="h-2.5 w-2.5 mr-1" />Generated</>
                            )}
                          </Badge>
                        )}
                        {msg.generation_ms !== undefined && (
                          <Badge variant="outline" className="text-[10px]">
                            <Clock className="h-2.5 w-2.5 mr-1" />
                            {msg.generation_ms}ms
                          </Badge>
                        )}
                        {msg.model_used && (
                          <Badge variant="outline" className="text-[10px]">
                            <Brain className="h-2.5 w-2.5 mr-1" />
                            {msg.model_used}
                          </Badge>
                        )}
                        {msg.cache_key && (
                          <Badge variant="outline" className="text-[10px] font-mono">
                            {msg.cache_key.slice(0, 12)}...
                          </Badge>
                        )}
                        {msg.token_usage ? (
                          msg.cached ? (
                            <>
                              {msg.token_usage.cached_tokens > 0 ? (
                                <Badge variant="outline" className="text-[10px]">
                                  <Database className="h-2.5 w-2.5 mr-1" />
                                  {msg.token_usage.cached_tokens.toLocaleString()} cached tokens
                                </Badge>
                              ) : null}
                              {msg.token_usage.tokens_saved > 0 ? (
                                <Badge variant="accent" className="text-[10px]">
                                  {msg.token_usage.tokens_saved.toLocaleString()} tokens saved
                                </Badge>
                              ) : null}
                              {msg.token_usage.estimated_savings > 0 ? (
                                <Badge variant="accent" className="text-[10px]">
                                  saved ${msg.token_usage.estimated_savings < 0.01
                                    ? msg.token_usage.estimated_savings.toFixed(4)
                                    : msg.token_usage.estimated_savings.toFixed(3)}
                                </Badge>
                              ) : null}
                            </>
                          ) : (
                            <>
                              {msg.token_usage.input_tokens > 0 ? (
                                <Badge variant="outline" className="text-[10px]">
                                  {msg.token_usage.input_tokens.toLocaleString()} in
                                </Badge>
                              ) : null}
                              {msg.token_usage.output_tokens > 0 ? (
                                <Badge variant="outline" className="text-[10px]">
                                  {msg.token_usage.output_tokens.toLocaleString()} out
                                </Badge>
                              ) : null}
                              {msg.token_usage.total_tokens > 0 ? (
                                <Badge variant="outline" className="text-[10px]">
                                  {msg.token_usage.total_tokens.toLocaleString()} total
                                </Badge>
                              ) : null}
                              {msg.token_usage.estimated_cost > 0 ? (
                                <Badge variant="outline" className="text-[10px]">
                                  ${msg.token_usage.estimated_cost < 0.01
                                    ? msg.token_usage.estimated_cost.toFixed(4)
                                    : msg.token_usage.estimated_cost.toFixed(3)}
                                </Badge>
                              ) : null}
                              {msg.token_usage.tokens_saved > 0 ? (
                                <Badge variant="accent" className="text-[10px]">
                                  {msg.token_usage.tokens_saved.toLocaleString()} tokens saved from context
                                </Badge>
                              ) : null}
                            </>
                          )
                        ) : null}
                        {msg.token_usage?.pricing_stale ? (
                          <Badge variant="outline" className="text-[10px] text-yellow-500 border-yellow-500/30">
                            pricing from {msg.token_usage.pricing_updated || "unknown"}
                          </Badge>
                        ) : null}
                      </div>
                    )}

                  {/* Pipeline trace */}
                  {msg.role === "assistant" && showDebug && (
                    <PipelineTrace trace={msg.pipeline_trace || []} />
                  )}

                  {/* Sources */}
                  {msg.role === "assistant" && (
                    <SourceList sources={msg.sources || []} />
                  )}
                </div>

                {msg.role === "user" && (
                  <div className="flex-shrink-0 h-8 w-8 rounded-lg bg-accent/10 flex items-center justify-center">
                    <User className="h-4 w-4 text-accent" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-3">
                <div className="flex-shrink-0 h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Loader2 className="h-4 w-4 text-primary animate-spin" />
                </div>
                <div className="bg-muted/50 rounded-xl px-4 py-3 text-sm text-muted-foreground">
                  Running pipeline...
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </CardContent>

          {/* Input */}
          <div className="border-t border-border/40 p-4">
            <form onSubmit={(e) => { e.preventDefault(); handleSend() }} className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question..."
                aria-label="Message input"
                className="flex-1 rounded-lg border border-border/40 bg-background px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                disabled={loading}
              />
              <Button type="submit" disabled={loading || !input.trim()} size="icon">
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </Card>

        {/* Sidebar — horizontal row below chat */}
        <div className="grid grid-cols-3 gap-4">
          {/* Pipeline Trace Toggle */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center justify-between">
                <label className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Pipeline Trace
                </label>
                <button
                  onClick={() => setShowDebug(!showDebug)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                    showDebug ? "bg-primary" : "bg-muted"
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                      showDebug ? "translate-x-4.5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>
            </CardContent>
          </Card>

          {/* Pipeline Legend */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <Layers className="h-3.5 w-3.5" />
                Cache Layers
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-[10px]">
              {[
                { icon: Brain, label: "Intent Detection", desc: "Classify query type" },
                { icon: Database, label: "Exact Cache", desc: "SHA-256 key match" },
                { icon: Search, label: "Semantic Cache", desc: "Embedding similarity" },
                { icon: GitBranch, label: "Composable", desc: "Decompose & partial hit" },
                { icon: Search, label: "Fuzzy Match", desc: "Similar query suggestions" },
                { icon: Brain, label: "Agent Reasoning", desc: "LLM plans next action" },
                { icon: Search, label: "Agent Tool Call", desc: "Search, retrieve, explore" },
                { icon: Zap, label: "LLM Generation", desc: "Forward to provider" },
              ].map(({ icon: Icon, label, desc }) => (
                <div key={label} className="flex items-center gap-2 text-muted-foreground">
                  <Icon className="h-3 w-3 shrink-0" />
                  <span className="font-medium text-foreground">{label}</span>
                  <span className="ml-auto">{desc}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Conversation History */}
          <SidebarHistory
            tab={sidebarTab}
            onTabChange={setSidebarTab}
            history={history}
            onReplay={(q) => handleSend(q)}
            sessions={sessions}
            activeSessionId={activeSessionId}
            onLoadSession={handleLoadSession}
            onDeleteSession={handleDeleteSession}
          />

        </div>
      </div>
    </div>
  )
}
