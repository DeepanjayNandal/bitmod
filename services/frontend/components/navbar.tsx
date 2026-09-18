"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Menu, X } from "lucide-react"
import { GithubIcon } from "@/components/icons"
import { useState, useEffect } from "react"
import dynamic from "next/dynamic"
import { TerminalWordmarkNav } from "@/components/terminal-logo"

const AnimatedNav = dynamic(
  () => import("@/components/animated-wordmark").then(mod => ({ default: mod.AnimatedWordmarkNav })),
  { ssr: false, loading: () => <TerminalWordmarkNav /> }
)

function NavLogo() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  return mounted ? <AnimatedNav /> : <TerminalWordmarkNav />
}

const navLinks = [
  { href: "/#features", label: "Features" },
  { href: "/architecture", label: "Architecture" },
  { href: "/docs", label: "Docs" },
  { href: "/guides", label: "Guides" },
  { href: "/integrations", label: "Integrations" },
  { href: "/playground", label: "Playground" },
  { href: "/security", label: "Security" },
  { href: "/admin", label: "Admin" },
]

export function Navbar() {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => { setMobileOpen(false) }, [pathname])

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Logo */}
        <Link href="/" className="flex items-center">
          <NavLogo />
        </Link>

        {/* Desktop Nav */}
        <nav className="hidden md:flex items-center gap-1">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "px-3 py-2 text-sm font-medium rounded-lg transition-colors hover:text-foreground",
                pathname === link.href || (link.href.includes('#') && pathname === link.href.split('#')[0]) ? "text-foreground" : "text-muted-foreground"
              )}
            >
              {link.label}
            </Link>
          ))}
          <a
            href="https://github.com/BitModerator/bitmod"
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
            aria-label="GitHub repository"
          >
            <GithubIcon className="h-5 w-5" />
          </a>
        </nav>

        {/* CTA */}
        <div className="hidden md:flex items-center gap-3">
          <Button variant="accent" size="sm" asChild>
            <Link href="/docs">Get Started</Link>
          </Button>
        </div>

        {/* Mobile Menu Toggle */}
        <button
          className="md:hidden p-2 text-muted-foreground hover:text-foreground"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {/* Mobile Menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-border/40 bg-background/95 backdrop-blur-xl">
          <div className="flex flex-col gap-1 px-4 py-4">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg"
                onClick={() => setMobileOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <Button variant="accent" size="sm" className="mt-2" asChild>
              <Link href="/docs">Get Started</Link>
            </Button>
          </div>
        </div>
      )}
    </header>
  )
}
