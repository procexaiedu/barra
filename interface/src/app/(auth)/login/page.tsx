"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { loginAction } from "./actions"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card"
import { toast } from "sonner"
import { LogIn, Loader2, Sparkles } from "lucide-react"

export default function Login() {
  const [isLoading, setIsLoading] = useState(false)
  const router = useRouter()

  const handleLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setIsLoading(true)

    const formData = new FormData(e.currentTarget)
    const result = await loginAction(formData)

    if (result?.error) {
      toast.error("Falha na autenticação", {
        description: result.error,
      })
      setIsLoading(false)
      return
    }

    toast.success("Bem-vindo ao Barra Vips!")
    router.push("/")
    router.refresh()
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background">
      {/* Dynamic Background Effects */}
      <div className="absolute inset-0 z-0">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-primary/20 via-background to-background opacity-50 mix-blend-screen" />
        <div className="absolute -top-[40%] -left-[20%] h-[80%] w-[60%] rounded-full bg-primary/10 blur-[120px] animate-pulse duration-10000" />
        <div className="absolute -bottom-[40%] -right-[20%] h-[80%] w-[60%] rounded-full bg-primary/5 blur-[120px]" />
      </div>

      {/* Login Card with Glassmorphism */}
      <div className="z-10 w-full max-w-[420px] p-4 animate-in fade-in slide-in-from-bottom-8 duration-700">
        <div className="mb-8 flex flex-col items-center justify-center space-y-2 text-center animate-in fade-in slide-in-from-top-4 duration-1000 delay-200">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20 mb-2">
            <Sparkles className="h-6 w-6 text-primary" />
          </div>
          <h1 className="font-heading text-4xl font-bold tracking-tight text-foreground">
            Barra Vips
          </h1>
          <p className="text-muted-foreground">
            Acesso à central inteligente
          </p>
        </div>

        <Card className="border-border/50 bg-background/60 backdrop-blur-xl shadow-2xl ring-1 ring-foreground/5 relative overflow-hidden group">
          {/* Subtle hover effect on card border */}
          <div className="absolute inset-0 z-0 bg-gradient-to-br from-primary/5 via-transparent to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
          
          <CardHeader className="relative z-10 pb-6 pt-8">
            <CardTitle className="text-xl">Entrar</CardTitle>
            <CardDescription>
              Insira suas credenciais corporativas abaixo
            </CardDescription>
          </CardHeader>
          <form onSubmit={handleLogin} className="relative z-10">
            <CardContent className="space-y-5">
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
                  className="bg-background/50 transition-colors focus:bg-background"
                />
              </div>
              <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Senha</Label>
                </div>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  disabled={isLoading}
                  className="bg-background/50 transition-colors focus:bg-background"
                />
              </div>
            </CardContent>
            <CardFooter className="pb-8 pt-4">
              <Button 
                type="submit" 
                className="w-full h-11 relative overflow-hidden transition-all hover:shadow-[0_0_20px_-5px_hsl(var(--primary))]" 
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Autenticando...
                  </>
                ) : (
                  <>
                    <LogIn className="mr-2 h-4 w-4" />
                    Acessar Painel
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
