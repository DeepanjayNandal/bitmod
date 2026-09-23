import type { Metadata } from "next"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  ArrowRight, DollarSign, Zap, Layers, FileDown, TrendingDown
} from "lucide-react"

export const metadata: Metadata = {
  title: "Cost Reduction | BitMod",
  description: "Cut LLM API costs by 90% or more with BitMod intelligent caching. Eliminate redundant calls, reduce latency, and keep your data on your servers.",
}

export default function CostReductionPage() {
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
            Solutions
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Cut LLM Costs
            </span>
            <br />
            <span className="text-foreground">by 90%+</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            BitMod&apos;s 9-layer intelligent cache intercepts redundant LLM calls before they
            happen. Exact match, semantic similarity, composable decomposition &mdash; all running
            on your infrastructure.
          </p>
        </div>
      </section>

      {/* Visual Comparison */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            The math is simple
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Same questions, dramatically different bills.
          </p>
        </div>

        <div className="mx-auto max-w-4xl grid gap-8 md:grid-cols-2">
          {/* Without BitMod */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">without-bitmod.txt</span>
            </div>
            <div className="p-6 space-y-4">
              <div className="text-sm font-mono text-[#8b949e]">Daily API usage</div>
              <div className="space-y-2">
                <div className="flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3]">Queries</span>
                  <span className="text-[#ff7b72] font-bold">1,000</span>
                </div>
                <div className="flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3]">Cost per query</span>
                  <span className="text-[#ff7b72]">$0.03</span>
                </div>
                <div className="border-t border-border/20 pt-2 flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3] font-bold">Daily total</span>
                  <span className="text-[#ff7b72] font-bold text-lg">$30.00</span>
                </div>
              </div>
              <div className="text-xs text-[#8b949e] italic">Every query hits the LLM API</div>
            </div>
          </div>

          {/* With BitMod */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">with-bitmod.txt</span>
            </div>
            <div className="p-6 space-y-4">
              <div className="text-sm font-mono text-[#8b949e]">Daily API usage</div>
              <div className="space-y-2">
                <div className="flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3]">Unique queries</span>
                  <span className="text-[#79c0ff]">1 &times; $0.03</span>
                </div>
                <div className="flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3]">Cache hits</span>
                  <span className="text-[#7ee787] font-bold">999 &times; $0.00</span>
                </div>
                <div className="border-t border-border/20 pt-2 flex justify-between text-sm font-mono">
                  <span className="text-[#e6edf3] font-bold">Daily total</span>
                  <span className="text-[#7ee787] font-bold text-lg">$0.03</span>
                </div>
              </div>
              <div className="text-xs text-[#7ee787]">99.9% served from cache</div>
            </div>
          </div>
        </div>
      </section>

      {/* How Costs Are Reduced */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Three layers of{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              cost elimination
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Each layer independently reduces your LLM spend.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-3">
          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <Zap className="h-10 w-10 text-yellow-500 mb-2" />
              <CardTitle className="text-lg">9-Layer Intelligent Cache</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                BitMod&apos;s intelligent cache learns your application&apos;s patterns. Exact, semantic,
                composable, and fuzzy matching eliminate redundant LLM calls automatically.
              </CardDescription>
            </CardContent>
          </Card>

          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <FileDown className="h-10 w-10 text-primary mb-2" />
              <CardTitle className="text-lg">Block Compression</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                Three compression levels &mdash; full, structured, and headline &mdash; reduce the token
                count sent to LLMs. Less context means fewer input tokens, which means lower cost
                per query even on cache misses.
              </CardDescription>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="border-y border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            {[
              { value: "90%+", label: "Cost Reduction", icon: TrendingDown },
              { value: "68-82ms", label: "Cached, over HTTP", icon: Zap },
              { value: "0", label: "LLM Calls on Hit", icon: DollarSign },
              { value: "3", label: "Compression Levels", icon: Layers },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <stat.icon className="mx-auto h-6 w-6 text-primary mb-2" />
                <div className="text-3xl font-bold text-foreground">{stat.value}</div>
                <div className="text-sm text-muted-foreground">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Stop paying for{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            answers that already exist
          </span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Install BitMod, point it at your data, and watch your LLM costs drop. One command to set up, instant savings.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/docs">
              Read the Docs <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
