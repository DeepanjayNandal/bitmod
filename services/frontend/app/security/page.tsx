import type { Metadata } from "next"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Shield, Lock, Key, Eye, FileCheck,
  ArrowRight, Zap, CheckCircle, HardDrive, ScrollText,
  KeyRound, Ban, Users, ShieldAlert, Target, TrendingUp,
  BookOpen
} from "lucide-react"

export const metadata: Metadata = {
  title: "Security | BitMod",
  description: "Defense-in-depth security: API key management, JWT auth, HMAC plan integrity, rate limiting, source version locking, and responsible disclosure policy.",
}

const SECURITY_LAYERS = [
  {
    name: "API Gateway",
    desc: "Rate limiting, CORS enforcement, security headers on every response",
    color: "text-[#79c0ff]",
    borderColor: "border-[#79c0ff]/20",
    bgColor: "bg-[#79c0ff]/5",
    icon: Zap,
  },
  {
    name: "Authentication",
    desc: "API key (SHA-256 hashed) + JWT token exchange, no plaintext secrets",
    color: "text-[#ffa657]",
    borderColor: "border-[#ffa657]/20",
    bgColor: "bg-[#ffa657]/5",
    icon: Key,
  },
  {
    name: "Authorization",
    desc: "Scope-based access control, privilege escalation prevention",
    color: "text-[#7ee787]",
    borderColor: "border-[#7ee787]/20",
    bgColor: "bg-[#7ee787]/5",
    icon: Eye,
  },
  {
    name: "Data Integrity",
    desc: "HMAC-SHA256 signatures on action plans, tamper detection on replay",
    color: "text-[#d2a8ff]",
    borderColor: "border-[#d2a8ff]/20",
    bgColor: "bg-[#d2a8ff]/5",
    icon: FileCheck,
  },
  {
    name: "Cache Security",
    desc: "Verified responses, source version locking, tamper-proof cached answers",
    color: "text-[#ff7b72]",
    borderColor: "border-[#ff7b72]/20",
    bgColor: "bg-[#ff7b72]/5",
    icon: Shield,
  },
]

const SECURITY_FEATURES = [
  {
    title: "Authentication On By Default",
    desc: "BITMOD_AUTH_ENABLED defaults to true, so an unconfigured deployment rejects unauthenticated requests with 401. Set it to 0 to allow anonymous access — opting out is explicit. Note that /v1/chat is unauthenticated while /v1/chat/completions, the drop-in proxy path, is not, and /v1/admin/* additionally requires a key with admin scope.",
    icon: Lock,
    color: "text-[#7ee787]",
  },
  {
    title: "API Key Management",
    desc: "Database-backed key storage with SHA-256 hashing. Keys are never stored in plaintext — only their hashes are persisted, making key extraction from a database breach impossible.",
    icon: Key,
    color: "text-[#ffa657]",
  },
  {
    title: "JWT Token Exchange",
    desc: "Stateless authentication with configurable expiry and scope-based claims. API keys are exchanged for short-lived JWTs that carry only the permissions needed.",
    icon: Lock,
    color: "text-[#79c0ff]",
  },
  {
    title: "Rate Limiting",
    desc: "Configurable rate limiting — default 60 requests per minute per key (BITMOD_RATE_LIMIT). Per-key and global limits protect upstream providers and ensure fair resource allocation. Tier-based rate limiting is on the roadmap.",
    icon: Zap,
    color: "text-[#7ee787]",
  },
  {
    title: "HMAC Plan Integrity",
    desc: "Every action plan is cryptographically signed with HMAC-SHA256. Tampered plans are rejected before execution.",
    icon: FileCheck,
    color: "text-[#d2a8ff]",
  },
  {
    title: "Source Version Locking",
    desc: "Cache entries are locked to the SHA-256 hash of their source documents. When source data changes, dependent cache entries are automatically invalidated — no stale answers.",
    icon: Shield,
    color: "text-[#ff7b72]",
  },
  {
    title: "Security Headers",
    desc: "HSTS, X-Content-Type-Options, X-Frame-Options, and Content-Security-Policy headers on every response. Defense-in-depth at the HTTP layer.",
    icon: Eye,
    color: "text-green-400",
  },
  {
    title: "Encryption at Rest",
    desc: "AES-256-GCM envelope encryption for sensitive data. Key encryption key (KEK) loaded from environment variable or file. Optional and backwards-compatible — enable it when you need it.",
    icon: HardDrive,
    color: "text-cyan-400",
  },
  {
    title: "Audit Logging",
    desc: "Full event system tracking auth success/failure, key creation/revocation, rate limit blocks, and injection detections. Every event records actor, action, outcome, source IP, and correlation ID.",
    icon: ScrollText,
    color: "text-amber-400",
  },
  {
    title: "JWT RS256 Signing",
    desc: "Asymmetric RS256 signing support alongside HS256. Auto-generates key pairs on first run. Exposes a JWKS endpoint for external token verification by downstream services.",
    icon: KeyRound,
    color: "text-indigo-400",
  },
  {
    title: "Token Revocation",
    desc: "Every JWT carries a unique jti claim. Bounded revocation store enables immediate token invalidation without waiting for expiry. Constant-time lookup, automatic cleanup.",
    icon: Ban,
    color: "text-rose-400",
  },
  {
    title: "Per-Tenant Rate Limiting",
    desc: "API key-based rate limit buckets in addition to IP-based limiting. Each tenant gets independent counters, preventing noisy-neighbor issues in multi-tenant deployments.",
    icon: Users,
    color: "text-teal-400",
  },
  {
    title: "LLM Output Filtering",
    desc: "Scans LLM responses for injection markers, tool definition leakage, and system prompt fragment exposure. Detects and blocks prompt injection attempts before they reach your users.",
    icon: ShieldAlert,
    color: "text-orange-400",
  },
]

export default function SecurityPage() {
  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      {/* Hero */}
      <section className="mx-auto max-w-7xl px-4 pt-20 pb-16 sm:px-6 sm:pt-28 sm:pb-24 lg:px-8">
        <div className="text-center">
          <Badge variant="accent" className="mb-6 px-4 py-1.5 text-sm">
            Security
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl">
            <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
              Security First.
            </span>
            <br />
            <span className="text-foreground">Always.</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            BitMod is designed with security at every layer &mdash; from API key
            management and cryptographic action plan integrity to namespace isolation and source-aware
            cache invalidation.
          </p>
        </div>
      </section>

      {/* Security Architecture Flow Diagram */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Architecture</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Defense in depth.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Every layer secured.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Every request passes through five security layers before any data is returned.
          </p>
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 overflow-hidden shadow-2xl">
            {/* Incoming request */}
            <div className="text-center mb-4">
              <div className="inline-flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20 px-5 py-2.5 text-primary font-semibold text-sm arch-node">
                <Lock className="h-4 w-4" />
                Incoming Request
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground font-mono">
                Authorization: Bearer sk-bitmod-...
              </div>
            </div>

            {/* Security layer cards with pulse connectors */}
            {SECURITY_LAYERS.map((layer, i) => (
              <div key={layer.name}>
                {/* Animated connector */}
                <div className="flex justify-center">
                  <div
                    className="w-px h-8 bg-gradient-to-b from-primary/60 to-primary/20 animate-flow-pulse"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                </div>

                {/* Layer node */}
                <div className={`rounded-lg ${layer.bgColor} border ${layer.borderColor} p-4 arch-node`}>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center h-8 w-8 rounded-full bg-muted/20 border border-border/20 shrink-0">
                      <layer.icon className={`h-4 w-4 ${layer.color}`} />
                    </div>
                    <div className="min-w-0">
                      <div className={`text-sm font-semibold ${layer.color}`}>{layer.name}</div>
                      <div className="text-[11px] text-muted-foreground leading-tight">{layer.desc}</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Final connector */}
            <div className="flex justify-center">
              <div
                className="w-px h-8 bg-gradient-to-b from-green-400/60 to-green-400/20 animate-flow-pulse"
                style={{ animationDelay: "0.9s" }}
              />
            </div>

            {/* Verified response */}
            <div className="text-center">
              <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold text-sm arch-node">
                <CheckCircle className="h-4 w-4" />
                Verified Response
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">
                Authenticated, authorized, integrity-checked, and served
              </p>
            </div>
          </div>
        </div>
      </section>

      <Separator />

      {/* Key Security Features */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Features</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Built-in security.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Not bolted on.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Every security feature ships with the core engine. No plugins, no add-ons, no extra cost.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {SECURITY_FEATURES.map((feature) => (
            <Card
              key={feature.title}
              className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg"
            >
              <CardHeader className="pb-2">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-muted/20 border border-border/20 shrink-0">
                    <feature.icon className={`h-5 w-5 ${feature.color}`} />
                  </div>
                  <CardTitle className="text-lg">{feature.title}</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">
                  {feature.desc}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      <Separator />

      {/* Compliance */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Compliance</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Your data.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Your infrastructure.
            </span>
          </h2>
        </div>

        <div className="mx-auto max-w-2xl">
          <Card className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardContent className="p-6 sm:p-8">
              <div className="flex items-start gap-4">
                <div className="flex items-center justify-center h-12 w-12 rounded-lg bg-green-500/10 border border-green-500/20 shrink-0">
                  <Shield className="h-6 w-6 text-green-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Self-Hosted Data Sovereignty</h3>
                  <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                    All data stays on your infrastructure. Cache entries never leave your deployment.
                    BitMod runs entirely within your environment &mdash; no external calls, no shared
                    state, no telemetry. Full air-gap support for regulated industries and
                    sensitive workloads.
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {["Self-hosted data sovereignty", "Air-gap deployment support", "Zero external telemetry", "Full audit control"].map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1.5 rounded-full bg-green-500/10 border border-green-500/20 px-3 py-1 text-xs text-green-400 font-medium"
                      >
                        <CheckCircle className="h-3 w-3" />
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Security Maturity Roadmap */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Roadmap</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Security maturity{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              is a journey.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Where we are today, and where we&apos;re headed.
          </p>
        </div>

        <div className="mx-auto max-w-3xl space-y-0">
          {[
            {
              phase: "Phase 1 — Foundation",
              status: "complete" as const,
              items: [
                "SHA-256 API key hashing & JWT token exchange",
                "HMAC-SHA256 action plan integrity verification",
                "Rate limiting (per-key and global)",
                "Security headers (HSTS, CSP, X-Frame-Options)",
                "Source version locking for cache integrity",
                "LLM output filtering & injection detection",
              ],
            },
            {
              phase: "Phase 2 — Encryption & Audit",
              status: "complete" as const,
              items: [
                "AES-256-GCM envelope encryption at rest",
                "RS256 asymmetric JWT signing with JWKS endpoint",
                "Token revocation with bounded jti store",
                "Full audit event logging with correlation IDs",
                "Per-tenant rate limiting buckets",
              ],
            },
            {
              phase: "Phase 3 — Enterprise Authentication",
              status: "in-progress" as const,
              items: [
                "SSO / SAML / OAuth2 provider integration",
                "Role-based access control (RBAC) with custom roles",
                "Namespace-level permission boundaries",
                "Secrets management (SOPS / Vault integration)",
                "Tier-based rate limiting with usage quotas",
              ],
            },
            {
              phase: "Phase 4 — Compliance & Certification",
              status: "planned" as const,
              items: [
                "SOC 2 Type II audit preparation",
                "HIPAA compliance bundle for healthcare deployments",
                "GDPR data handling & right-to-erasure support",
                "FedRAMP readiness for government workloads",
                "Penetration testing program with third-party auditors",
              ],
            },
          ].map((phase, i) => (
            <div key={phase.phase} className="relative pl-8">
              {/* Timeline line */}
              {i < 3 && (
                <div className="absolute left-[11px] top-10 bottom-0 w-px bg-border/40" />
              )}
              {/* Timeline dot */}
              <div className={`absolute left-0 top-2 h-6 w-6 rounded-full border-2 flex items-center justify-center ${
                phase.status === "complete"
                  ? "bg-green-500/20 border-green-500/60"
                  : phase.status === "in-progress"
                  ? "bg-primary/20 border-primary/60"
                  : "bg-muted/20 border-border/60"
              }`}>
                {phase.status === "complete" ? (
                  <CheckCircle className="h-3 w-3 text-green-400" />
                ) : phase.status === "in-progress" ? (
                  <TrendingUp className="h-3 w-3 text-primary" />
                ) : (
                  <Target className="h-3 w-3 text-muted-foreground" />
                )}
              </div>

              <div className="pb-10">
                <div className="flex items-center gap-3 mb-3">
                  <h3 className="text-lg font-semibold">{phase.phase}</h3>
                  <Badge className={
                    phase.status === "complete"
                      ? "bg-green-500/15 text-green-400 border-green-500/30"
                      : phase.status === "in-progress"
                      ? "bg-primary/15 text-primary border-primary/30"
                      : "bg-muted/15 text-muted-foreground border-border/30"
                  }>
                    {phase.status === "complete" ? "Complete" : phase.status === "in-progress" ? "In Progress" : "Planned"}
                  </Badge>
                </div>
                <ul className="space-y-2">
                  {phase.items.map((item) => (
                    <li key={item} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <CheckCircle className={`h-4 w-4 shrink-0 mt-0.5 ${
                        phase.status === "complete" ? "text-green-400" : "text-border"
                      }`} />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>

      <Separator />

      {/* Best Practices */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Best Practices</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Secure your{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              BitMod deployment.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Follow these recommendations to harden your installation.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              icon: Key,
              title: "Rotate API Keys Regularly",
              desc: "Generate new API keys on a schedule. Revoke unused keys immediately. Use scoped keys with minimum permissions for each integration.",
              color: "text-[#ffa657]",
            },
            {
              icon: Lock,
              title: "Enable Encryption at Rest",
              desc: "Set BITMOD_ENCRYPTION_KEY in your environment to activate AES-256-GCM encryption. Store the key in a secrets manager — never commit it to version control.",
              color: "text-[#79c0ff]",
            },
            {
              icon: Shield,
              title: "Use Network Isolation",
              desc: "Run BitMod behind a reverse proxy. Restrict database ports to internal networks. Use TLS for all connections between services.",
              color: "text-[#7ee787]",
            },
            {
              icon: ScrollText,
              title: "Monitor Audit Logs",
              desc: "Pipe BitMod audit events to your SIEM or log aggregator. Set alerts for repeated auth failures, rate limit blocks, and injection detections.",
              color: "text-amber-400",
            },
            {
              icon: Users,
              title: "Scope Namespaces",
              desc: "Use separate namespaces for different teams or environments. Each namespace has independent cache isolation — a breach in one doesn't affect others.",
              color: "text-teal-400",
            },
            {
              icon: BookOpen,
              title: "Keep BitMod Updated",
              desc: "Run bitmod update regularly to get the latest security patches. Subscribe to our GitHub security advisories to be notified of critical fixes.",
              color: "text-indigo-400",
            },
          ].map((practice) => (
            <Card
              key={practice.title}
              className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg"
            >
              <CardHeader className="pb-2">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-muted/20 border border-border/20 shrink-0">
                    <practice.icon className={`h-5 w-5 ${practice.color}`} />
                  </div>
                  <CardTitle className="text-lg">{practice.title}</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">
                  {practice.desc}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      {/* Help Shape BitMod */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Help shape{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            BitMod security.
          </span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Report vulnerabilities, request features, explore enterprise solutions, or review our full security policy.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/contact">
              Contact Us <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
          <Button size="xl" variant="outline" asChild>
            <Link href="/docs">
              Read the Docs
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
