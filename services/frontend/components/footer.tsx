import Link from "next/link"
import { GithubIcon } from "@/components/icons"
import { TerminalWordmarkNav } from "@/components/terminal-logo"

const footerLinks = {
  Product: [
    { label: "Architecture", href: "/architecture" },
    { label: "Cache Engine", href: "/cache-engine" },
    { label: "Admin Dashboard", href: "/admin" },
    { label: "Playground", href: "/playground" },
  ],
  Solutions: [
    { label: "Cost Reduction", href: "/solutions/cost-reduction" },
    { label: "Bring Your LLM & DB", href: "/solutions/any-llm-any-db" },
    { label: "Developer Experience", href: "/solutions/developer-experience" },
  ],
  Resources: [
    { label: "Docs", href: "/docs" },
    { label: "Guides", href: "/guides" },
    { label: "Integrations", href: "/integrations" },
    { label: "Security", href: "/security" },
    { label: "Support", href: "/support" },
    { label: "Contact", href: "/contact" },
  ],
}

const socialLinks = [
  {
    label: "GitHub",
    href: "https://github.com/BitModerator/bitmod",
    icon: GithubIcon,
  },
]

export function Footer() {
  return (
    <footer className="border-t border-border/40 bg-background">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        {/* Top section: brand + link columns */}
        <div className="grid grid-cols-2 gap-8 md:grid-cols-6 lg:grid-cols-6">
          {/* Brand */}
          <div className="col-span-2">
            <Link href="/" className="inline-block">
              <TerminalWordmarkNav />
            </Link>
            <p className="mt-4 text-sm text-muted-foreground leading-relaxed">
              Modular AI data infrastructure.
              <br />
              Compute once, serve forever.
            </p>

            {/* Social links */}
            <div className="mt-6 flex items-center gap-4">
              {socialLinks.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={social.label}
                >
                  <social.icon className="h-5 w-5" />
                </a>
              ))}
            </div>
          </div>

          {/* Link columns */}
          {Object.entries(footerLinks).map(([category, links]) => (
            <div key={category}>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-foreground">
                {category}
              </h3>
              <ul className="mt-4 space-y-2.5">
                {links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="mt-12 border-t border-border/40 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
          <p>&copy; {new Date().getFullYear()} BitMod. Apache 2.0 License.</p>
        </div>
      </div>
    </footer>
  )
}
