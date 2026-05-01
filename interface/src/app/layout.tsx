import type { Metadata } from "next"
import { Inter, JetBrains_Mono, Cormorant_Garamond } from "next/font/google"
import { Toaster } from "sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import "./globals.css"

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
})

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
})

const cormorant = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["500"],
  display: "swap",
})

export const metadata: Metadata = {
  title: "Barra Vips Painel",
  description: "Central inteligente de atendimento Barra Vips.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="pt-BR"
      className={`dark ${inter.variable} ${jetbrainsMono.variable} ${cormorant.variable}`}
    >
      <body className="min-h-screen bg-background text-foreground font-sans antialiased">
        <TooltipProvider>
          {children}
        </TooltipProvider>
        <Toaster position="bottom-right" theme="dark" richColors closeButton />
      </body>
    </html>
  )
}
