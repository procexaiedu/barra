"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { loginAction } from "./actions"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card"
import { supabase } from "@/lib/supabase"
import { toast } from "sonner"
import { LogIn, Loader2 } from "lucide-react"

export default function Login() {
  const [isLoading, setIsLoading] = useState(false)
  const router = useRouter()

  const handleLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setIsLoading(true)

    const formData = new FormData(e.currentTarget)
    const email = String(formData.get("email") ?? "")
    const password = String(formData.get("password") ?? "")
    const result = await loginAction(formData)

    if (result?.error) {
      toast.error("Falha na autenticação", {
        description: result.error,
      })
      setIsLoading(false)
      return
    }

    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) {
      toast.error("Falha na autenticação", {
        description: error.message,
      })
      setIsLoading(false)
      return
    }

    toast.success("Bem-vindo ao Elite Baby!")
    router.push("/")
    router.refresh()
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      {/* Halo de ouro — o "momento de entrada" do produto de luxo, contido. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background:radial-gradient(48%_38%_at_50%_26%,color-mix(in_oklab,var(--gold-500)_14%,transparent),transparent_68%)]"
      />
      <div className="relative flex w-full max-w-[400px] flex-col gap-8">
        <div className="flex flex-col items-center gap-2.5 text-center">
          <span className="h-1 w-10 rounded-full bg-gold-500" aria-hidden />
          <h1 className="text-aurum font-serif text-[42px] font-medium leading-none tracking-[-0.01em]">
            Elite Baby
          </h1>
          <p className="text-[13px] text-text-muted">Acesso à central inteligente.</p>
        </div>

        <Card className="rise-in">
          <CardHeader>
            <CardTitle>Entrar</CardTitle>
            <CardDescription>
              Insira suas credenciais corporativas abaixo
            </CardDescription>
          </CardHeader>
          <form onSubmit={handleLogin}>
            <CardContent className="flex flex-col gap-5">
              <div className="space-y-2.5">
                <Label htmlFor="email">E-mail</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="seu@email.com"
                  autoComplete="email"
                  required
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2.5">
                <Label htmlFor="password">Senha</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  disabled={isLoading}
                />
              </div>
            </CardContent>
            <CardFooter>
              <Button type="submit" variant="primary" size="lg" className="w-full" disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 size={16} strokeWidth={1.5} className="animate-spin" />
                    Autenticando...
                  </>
                ) : (
                  <>
                    <LogIn size={16} strokeWidth={1.5} />
                    Acessar painel
                  </>
                )}
              </Button>
            </CardFooter>
          </form>
        </Card>
      </div>
    </main>
  )
}
