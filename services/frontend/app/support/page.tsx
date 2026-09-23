import type { Metadata } from "next"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import {
  MessageCircle, Book, ArrowRight, Zap, HelpCircle,
  Bug, Lightbulb, Users
} from "lucide-react"

export const metadata: Metadata = {
  title: "Support | BitMod",
  description: "Get help with BitMod: report bugs, browse documentation, join community discussions, and find answers to common questions.",
}

const helpChannels = [
  {
    icon: Bug,
    title: "GitHub Issues",
    description: "Report bugs, request features, and track progress on fixes.",
    href: "https://github.com/DeepanjayNandal/bitmod/issues",
    external: true,
    buttonLabel: "Open an Issue",
  },
  {
    icon: Book,
    title: "Documentation",
    description: "Comprehensive guides, API reference, and configuration docs.",
    href: "/docs",
    external: false,
    buttonLabel: "Read the Docs",
  },
  {
    icon: MessageCircle,
    title: "GitHub Discussions",
    description: "Ask questions, share ideas, and connect with other users.",
    href: "https://github.com/DeepanjayNandal/bitmod/discussions",
    external: true,
    buttonLabel: "Join the Discussion",
  },
  {
    icon: Users,
    title: "Contributing",
    description: "Help build BitMod. Read our contributor guide and get started.",
    href: "https://github.com/DeepanjayNandal/bitmod/blob/main/CONTRIBUTING.md",
    external: true,
    buttonLabel: "Start Contributing",
  },
  {
    icon: HelpCircle,
    title: "Contact Us",
    description: "Enterprise sales, vulnerability reports, feature requests, or general questions.",
    href: "/contact",
    external: false,
    buttonLabel: "Get in Touch",
  },
]

const faqs = [
  {
    question: "How do I install BitMod?",
    answer: "Clone the repo and run docker compose up. Requires Python 3.10+ if you run from source instead.",
  },
  {
    question: "Which LLMs are supported?",
    answer: "Any OpenAI-compatible provider, via the universal adapter. Set 3 env vars (URL, key, model) and any OpenAI-compatible API works — Ollama, OpenAI, Anthropic, Groq, Together, vLLM, and more.",
  },
  {
    question: "Do I need a database server?",
    answer: "No, SQLite is the zero-config default. Upgrade to PostgreSQL when you're ready to scale.",
  },
  {
    question: "Is BitMod free?",
    answer: "Yes, 100% open source under Apache 2.0. Self-host with no limits.",
  },
  {
    question: "How does caching work?",
    answer: "9-layer intelligent cache with exact, semantic, composable, and fuzzy matching — reducing LLM calls and costs automatically.",
  },
  {
    question: "Can I use my own models?",
    answer: "Yes, connect Ollama for local models or any OpenAI-compatible endpoint.",
  },
]

const quickLinks = [
  { label: "Docs", href: "/docs" },
  { label: "Guides", href: "/guides" },
  { label: "Security", href: "/security" },
  { label: "Contact", href: "/contact" },
]

export default function SupportPage() {
  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        {/* Hero */}
        <div className="text-center mb-16">
          <Badge variant="accent" className="mb-4">Support</Badge>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              We&apos;re Here to Help
            </span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            BitMod is community-driven and open source. Find answers, report issues,
            and connect with other developers building with BitMod.
          </p>
        </div>

        {/* Get Help */}
        <div className="mb-20">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl mb-2">
            Get Help
          </h2>
          <p className="text-muted-foreground mb-8">
            Choose the channel that fits your needs.
          </p>

          <div className="grid gap-6 sm:grid-cols-2">
            {helpChannels.map((channel) => (
              <Card key={channel.title} className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
                <CardHeader>
                  <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <channel.icon className="h-5 w-5 text-primary" />
                  </div>
                  <CardTitle className="text-lg">{channel.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-6">
                    {channel.description}
                  </p>
                  <Button asChild variant="outline" className="w-full">
                    {channel.external ? (
                      <a href={channel.href} target="_blank" rel="noopener noreferrer">
                        {channel.buttonLabel}
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </a>
                    ) : (
                      <Link href={channel.href}>
                        {channel.buttonLabel}
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Link>
                    )}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Common Questions */}
        <div className="mb-20">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl mb-2">
            Common Questions
          </h2>
          <p className="text-muted-foreground mb-8">
            Quick answers to the questions we hear most.
          </p>

          <div className="grid gap-6 sm:grid-cols-2">
            {faqs.map((faq) => (
              <Card key={faq.question} className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
                <CardHeader>
                  <CardTitle className="flex items-start gap-3 text-base">
                    <HelpCircle className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                    {faq.question}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    {faq.answer}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Quick Links */}
        <div>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl mb-8">
            Quick Links
          </h2>

          <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
            {quickLinks.map((link) => (
              <Card key={link.label} className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg group">
                <Link href={link.href} className="block">
                  <CardContent className="flex items-center justify-between py-6">
                    <span className="font-medium">{link.label}</span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </CardContent>
                </Link>
              </Card>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
