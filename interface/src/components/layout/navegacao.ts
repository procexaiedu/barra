import {
  LayoutDashboard,
  MessagesSquare,
  Calendar,
  Receipt,
  ListChecks,
  Users,
  IdCard,
  Headset,
  KeyRound,
  ChartLine,
  Wallet,
  Bot,
  type LucideIcon,
} from "lucide-react"

export type ItemNavegacao = {
  href: string
  label: string
  icon: LucideIcon
}

export type GrupoNavegacao = {
  label: string
  items: ItemNavegacao[]
}

// Fonte única da navegação do painel. Consumida pela Sidebar (desktop) e pela
// BottomNav + MobileDrawer (mobile).
export const grupos: GrupoNavegacao[] = [
  {
    label: "OPERAÇÃO",
    items: [
      { href: "/", label: "Painel", icon: LayoutDashboard },
      { href: "/atendimentos", label: "Atendimentos", icon: MessagesSquare },
      { href: "/agenda", label: "Agenda", icon: Calendar },
      { href: "/pix", label: "Pix", icon: Receipt },
      { href: "/tarefas", label: "Tarefas", icon: ListChecks },
    ],
  },
  {
    label: "CADASTROS",
    items: [
      { href: "/clientes", label: "Clientes", icon: Users },
      { href: "/modelos", label: "Modelos", icon: IdCard },
      // Ao lado de Modelos por pedido explícito (ADR-0048): é onde o percentual de comissão do
      // telefonista é alterado. "Telefonista" é o Vendedor no vocabulário do grupo financeiro.
      { href: "/telefonistas", label: "Telefonistas", icon: Headset },
      // O registro de "de quem e esta chave" (ADR-0049): e cadastro, e e onde o dono classifica
      // a chave que apareceu num comprovante. Nao e o `chave_pix` da ficha da modelo — aquele e
      // destino de REPASSE, e somar os dois sentidos faz o razao dobrar (ADR-0049 §3).
      { href: "/chaves-pix", label: "Chaves Pix", icon: KeyRound },
    ],
  },
  {
    label: "ANÁLISE",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: ChartLine },
      { href: "/financeiro", label: "Financeiro", icon: Wallet },
      { href: "/avaliacao", label: "Avaliação", icon: Bot },
    ],
  },
]

const todosItens = grupos.flatMap((grupo) => grupo.items)

const hrefsPrincipais = ["/", "/atendimentos", "/agenda", "/pix"] as const

// Destinos da barra inferior em mobile (os 4 de uso operacional). O 5º slot da
// barra é o botão "Mais", que abre o MobileDrawer com o restante.
export const destinosPrincipais: ItemNavegacao[] = hrefsPrincipais
  .map((href) => todosItens.find((item) => item.href === href))
  .filter((item): item is ItemNavegacao => item !== undefined)

// Destinos restantes, exibidos no MobileDrawer.
export const destinosSecundarios: ItemNavegacao[] = todosItens.filter(
  (item) => !hrefsPrincipais.includes(item.href as (typeof hrefsPrincipais)[number])
)

// Lógica de item ativo compartilhada (Sidebar, BottomNav, MobileDrawer).
export function itemAtivo(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/"
  return pathname.startsWith(href)
}
