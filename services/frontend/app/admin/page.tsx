"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  Zap, Database, Brain, FileText, Server, Clock, CheckCircle,
  XCircle, ArrowRight, BarChart3, Layers, MessageSquare,
  Activity, Cpu, Search, Repeat,
  RefreshCw, AlertTriangle, ChevronDown, ChevronRight,
} from "lucide-react"
import {
  PieChart, Pie, Cell,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts"
import {
  normalizeMetrics,
  type AdminMetrics,
  type NormalizedComparisonQuery,
} from "@/lib/admin-data"

// ─── Config ──────────────────────────────────────────────────────

import { getApiKey, setApiKey as persistApiKey, authHeaders, MISSING_KEY_MESSAGE } from "@/lib/api-key"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// ─── Helpers ─────────────────────────────────────────────────────

const FORMAT_COLORS: Record<string, string> = {
  PDF: "text-red-400",
  DOCX: "text-blue-400",
  HTML: "text-orange-400",
  MD: "text-green-400",
  CSV: "text-yellow-400",
  JSON: "text-purple-400",
  TEXT: "text-slate-400",
}

function formatColor(format: string): string {
  return FORMAT_COLORS[(format || "").toUpperCase()] || "text-muted-foreground"
}

function buildWithoutRows(queries: NormalizedComparisonQuery[]) {
  const rows: Array<{ query: string; time: number; status: string; tokens: number; cost: number }> = []
  for (const q of queries) {
    const tokens = q.input_tokens + q.output_tokens
    rows.push({ query: q.query, time: q.first_gen_ms, status: "Generated", tokens, cost: q.cost_per_call })
    for (let i = 0; i < q.serves; i++) {
      rows.push({ query: q.query, time: q.first_gen_ms, status: "Generated", tokens, cost: q.cost_per_call })
    }
  }
  return rows
}

function buildWithRows(queries: NormalizedComparisonQuery[]) {
  const rows: Array<{ query: string; time: number; status: string; tokens: number; cost: number }> = []
  for (const q of queries) {
    const tokens = q.input_tokens + q.output_tokens
    rows.push({ query: q.query, time: q.first_gen_ms, status: "Generated", tokens, cost: q.cost_per_call })
    for (let i = 0; i < q.serves; i++) {
      rows.push({ query: q.query, time: q.cached_serve_ms, status: "Cached", tokens: 0, cost: 0 })
    }
  }
  return rows
}

// ─── Collapsible Section ─────────────────────────────────────────

function Section({ id, title, icon: Icon, badge, children, openSections, toggle }: {
  id: string
  title: string
  icon: React.ElementType
  badge?: string
  children: React.ReactNode
  openSections: Set<string>
  toggle: (id: string) => void
}) {
  const isOpen = openSections.has(id)
  return (
    <div className="border border-border/40 rounded-lg bg-card/50 overflow-hidden">
      <button
        onClick={() => toggle(id)}
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-muted/20 transition-colors"
      >
        {isOpen
          ? <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
          : <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        }
        <Icon className="h-5 w-5 text-primary shrink-0" />
        <span className="text-sm font-semibold flex-1">{title}</span>
        {badge && (
          <Badge variant="outline" className="text-[10px] ml-auto">{badge}</Badge>
        )}
      </button>
      {isOpen && (
        <div className="px-5 pb-5 border-t border-border/20">
          <div className="pt-4">{children}</div>
        </div>
      )}
    </div>
  )
}

// ─── Helper Components ───────────────────────────────────────────

function StatCard({ label, value, subtitle, icon: Icon, accent = false }: {
  label: string; value: string; subtitle?: string; icon: React.ElementType; accent?: boolean
}) {
  return (
    <Card className="border-border/40 bg-card/50">
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
            <p className={`mt-1 text-2xl font-bold ${accent ? "text-accent" : "text-foreground"}`}>{value}</p>
            {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          <div className={`rounded-lg p-2 ${accent ? "bg-accent/10" : "bg-primary/10"}`}>
            <Icon className={`h-5 w-5 ${accent ? "text-accent" : "text-primary"}`} />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function deriveProviderHealth(item: Record<string, unknown>): "online" | "degraded" | "offline" {
  const explicit = item.status as string | undefined
  if (explicit === "online" || explicit === "active") return "online"
  if (explicit === "degraded" || explicit === "fallback") return "degraded"
  if (explicit === "offline" || explicit === "error") return "offline"
  if (explicit === "available") return "offline"
  if (item.active) return "online"
  if (item.configured) return "degraded"
  return "offline"
}

function providerDetail(item: Record<string, unknown>): string {
  if (item.display) return String(item.display)
  if (item.model) return String(item.model)
  if (item.url) return String(item.url)
  if (item.note) return String(item.note)
  const details = item.details as Record<string, unknown> | undefined
  if (details?.path) return String(details.path)
  if (item.role) return `Role: ${item.role}`
  return ""
}

function StatusDot({ health }: { health: "online" | "degraded" | "offline" }) {
  const colors: Record<string, string> = {
    online: "bg-green-500",
    degraded: "bg-yellow-500",
    offline: "bg-red-500",
  }
  const pingColors: Record<string, string> = {
    online: "bg-green-400",
    degraded: "bg-yellow-400",
    offline: "bg-red-400",
  }
  return (
    <span className="relative flex h-2.5 w-2.5">
      {health === "online" && (
        <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${pingColors[health]} opacity-75`} />
      )}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${colors[health]}`} />
    </span>
  )
}

function LoadingSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      {/* Stat cards skeleton */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-xl border border-border/20 bg-card/50 p-5">
            <div className="flex items-start justify-between">
              <div className="space-y-2 flex-1">
                <div className="h-3 w-20 bg-muted/20 rounded" />
                <div className="h-7 w-16 bg-muted/30 rounded" />
                <div className="h-2.5 w-28 bg-muted/15 rounded" />
              </div>
              <div className="h-9 w-9 bg-muted/15 rounded-lg" />
            </div>
          </div>
        ))}
      </div>

      {/* Section skeleton */}
      {[...Array(3)].map((_, i) => (
        <div key={i} className="rounded-lg border border-border/20 bg-card/50 overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-3.5">
            <div className="h-4 w-4 bg-muted/20 rounded" />
            <div className="h-5 w-5 bg-muted/20 rounded" />
            <div className="h-4 w-32 bg-muted/20 rounded" />
            <div className="ml-auto h-5 w-16 bg-muted/15 rounded-full" />
          </div>
          <div className="px-5 pb-5 border-t border-border/10">
            <div className="pt-4 space-y-3">
              {[...Array(3)].map((_, j) => (
                <div key={j} className="h-10 bg-muted/15 rounded-lg" />
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <Card className="border-border/40 bg-card/50">
      <CardContent className="p-8 text-center">
        <p className="text-sm text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  )
}

// ─── Chart Colors ────────────────────────────────────────────────

const CHART_HIT_COLOR = "#22c55e"
const CHART_MISS_COLOR = "#ef4444"
const CHART_WITHOUT_COLOR = "#ef4444"
const CHART_WITH_COLOR = "#22c55e"
const CHART_GRID_COLOR = "#333"
const CHART_TEXT_COLOR = "#a1a1aa"

interface ChartTooltipProps {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}

function ChartTooltipContent({ active, payload, label }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="rounded-lg border border-border/40 bg-card px-3 py-2 text-xs shadow-lg">
      {label && <p className="font-medium text-foreground mb-1">{label}</p>}
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color }}>
          {entry.name}: {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
        </p>
      ))}
    </div>
  )
}

function CacheHitRateChart({ hitRate }: { hitRate: number }) {
  const data = [
    { name: "Hits", value: hitRate },
    { name: "Misses", value: 100 - hitRate },
  ]
  const COLORS = [CHART_HIT_COLOR, CHART_MISS_COLOR]

  return (
    <Card className="border-border/40 bg-card/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">Cache Hit Rate</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={55}
              outerRadius={80}
              paddingAngle={3}
              dataKey="value"
              strokeWidth={0}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i]} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltipContent />} />
            <Legend
              formatter={(value: string) => <span className="text-xs text-zinc-400">{value}</span>}
            />
          </PieChart>
        </ResponsiveContainer>
        <p className="text-center text-2xl font-bold text-foreground -mt-2">{hitRate}%</p>
      </CardContent>
    </Card>
  )
}

function CostComparisonChart({ costWithout, costWith }: { costWithout: number; costWith: number }) {
  const data = [
    { name: "Without BitMod", cost: parseFloat(costWithout.toFixed(4)) },
    { name: "With BitMod", cost: parseFloat(costWith.toFixed(4)) },
  ]

  return (
    <Card className="border-border/40 bg-card/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">Cost Comparison ($)</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} barCategoryGap="30%">
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_COLOR} />
            <XAxis
              dataKey="name"
              tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
              axisLine={{ stroke: CHART_GRID_COLOR }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
              axisLine={{ stroke: CHART_GRID_COLOR }}
              tickLine={false}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip content={<ChartTooltipContent />} />
            <Bar dataKey="cost" name="Est. Cost" radius={[4, 4, 0, 0]}>
              <Cell fill={CHART_WITHOUT_COLOR} />
              <Cell fill={CHART_WITH_COLOR} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

function TokenUsageChart({ tokensWithout, tokensWith }: { tokensWithout: number; tokensWith: number }) {
  const data = [
    { name: "Without BitMod", tokens: tokensWithout },
    { name: "With BitMod", tokens: tokensWith },
  ]

  return (
    <Card className="border-border/40 bg-card/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">Token Usage</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} barCategoryGap="30%">
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_COLOR} />
            <XAxis
              dataKey="name"
              tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
              axisLine={{ stroke: CHART_GRID_COLOR }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
              axisLine={{ stroke: CHART_GRID_COLOR }}
              tickLine={false}
              tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`}
            />
            <Tooltip content={<ChartTooltipContent />} />
            <Bar dataKey="tokens" name="Tokens" radius={[4, 4, 0, 0]}>
              <Cell fill={CHART_WITHOUT_COLOR} />
              <Cell fill={CHART_WITH_COLOR} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

// ─── Page ────────────────────────────────────────────────────────

export default function AdminPage() {
  const [data, setData] = useState<AdminMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  // localStorage is unavailable during SSR, so read it on mount.
  const [apiKey, setApiKeyState] = useState("")
  useEffect(() => setApiKeyState(getApiKey()), [])
  const [secondsAgo, setSecondsAgo] = useState(0)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["cache", "comparison"]))

  const intervalRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const delayRef = useRef(30_000)

  const toggle = useCallback((id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const fetchData = useCallback(async () => {
    try {
      // /v1/admin/metrics requires admin scope. This page previously sent no
      // credentials at all, so it failed against any gateway with auth on.
      const res = await fetch(`${API_URL}/v1/admin/metrics`, { headers: authHeaders() })
      if (res.status === 401 || res.status === 403) {
        setError(MISSING_KEY_MESSAGE)
        delayRef.current = Math.min(delayRef.current * 2, 300_000)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(normalizeMetrics(json))
      setError(null)
      setLastUpdated(new Date())
      setSecondsAgo(0)
      delayRef.current = 30_000
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error"
      setError(`Could not reach API at ${API_URL}/v1/admin/metrics: ${msg}`)
      delayRef.current = Math.min(delayRef.current * 2, 300_000)
    } finally {
      setLoading(false)
      intervalRef.current = setTimeout(fetchData, delayRef.current)
    }
  }, [])

  useEffect(() => {
    fetchData()
    return () => {
      if (intervalRef.current) clearTimeout(intervalRef.current)
    }
  }, [fetchData])

  useEffect(() => {
    const tick = setInterval(() => {
      if (lastUpdated) {
        setSecondsAgo(Math.floor((Date.now() - lastUpdated.getTime()) / 1000))
      }
    }, 1000)
    return () => clearInterval(tick)
  }, [lastUpdated])

  // Derived values
  const cache = data?.cache
  const comparison = data?.comparison
  const compQueries = comparison?.queries ?? []

  const recentConvs = data?.conversations?.slice(0, 20) ?? []
  const compQuerySet = new Set(compQueries.map((q) => q.query))
  const CHARS_PER_TOKEN = 4
  const convAsCompQueries: NormalizedComparisonQuery[] = recentConvs
    .filter((c) => !compQuerySet.has(c.user_message))
    .map((c) => {
      const inputTokens = Math.max(1, Math.round(c.user_message.length / CHARS_PER_TOKEN))
      const outputTokens = Math.max(1, Math.round(c.assistant_response.length / CHARS_PER_TOKEN))
      return {
        query: c.user_message,
        first_gen_ms: c.cache_hit ? c.generation_ms * 20 : c.generation_ms,
        cached_serve_ms: c.cache_hit ? c.generation_ms : 0.5,
        serves: c.cache_hit ? 1 : 0,
        model_used: c.model_used,
        total_without_cache_ms: c.cache_hit
          ? (c.generation_ms * 20) * 2
          : c.generation_ms,
        total_with_cache_ms: c.cache_hit
          ? (c.generation_ms * 20) + c.generation_ms
          : c.generation_ms,
        savings_ms: c.cache_hit
          ? (c.generation_ms * 20) - c.generation_ms
          : 0,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cost_per_call: 0,
        total_cost_without: 0,
        total_cost_with: 0,
        cost_saved: 0,
      }
    })
  const allCompQueries = [...compQueries, ...convAsCompQueries]

  const queriesWithout = allCompQueries.length > 0 ? buildWithoutRows(allCompQueries) : []
  const queriesWith = allCompQueries.length > 0 ? buildWithRows(allCompQueries) : []

  const totalTimeWithoutMs = allCompQueries.reduce((s, q) => s + q.total_without_cache_ms, 0)
  const totalTimeWithMs = allCompQueries.reduce((s, q) => s + q.total_with_cache_ms, 0)
  const totalQueriesWithout = allCompQueries.reduce((s, q) => s + 1 + q.serves, 0)
  const totalQueriesWith = allCompQueries.length
  const savingsFactor = comparison?.savings_factor ?? 1

  const totalCostWithout = comparison?.total_cost_without ?? allCompQueries.reduce((s, q) => s + q.total_cost_without, 0)
  const totalCostWith = comparison?.total_cost_with ?? allCompQueries.reduce((s, q) => s + q.total_cost_with, 0)
  const totalCostSaved = comparison?.total_cost_saved ?? (totalCostWithout - totalCostWith)
  const totalTokensWithout = comparison?.total_tokens_without ?? allCompQueries.reduce((s, q) => s + (q.input_tokens + q.output_tokens) * (1 + q.serves), 0)
  const totalTokensWith = comparison?.total_tokens_with ?? allCompQueries.reduce((s, q) => s + q.input_tokens + q.output_tokens, 0)

  const providerGroups = data?.providers
    ? [
        { category: "LLM", icon: Brain, items: data.providers.llm },
        { category: "Database", icon: Database, items: data.providers.database },
        { category: "Embeddings", icon: Cpu, items: data.providers.embeddings },
        { category: "Vector Store", icon: Search, items: data.providers.vector_store },
      ]
    : []

  const docs = data?.documents?.documents ?? []
  const uniqueFormats = docs.length > 0 ? new Set(docs.map((d) => d.format.toUpperCase())).size : 0

  return (
    <div className="relative">
      {/* Gradient background */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/4 top-0 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-primary/8 blur-[120px]" />
        <div className="absolute right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-accent/6 blur-[100px]" />
      </div>

      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <Badge variant="accent">Admin Dashboard</Badge>
            <div className="flex items-center gap-3">
              {lastUpdated && (
                <span className="text-xs text-muted-foreground">
                  Last updated: {secondsAgo}s ago
                </span>
              )}
              <button
                onClick={fetchData}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border/40 bg-card/50 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">System Overview</h1>
          <p className="mt-2 text-muted-foreground">
            Live cache performance, provider status, and infrastructure metrics.
          </p>

          {/* /v1/admin/metrics needs admin scope. Key lives in localStorage,
              not in a NEXT_PUBLIC_ variable, for the same reason as the
              Playground: build-time inlining would publish it. */}
          <div className="mt-4 flex flex-col gap-1.5 sm:flex-row sm:items-center">
            <label htmlFor="bitmod-admin-api-key" className="text-xs text-muted-foreground sm:w-32">
              API key (admin)
            </label>
            <input
              id="bitmod-admin-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKeyState(e.target.value)
                persistApiKey(e.target.value)
                fetchData()
              }}
              placeholder="Required when the gateway has auth enabled."
              autoComplete="off"
              spellCheck={false}
              className="flex-1 rounded-md border border-border/60 bg-background/60 px-3 py-1.5 text-xs font-mono outline-none focus:border-primary/60"
            />
            <span className="text-[10px] text-muted-foreground">
              {apiKey ? "Saved in this browser" : "Not set"}
            </span>
          </div>
        </div>

        {/* Connection error banner */}
        {error && (
          <div className="mb-6 flex items-center gap-3 rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-4 py-3">
            <AlertTriangle className="h-5 w-5 text-yellow-500 shrink-0" />
            <p className="text-sm text-yellow-400 flex-1">{error}</p>
            <button
              onClick={() => {
                setLoading(true)
                setError(null)
                delayRef.current = 30_000
                if (intervalRef.current) clearTimeout(intervalRef.current)
                fetchData()
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs font-medium text-yellow-400 hover:bg-yellow-500/20 transition-colors shrink-0"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
          </div>
        )}

        {/* Loading state */}
        {loading && !data && <LoadingSkeleton />}

        {/* Content */}
        {(!loading || data) && (
          <div className="space-y-3">

            {/* ═══ Cache Performance ═══ */}
            <Section
              id="cache"
              title="Cache Performance"
              icon={BarChart3}
              badge={cache ? `${cache.hit_rate}% hit rate` : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {cache ? (
                <>
                  <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
                    <StatCard
                      label="Total Cached"
                      value={cache.total_entries.toLocaleString()}
                      subtitle={`${cache.valid_entries} valid / ${cache.invalidated_entries} invalidated`}
                      icon={Database}
                    />
                    <StatCard label="Cache Hit Rate" value={`${cache.hit_rate}%`} icon={Zap} accent />
                    <StatCard
                      label="Compute Saved"
                      value={`${cache.total_compute_saved_s.toLocaleString()}s`}
                      subtitle="Total generation time avoided"
                      icon={Clock}
                    />
                    <StatCard
                      label="Serve Count"
                      value={cache.total_serves.toLocaleString()}
                      subtitle={`Avg gen: ${cache.avg_generation_ms}ms`}
                      icon={Repeat}
                    />
                  </div>

                  <div className="mt-4">
                    <Card className="border-border/40 bg-card/50">
                      <CardContent className="p-5">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium text-muted-foreground">Cache Utilization</span>
                          <span className="text-sm font-semibold text-primary">{cache.hit_rate}%</span>
                        </div>
                        <Progress value={cache.hit_rate} />
                        <div className="flex justify-between mt-2 text-xs text-muted-foreground">
                          <span>{cache.valid_entries} valid entries</span>
                          <span>{cache.invalidated_entries} invalidated</span>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Cache Hit Rate Chart */}
                  <div className="mt-4">
                    <CacheHitRateChart hitRate={cache.hit_rate} />
                  </div>
                </>
              ) : (
                <EmptyState message="No data yet. Cache performance metrics will appear once the system starts processing queries." />
              )}
            </Section>

            {/* ═══ Without vs With BitMod Comparison ═══ */}
            <Section
              id="comparison"
              title="Without BitMod vs With BitMod"
              icon={Activity}
              badge={allCompQueries.length > 0 ? `${allCompQueries.length} queries` : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {allCompQueries.length > 0 ? (
                <>
                  {/* Summary stats */}
                  <div className="grid gap-6 lg:grid-cols-2 mb-6">
                    {/* Without BitMod stats */}
                    <Card className="border-border/40 bg-card/50">
                      <CardHeader className="pb-2 bg-destructive/5 border-b border-border/20">
                        <CardTitle className="text-base flex items-center gap-2">
                          <XCircle className="h-5 w-5 text-red-400" />
                          Without BitMod
                          <Badge variant="destructive" className="text-[10px] ml-auto">Redundant Calls</Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-4">
                        <div className="grid grid-cols-4 gap-3 text-center">
                          <div>
                            <p className="text-xs text-muted-foreground">API Calls</p>
                            <p className="text-2xl font-bold text-red-400">{totalQueriesWithout}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Total Time</p>
                            <p className="text-2xl font-bold text-red-400">{(totalTimeWithoutMs / 1000).toFixed(1)}s</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Total Tokens</p>
                            <p className="text-2xl font-bold text-red-400">{totalTokensWithout.toLocaleString()}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Est. Cost</p>
                            <p className="text-2xl font-bold text-red-400">${totalCostWithout.toFixed(4)}</p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    {/* With BitMod stats */}
                    <Card className="border-border/40 bg-card/50 ring-1 ring-primary/20">
                      <CardHeader className="pb-2 bg-primary/5 border-b border-border/20">
                        <CardTitle className="text-base flex items-center gap-2">
                          <CheckCircle className="h-5 w-5 text-green-400" />
                          With BitMod
                          <Badge variant="accent" className="text-[10px] ml-auto">Intelligent Cache</Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-4">
                        <div className="grid grid-cols-5 gap-3 text-center">
                          <div>
                            <p className="text-xs text-muted-foreground">LLM Calls</p>
                            <p className="text-2xl font-bold text-green-400">{totalQueriesWith}</p>
                            <p className="text-[10px] text-muted-foreground">
                              + {totalQueriesWithout - totalQueriesWith} cache hits
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Total Time</p>
                            <p className="text-2xl font-bold text-green-400">{(totalTimeWithMs / 1000).toFixed(1)}s</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Total Tokens</p>
                            <p className="text-2xl font-bold text-green-400">{totalTokensWith.toLocaleString()}</p>
                            <p className="text-[10px] text-muted-foreground">
                              {totalTokensWithout > 0 ? `-${Math.round((1 - totalTokensWith / totalTokensWithout) * 100)}%` : ""}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Est. Cost</p>
                            <p className="text-2xl font-bold text-green-400">${totalCostWith.toFixed(4)}</p>
                            <p className="text-[10px] text-muted-foreground">
                              saved ${totalCostSaved.toFixed(4)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Savings Factor</p>
                            <p className="text-2xl font-bold text-green-400">{savingsFactor.toFixed(1)}x</p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Cost & Token Charts */}
                  <div className="grid gap-4 lg:grid-cols-2 mb-6">
                    <CostComparisonChart costWithout={totalCostWithout} costWith={totalCostWith} />
                    <TokenUsageChart tokensWithout={totalTokensWithout} tokensWith={totalTokensWith} />
                  </div>

                  {/* Query detail lists */}
                  <div className="grid gap-6 lg:grid-cols-2">
                    {/* Without BitMod queries */}
                    <Card className="border-border/40 bg-card/50 overflow-hidden">
                      <CardHeader className="pb-3 border-b border-border/20">
                        <CardTitle className="text-sm text-muted-foreground">Query Log — Without Cache</CardTitle>
                      </CardHeader>
                      <CardContent className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                        {queriesWithout.map((q, i) => (
                          <div key={i} className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2.5 text-sm">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-muted-foreground text-xs font-mono w-4 shrink-0">#{i + 1}</span>
                              <span className="truncate text-muted-foreground text-xs">{q.query}</span>
                            </div>
                            <div className="flex items-center gap-3 shrink-0 ml-2">
                              {q.tokens > 0 && (
                                <span className="text-[10px] font-mono text-muted-foreground">{q.tokens.toLocaleString()} tok</span>
                              )}
                              {q.cost > 0 && (
                                <span className="text-[10px] font-mono text-red-400/70">${q.cost.toFixed(4)}</span>
                              )}
                              <span className="text-xs font-mono text-red-400">{q.time}ms</span>
                              <Badge variant="secondary" className="text-[10px]">{q.status}</Badge>
                            </div>
                          </div>
                        ))}
                      </CardContent>
                    </Card>

                    {/* With BitMod queries */}
                    <Card className="border-border/40 bg-card/50 overflow-hidden ring-1 ring-primary/20">
                      <CardHeader className="pb-3 border-b border-border/20">
                        <CardTitle className="text-sm text-muted-foreground">Query Log — With Cache</CardTitle>
                      </CardHeader>
                      <CardContent className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                        {queriesWith.map((q, i) => (
                          <div key={i} className={`flex items-center justify-between rounded-lg px-3 py-2.5 text-sm ${
                            q.status === "Cached" ? "bg-primary/5 border border-primary/10" : "bg-muted/30"
                          }`}>
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-muted-foreground text-xs font-mono w-4 shrink-0">#{i + 1}</span>
                              <span className="truncate text-muted-foreground text-xs">{q.query}</span>
                            </div>
                            <div className="flex items-center gap-3 shrink-0 ml-2">
                              {q.status === "Cached" ? (
                                <span className="text-[10px] font-mono text-green-400/70">$0</span>
                              ) : q.cost > 0 ? (
                                <span className="text-[10px] font-mono text-muted-foreground">${q.cost.toFixed(4)}</span>
                              ) : null}
                              {q.tokens > 0 && (
                                <span className="text-[10px] font-mono text-muted-foreground">{q.tokens.toLocaleString()} tok</span>
                              )}
                              <span className={`text-xs font-mono ${q.status === "Cached" ? "text-green-400" : "text-foreground"}`}>
                                {q.time < 1 ? `${q.time.toFixed(1)}ms` : `${q.time}ms`}
                              </span>
                              <Badge variant={q.status === "Cached" ? "default" : "secondary"} className="text-[10px]">
                                {q.status === "Cached" ? <><Zap className="h-2.5 w-2.5 mr-0.5" /> Cached</> : q.status}
                              </Badge>
                            </div>
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  </div>
                </>
              ) : (
                <EmptyState message="No data yet. Model comparison data will appear once queries have been processed and cached." />
              )}
            </Section>

            {/* ═══ Session Log ═══ */}
            <Section
              id="sessions"
              title="Session Log"
              icon={MessageSquare}
              badge={data?.conversations && data.conversations.length > 0 ? `${data.conversations.length} sessions` : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {data?.conversations && data.conversations.length > 0 ? (
                <Card className="border-border/40 bg-card/50 overflow-hidden">
                  <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-10">
                        <tr className="border-b border-border/40 bg-muted/30">
                          <th className="px-4 py-3 text-left font-medium text-muted-foreground">Time</th>
                          <th className="px-4 py-3 text-left font-medium text-muted-foreground">Query</th>
                          <th className="px-4 py-3 text-left font-medium text-muted-foreground">Response</th>
                          <th className="px-4 py-3 text-center font-medium text-muted-foreground">Status</th>
                          <th className="px-4 py-3 text-right font-medium text-muted-foreground">Model</th>
                          <th className="px-4 py-3 text-right font-medium text-muted-foreground">Latency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.conversations.map((conv) => (
                          <tr key={conv.id} className="border-b border-border/20 hover:bg-muted/20 transition-colors">
                            <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap font-mono">
                              {conv.created_at
                                ? new Date(conv.created_at).toLocaleString(undefined, {
                                    month: "short", day: "numeric",
                                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                                  })
                                : "\u2014"}
                            </td>
                            <td className="px-4 py-3 max-w-[250px]">
                              <span className="truncate block text-foreground" title={conv.user_message}>
                                {conv.user_message.slice(0, 80)}{conv.user_message.length > 80 ? "..." : ""}
                              </span>
                            </td>
                            <td className="px-4 py-3 max-w-[300px]">
                              <span className="truncate block text-muted-foreground text-xs" title={conv.assistant_response}>
                                {conv.assistant_response.slice(0, 100)}{conv.assistant_response.length > 100 ? "..." : ""}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              {conv.cache_hit ? (
                                <Badge variant="accent" className="text-[10px]">
                                  <Zap className="h-2.5 w-2.5 mr-0.5" /> Cached
                                </Badge>
                              ) : (
                                <Badge variant="secondary" className="text-[10px]">
                                  <Brain className="h-2.5 w-2.5 mr-0.5" /> Generated
                                </Badge>
                              )}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className="text-xs font-mono text-muted-foreground">{conv.model_used}</span>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className={`text-xs font-mono ${conv.cache_hit ? "text-green-400" : "text-foreground"}`}>
                                {conv.generation_ms < 1000
                                  ? `${conv.generation_ms}ms`
                                  : `${(conv.generation_ms / 1000).toFixed(1)}s`}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              ) : (
                <EmptyState message="No sessions yet. Conversations from the playground will appear here in real time." />
              )}
            </Section>

            {/* ═══ Recent Prompts ═══ */}
            <Section
              id="prompts"
              title="Recent Prompts"
              icon={Clock}
              badge={recentConvs.length > 0 ? `Last ${recentConvs.length}` : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {recentConvs.length > 0 ? (
                <Card className="border-border/40 bg-card/50 overflow-hidden">
                  <CardContent className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                    {recentConvs.map((conv, i) => (
                      <div key={conv.id || i} className={`flex items-center justify-between rounded-lg px-3 py-2.5 text-sm ${
                        conv.cache_hit ? "bg-primary/5 border border-primary/10" : "bg-muted/30"
                      }`}>
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <span className="text-muted-foreground text-xs font-mono w-4 shrink-0">#{i + 1}</span>
                          <span className="truncate text-xs" title={conv.user_message}>
                            {conv.user_message.slice(0, 80)}{conv.user_message.length > 80 ? "..." : ""}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 shrink-0 ml-2">
                          <span className="text-[10px] font-mono text-muted-foreground hidden sm:inline">
                            {conv.created_at
                              ? new Date(conv.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
                              : ""}
                          </span>
                          <span className={`text-xs font-mono ${conv.cache_hit ? "text-green-400" : "text-foreground"}`}>
                            {conv.generation_ms < 1000
                              ? `${conv.generation_ms}ms`
                              : `${(conv.generation_ms / 1000).toFixed(1)}s`}
                          </span>
                          <Badge variant={conv.cache_hit ? "default" : "secondary"} className="text-[10px] w-[72px] justify-center">
                            {conv.cache_hit ? <><Zap className="h-2.5 w-2.5 mr-0.5" /> Cached</> : <><Brain className="h-2.5 w-2.5 mr-0.5" /> Generated</>}
                          </Badge>
                          <span className="text-[10px] font-mono text-muted-foreground hidden md:inline w-[80px] text-right truncate">
                            {conv.model_used}
                          </span>
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ) : (
                <EmptyState message="No prompts yet. Send queries from the playground to see them here." />
              )}
            </Section>

            {/* ═══ Multi-Format Ingestion ═══ */}
            <Section
              id="documents"
              title="Multi-Format Ingestion"
              icon={FileText}
              badge={docs.length > 0 ? `${docs.length} docs` : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {docs.length > 0 ? (
                <Card className="border-border/40 bg-card/50 overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/40 bg-muted/30">
                          <th className="px-4 py-3 text-left font-medium text-muted-foreground">Document</th>
                          <th className="px-4 py-3 text-left font-medium text-muted-foreground">Format</th>
                          <th className="px-4 py-3 text-right font-medium text-muted-foreground">Sections</th>
                          <th className="px-4 py-3 text-right font-medium text-muted-foreground">Chunks</th>
                          <th className="px-4 py-3 text-center font-medium text-muted-foreground">Status</th>
                          <th className="px-4 py-3 text-right font-medium text-muted-foreground">Ingested</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docs.map((doc, i) => (
                          <tr key={`${doc.title}-${i}`} className="border-b border-border/20 hover:bg-muted/20 transition-colors">
                            <td className="px-4 py-3 font-medium">{doc.title}</td>
                            <td className="px-4 py-3">
                              <Badge variant="outline" className={`text-[10px] font-mono ${formatColor(doc.format)}`}>
                                {doc.format.toUpperCase()}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-muted-foreground">{doc.sections.toLocaleString()}</td>
                            <td className="px-4 py-3 text-right font-mono text-muted-foreground">{doc.chunks.toLocaleString()}</td>
                            <td className="px-4 py-3 text-center">
                              <Badge variant="default" className="text-[10px]">
                                <CheckCircle className="h-2.5 w-2.5 mr-1" />
                                Embedded
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-xs text-muted-foreground">
                              {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "\u2014"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr className="bg-muted/20">
                          <td className="px-4 py-3 font-semibold">Total</td>
                          <td className="px-4 py-3"><span className="text-xs text-muted-foreground">{uniqueFormats} format{uniqueFormats !== 1 ? "s" : ""}</span></td>
                          <td className="px-4 py-3 text-right font-mono font-semibold">
                            {docs.reduce((s, d) => s + d.sections, 0).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-right font-mono font-semibold">
                            {docs.reduce((s, d) => s + d.chunks, 0).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <Badge variant="accent" className="text-[10px]">All Embedded</Badge>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs text-muted-foreground">
                            {docs.length} doc{docs.length !== 1 ? "s" : ""}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </Card>
              ) : (
                <EmptyState message="No data yet. Ingested documents will appear here once files are processed." />
              )}
            </Section>

            {/* ═══ Provider Status ═══ */}
            <Section
              id="providers"
              title="Provider Status"
              icon={Server}
              badge={providerGroups.filter((g) => g.items.length > 0).length > 0
                ? `${providerGroups.filter((g) => g.items.length > 0).length} active`
                : undefined}
              openSections={openSections}
              toggle={toggle}
            >
              {providerGroups.some((g) => g.items.length > 0) ? (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  {providerGroups.map((group) => (
                    <Card key={group.category} className="border-border/40 bg-card/50">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm text-muted-foreground uppercase tracking-wider">{group.category}</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {group.items.length > 0 ? (
                          group.items.map((item, idx) => {
                            const health = deriveProviderHealth(item)
                            const detail = providerDetail(item)
                            const name = String(item.name ?? "unknown")
                            const status = String(item.status ?? "")
                            const badgeVariant = health === "online" ? "default" : health === "degraded" ? "secondary" : "outline"
                            const badgeLabel = status === "active" ? "active" : status === "fallback" ? "fallback" : status === "available" ? "available" : health
                            return (
                              <div key={`${name}-${idx}`} className="flex items-center gap-3">
                                <StatusDot health={health} />
                                <div className="min-w-0 flex-1">
                                  <p className="text-sm font-medium truncate">{name}</p>
                                  {detail && <p className="text-[10px] text-muted-foreground truncate">{detail}</p>}
                                </div>
                                <Badge variant={badgeVariant} className="text-[10px] shrink-0">
                                  {badgeLabel}
                                </Badge>
                              </div>
                            )
                          })
                        ) : (
                          <p className="text-xs text-muted-foreground">No providers configured</p>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <EmptyState message="No data yet. Provider status will appear once the system is configured." />
              )}
            </Section>

            {/* ═══ Agentic Action Plans ═══ */}
            <Section
              id="agentic"
              title="Agentic Action Plans"
              icon={Layers}
              openSections={openSections}
              toggle={toggle}
            >
              <p className="text-sm text-muted-foreground mb-4">
                LLM reasons once to create an execution plan. All subsequent runs replay the plan deterministically with zero LLM calls.
              </p>

              <Card className="border-border/40 bg-card/50 mb-4">
                <CardContent className="p-5">
                  <div className="flex flex-wrap items-center justify-center gap-3 text-sm">
                    <div className="rounded-lg bg-primary/10 border border-primary/20 px-4 py-2 text-primary font-medium flex items-center gap-2">
                      <Brain className="h-4 w-4" />
                      LLM Reasons
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="rounded-lg bg-accent/10 border border-accent/20 px-4 py-2 text-accent font-medium flex items-center gap-2">
                      <Database className="h-4 w-4" />
                      Plan Cached
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="rounded-lg bg-green-500/10 border border-green-500/20 px-4 py-2 text-green-400 font-medium flex items-center gap-2">
                      <Repeat className="h-4 w-4" />
                      Deterministic Replay
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="rounded-lg bg-muted/50 border border-border/40 px-4 py-2 text-muted-foreground font-medium flex items-center gap-2">
                      <Zap className="h-4 w-4 text-accent" />
                      0 LLM Calls
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="mt-4 border-accent/20 bg-accent/5">
                <CardContent className="p-5 flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-muted-foreground">Total Action Plan Savings</p>
                    <p className="text-2xl font-extrabold text-accent">0s</p>
                    <p className="text-xs text-muted-foreground">of LLM compute avoided through deterministic replay</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium text-muted-foreground">Total Replays</p>
                    <p className="text-2xl font-extrabold text-primary">0</p>
                    <p className="text-xs text-muted-foreground">zero-cost plan executions</p>
                  </div>
                </CardContent>
              </Card>
            </Section>

          </div>
        )}
      </div>
    </div>
  )
}
