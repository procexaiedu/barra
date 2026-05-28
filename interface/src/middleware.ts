import { type NextRequest, NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'

export async function middleware(req: NextRequest) {
  if (req.nextUrl.pathname.startsWith('/demo-mapa')) return NextResponse.next() // TEMP verificação MAPA-1
  if (req.nextUrl.pathname.startsWith('/painel-preview')) return NextResponse.next() // TEMP verificação visual Painel
  const res = NextResponse.next()
  const url = req.nextUrl
  const isLogin = url.pathname.startsWith('/login')

  try {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll: () => req.cookies.getAll(),
          setAll: (toSet) => toSet.forEach(({ name, value, options }) =>
            res.cookies.set({ name, value, ...options })
          ),
        },
      }
    )
    const { data: { user } } = await supabase.auth.getUser()
    if (!user && !isLogin) return NextResponse.redirect(new URL('/login', req.url))
    if (user && isLogin) return NextResponse.redirect(new URL('/', req.url))
  } catch {
    if (!isLogin) return NextResponse.redirect(new URL('/login', req.url))
  }
  return res
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|svg)$).*)'],
}
