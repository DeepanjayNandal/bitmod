import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import Script from "next/script"
import { ThemeProvider } from "@/components/theme-provider"
import { Navbar } from "@/components/navbar"
import { Footer } from "@/components/footer"
import { ScrollToTop } from "@/components/scroll-to-top"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "BitMod — Modular AI Data Infrastructure",
  description: "Compute once, serve forever. Open-source intelligent caching for LLM applications. 200+ LLM providers, 4 databases, zero lock-in. Run it with docker compose up.",
  icons: { icon: "/favicon.svg" },
  metadataBase: new URL("https://bitmod.io"),
  openGraph: {
    title: "BitMod — Compute Once, Serve Forever",
    description: "Open-source modular AI data infrastructure with intelligent caching. Connect any LLM, any database, any vector store.",
    url: "https://bitmod.io",
    siteName: "BitMod",
    images: [{ url: "/logo-full.png", width: 630, height: 630, alt: "BitMod" }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "BitMod — Compute Once, Serve Forever",
    description: "Open-source modular AI data infrastructure with intelligent caching.",
    images: ["/logo-full.png"],
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md">
          Skip to content
        </a>
        <Script id="scroll-fix" strategy="beforeInteractive">{`if("scrollRestoration"in history)history.scrollRestoration="manual";window.scrollTo(0,0);`}</Script>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <div className="flex min-h-screen flex-col">
            <ScrollToTop />
            <Navbar />
            <main id="main-content" className="flex-1">{children}</main>
            <Footer />
          </div>
        </ThemeProvider>
      </body>
    </html>
  )
}
