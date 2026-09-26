"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import {
  Shield, MessageSquarePlus, Users, Bug,
  HelpCircle, ArrowRight, ExternalLink
} from "lucide-react"
import { GithubIcon } from "@/components/icons"

type FieldName = "name" | "email" | "severity" | "message"

const categories: Array<{
  id: string
  label: string
  icon: typeof HelpCircle
  color: string
  bgActive: string
  heading: string
  description: string
  fields: FieldName[]
  destination: string
  note: string | null
}> = [
  {
    id: "general",
    label: "General",
    icon: HelpCircle,
    color: "text-[#79c0ff]",
    bgActive: "bg-[#79c0ff]/15 border-[#79c0ff]/40 text-[#79c0ff]",
    heading: "General Inquiry",
    description: "Have a question about BitMod? Need help with your deployment? We're here to help.",
    fields: ["name", "email", "message"],
    destination: "github",
    note: "General questions are tracked as GitHub issues, which keeps answers searchable for the next person with the same question.",
  },
  {
    id: "security",
    label: "Vulnerability",
    icon: Shield,
    color: "text-[#ff7b72]",
    bgActive: "bg-[#ff7b72]/15 border-[#ff7b72]/40 text-[#ff7b72]",
    heading: "Report a Vulnerability",
    description: "Found a security issue? Report it responsibly. Do not open a public issue — email us directly.",
    fields: ["name", "email", "severity", "message"],
    destination: "github-security",
    note: "Opens a private GitHub security advisory, not a public issue. This is a personal project with no response-time commitment.",
  },
  {
    id: "feature",
    label: "Feature Request",
    icon: MessageSquarePlus,
    color: "text-[#7ee787]",
    bgActive: "bg-[#7ee787]/15 border-[#7ee787]/40 text-[#7ee787]",
    heading: "Request a Feature",
    description: "Have an idea that would make BitMod better? Tell us what you need.",
    fields: ["name", "email", "message"],
    destination: "github",
    note: "Feature requests are tracked as GitHub issues. We'll create one on your behalf or you can open one directly.",
  },
  {
    id: "bug",
    label: "Bug Report",
    icon: Bug,
    color: "text-[#ffa657]",
    bgActive: "bg-[#ffa657]/15 border-[#ffa657]/40 text-[#ffa657]",
    heading: "Report a Bug",
    description: "Something broken? Help us fix it by providing as much detail as possible.",
    fields: ["name", "email", "message"],
    destination: "github",
    note: "Include your BitMod version, OS, and steps to reproduce. Bug reports are tracked on GitHub.",
  },
  {
    id: "contribute",
    label: "Contribute",
    icon: Users,
    color: "text-primary",
    bgActive: "bg-primary/15 border-primary/40 text-primary",
    heading: "Contribute to BitMod",
    description: "Want to contribute code, documentation, or adapters? We'd love your help.",
    fields: [],
    destination: "github",
    note: null,
  },
]

const severityOptions = ["Critical", "High", "Medium", "Low", "Informational"]

export default function ContactPage() {
  const [activeCategory, setActiveCategory] = useState("general")
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    severity: "",
    message: "",
  })

  const category = categories.find((c) => c.id === activeCategory)!
  const Icon = category.icon

  // Every category opens a GitHub URL through an anchor, so there is no submit
  // path left. preventDefault stops Enter in a text field triggering a native
  // GET submit and reloading the page.
  const handleSubmit = (e: React.FormEvent) => e.preventDefault()

  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      {/* Hero */}
      <section className="mx-auto max-w-7xl px-4 pt-20 pb-12 sm:px-6 sm:pt-28 sm:pb-16 lg:px-8">
        <div className="text-center">
          <Badge variant="accent" className="mb-6 px-4 py-1.5 text-sm">
            Contact
          </Badge>

          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Get in Touch
            </span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Security reports, feature requests, bug reports, or just a question.
            Pick a category and it opens a prefilled GitHub page.
          </p>
        </div>
      </section>

      {/* Category Slider + Form */}
      <section className="mx-auto max-w-3xl px-4 pb-24 sm:px-6 lg:px-8">
        {/* Category slider */}
        <div className="flex flex-wrap justify-center gap-2 mb-10">
          {categories.map((cat) => {
            const CatIcon = cat.icon
            const isActive = activeCategory === cat.id
            return (
              <button
                key={cat.id}
                onClick={() => {
                  setActiveCategory(cat.id)
                  setFormData({ name: "", email: "", severity: "", message: "" })
                }}
                className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium border transition-all duration-200 cursor-pointer ${
                  isActive
                    ? cat.bgActive
                    : "bg-muted/10 border-border/40 text-muted-foreground hover:bg-muted/20 hover:text-foreground"
                }`}
              >
                <CatIcon className="h-4 w-4" />
                {cat.label}
              </button>
            )
          })}
        </div>

        {/* Active category content */}
        <Card className="border-border/40 bg-card/50 overflow-hidden">
          <CardContent className="p-6 sm:p-8">
            {/* Header */}
            <div className="flex items-start gap-4 mb-6">
              <div className={`flex items-center justify-center h-12 w-12 rounded-lg bg-muted/20 border border-border/20 shrink-0`}>
                <Icon className={`h-6 w-6 ${category.color}`} />
              </div>
              <div>
                <h2 className="text-xl font-bold">{category.heading}</h2>
                <p className="text-sm text-muted-foreground mt-1">{category.description}</p>
              </div>
            </div>

            {/* Contribute — special case (no form, just links) */}
            {category.id === "contribute" ? (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  {[
                    {
                      title: "Good First Issues",
                      desc: "Beginner-friendly issues to pick up.",
                      href: "https://github.com/DeepanjayNandal/bitmod/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22",
                      internal: false,
                    },
                    {
                      title: "Open Issues",
                      desc: "Browse all open issues on GitHub.",
                      href: "https://github.com/DeepanjayNandal/bitmod/issues",
                      internal: false,
                    },
                  ].map((link) => (
                    <Link
                      key={link.title}
                      href={link.href}
                      target={link.internal ? undefined : "_blank"}
                      rel={link.internal ? undefined : "noopener noreferrer"}
                      className="group rounded-lg border border-border/40 bg-muted/5 hover:bg-muted/10 hover:border-border/80 p-4 transition-all"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">{link.title}</span>
                        {link.internal ? (
                          <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                        ) : (
                          <ExternalLink className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">{link.desc}</p>
                    </Link>
                  ))}
                </div>
              </div>
            ) : (
              /* Form */
              <form onSubmit={handleSubmit} className="space-y-4">
                {/* Name + Email row */}
                <div className="grid gap-4 sm:grid-cols-2">
                  {category.fields.includes("name") && (
                    <div>
                      <label htmlFor="name" className="block text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
                        Name
                      </label>
                      <input
                        id="name"
                        type="text"
                        required
                        value={formData.name}
                        onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                        className="w-full rounded-lg border border-border/40 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                        placeholder="Your name"
                      />
                    </div>
                  )}
                  {category.fields.includes("email") && (
                    <div>
                      <label htmlFor="email" className="block text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
                        Email
                      </label>
                      <input
                        id="email"
                        type="email"
                        required
                        value={formData.email}
                        onChange={(e) => setFormData((prev) => ({ ...prev, email: e.target.value }))}
                        className="w-full rounded-lg border border-border/40 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                        placeholder="you@company.com"
                      />
                    </div>
                  )}
                </div>

                {/* Severity selector (security only) */}
                {category.fields.includes("severity") && (
                  <div>
                    <label htmlFor="severity" className="block text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
                      Severity
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {severityOptions.map((sev) => (
                        <button
                          key={sev}
                          type="button"
                          onClick={() => setFormData((prev) => ({ ...prev, severity: sev }))}
                          className={`rounded-full px-3 py-1.5 text-xs font-medium border transition-colors cursor-pointer ${
                            formData.severity === sev
                              ? sev === "Critical" || sev === "High"
                                ? "bg-red-500/15 border-red-500/40 text-red-400"
                                : sev === "Medium"
                                ? "bg-yellow-500/15 border-yellow-500/40 text-yellow-400"
                                : "bg-muted/15 border-border/60 text-foreground"
                              : "bg-muted/10 border-border/40 text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          {sev}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Message */}
                {category.fields.includes("message") && (
                  <div>
                    <label htmlFor="message" className="block text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
                      {category.id === "security" ? "Description" : category.id === "bug" ? "Steps to Reproduce" : category.id === "feature" ? "What would you like to see?" : "Message"}
                    </label>
                    <textarea
                      id="message"
                      required
                      rows={5}
                      value={formData.message}
                      onChange={(e) => setFormData((prev) => ({ ...prev, message: e.target.value }))}
                      className="w-full rounded-lg border border-border/40 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                      placeholder={
                        category.id === "security"
                          ? "Describe the vulnerability, affected components, and potential impact..."
                          : category.id === "bug"
                          ? "1. What did you do?\n2. What did you expect?\n3. What happened instead?\n\nBitMod version: \nOS: "
                          : category.id === "feature"
                          ? "Describe the feature and how it would help your workflow..."
                          : "How can we help?"
                      }
                    />
                  </div>
                )}

                {/* Note */}
                {category.note && (
                  <p className="text-xs text-muted-foreground">
                    {category.note}
                  </p>
                )}

                {/* Submit */}
                <div className="flex items-center gap-3 pt-2">
                  {category.destination === "github-security" ? (
                    <Button type="button" asChild>
                      <a
                        href="https://github.com/DeepanjayNandal/bitmod/security/advisories/new"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <GithubIcon className="mr-2 h-4 w-4" />
                        Open a private advisory
                        <ExternalLink className="ml-2 h-3.5 w-3.5" />
                      </a>
                    </Button>
                  ) : (
                    <Button type="button" asChild>
                      <a
                        href={`https://github.com/DeepanjayNandal/bitmod/issues/new?labels=${category.id === "bug" ? "bug" : category.id === "feature" ? "enhancement" : "question"}&title=${encodeURIComponent(formData.message.split("\n")[0] || "")}&body=${encodeURIComponent(`**From:** ${formData.name} (${formData.email})\n\n${formData.message}`)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <GithubIcon className="mr-2 h-4 w-4" />
                        Open on GitHub
                        <ExternalLink className="ml-2 h-3.5 w-3.5" />
                      </a>
                    </Button>
                  )}
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
