"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import {
  Shield, Building2, MessageSquarePlus, Users, Bug,
  HelpCircle, ArrowRight, Send, CheckCircle, ExternalLink
} from "lucide-react"
import { GithubIcon } from "@/components/icons"

type FieldName = "name" | "email" | "company" | "severity" | "message"

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
    destination: "support@bitmod.io",
    note: "We typically respond within 24 hours.",
  },
  {
    id: "enterprise",
    label: "Enterprise",
    icon: Building2,
    color: "text-[#d2a8ff]",
    bgActive: "bg-[#d2a8ff]/15 border-[#d2a8ff]/40 text-[#d2a8ff]",
    heading: "Enterprise Sales",
    description: "Custom compliance bundles, dedicated security reviews, white-label deployments, and priority support SLAs.",
    fields: ["name", "email", "company", "message"],
    destination: "enterprise@bitmod.io",
    note: "For custom authentication integrations, compliance requirements, and architecture consulting.",
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
    destination: "security@bitmod.io",
    note: "We respond within 48 hours and coordinate disclosure privately. See our SECURITY.md for full policy.",
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
  const [submitted, setSubmitted] = useState(false)
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    company: "",
    severity: "",
    message: "",
  })

  const category = categories.find((c) => c.id === activeCategory)!
  const Icon = category.icon

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (category.destination === "github") {
      return
    }

    // Build mailto link with form data
    const subject = encodeURIComponent(
      category.id === "security"
        ? `[Vulnerability Report] ${formData.severity ? `[${formData.severity}] ` : ""}BitMod Security`
        : category.id === "enterprise"
        ? `[Enterprise] ${formData.company || "Inquiry"}`
        : category.id === "feature"
        ? `[Feature Request] BitMod`
        : `[${category.label}] BitMod`
    )
    const body = encodeURIComponent(
      `Name: ${formData.name}\nEmail: ${formData.email}${formData.company ? `\nCompany: ${formData.company}` : ""}${formData.severity ? `\nSeverity: ${formData.severity}` : ""}\n\n${formData.message}`
    )
    window.open(`mailto:${category.destination}?subject=${subject}&body=${body}`, "_self")
    setSubmitted(true)
    setTimeout(() => setSubmitted(false), 3000)
  }

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
            Enterprise sales, security reports, feature requests, bug reports, or just a question.
            Pick a category and we&apos;ll route it to the right team.
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
                  setSubmitted(false)
                  setFormData({ name: "", email: "", company: "", severity: "", message: "" })
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
                      href: "https://github.com/BitModerator/bitmod/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22",
                      internal: false,
                    },
                    {
                      title: "Open Issues",
                      desc: "Browse all open issues on GitHub.",
                      href: "https://github.com/BitModerator/bitmod/issues",
                      internal: false,
                    },
                    {
                      title: "Security Policy",
                      desc: "Responsible disclosure process.",
                      href: "https://github.com/BitModerator/bitmod/blob/main/SECURITY.md",
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

                {/* Company field (enterprise only) */}
                {category.fields.includes("company") && (
                  <div>
                    <label htmlFor="company" className="block text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
                      Company
                    </label>
                    <input
                      id="company"
                      type="text"
                      value={formData.company}
                      onChange={(e) => setFormData((prev) => ({ ...prev, company: e.target.value }))}
                      className="w-full rounded-lg border border-border/40 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                      placeholder="Your organization"
                    />
                  </div>
                )}

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
                          : category.id === "enterprise"
                          ? "Tell us about your use case, scale, and requirements..."
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
                  {category.destination === "github" ? (
                    <Button type="button" asChild>
                      <a
                        href={`https://github.com/BitModerator/bitmod/issues/new?labels=${category.id === "bug" ? "bug" : "enhancement"}&title=${encodeURIComponent(formData.message.split("\n")[0] || "")}&body=${encodeURIComponent(`**From:** ${formData.name} (${formData.email})\n\n${formData.message}`)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <GithubIcon className="mr-2 h-4 w-4" />
                        Open on GitHub
                        <ExternalLink className="ml-2 h-3.5 w-3.5" />
                      </a>
                    </Button>
                  ) : submitted ? (
                    <Button disabled className="bg-green-500/15 text-green-400 border-green-500/30">
                      <CheckCircle className="mr-2 h-4 w-4" />
                      Opening mail client...
                    </Button>
                  ) : (
                    <Button type="submit">
                      <Send className="mr-2 h-4 w-4" />
                      Send to {category.destination}
                    </Button>
                  )}
                </div>
              </form>
            )}
          </CardContent>
        </Card>

        {/* Direct email fallback */}
        <div className="mt-6 text-center text-sm text-muted-foreground">
          <p>
            Prefer email? Reach us directly at{" "}
            <a href="mailto:support@bitmod.io" className="text-primary hover:underline">support@bitmod.io</a>,{" "}
            <a href="mailto:enterprise@bitmod.io" className="text-primary hover:underline">enterprise@bitmod.io</a>, or{" "}
            <a href="mailto:security@bitmod.io" className="text-primary hover:underline">security@bitmod.io</a>
          </p>
        </div>
      </section>
    </div>
  )
}
