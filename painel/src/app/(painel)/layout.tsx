import Link from "next/link";
import type { ReactNode } from "react";

const links = [
  { href: "/painel", label: "Painel" },
  { href: "/painel/atendimentos", label: "Atendimentos" },
  { href: "/painel/agenda", label: "Agenda" },
  { href: "/painel/crm", label: "CRM" },
  { href: "/painel/modelos", label: "Modelos" },
  { href: "/painel/pix", label: "Pix" },
  { href: "/painel/dashboard", label: "Dashboard" },
];

export default function PainelLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen grid-cols-[220px_1fr]">
      <aside className="border-r p-4">
        <div className="mb-6 font-semibold">Barra Vips</div>
        <nav className="flex flex-col gap-1">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="rounded px-2 py-1 text-sm hover:bg-muted"
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="p-6">{children}</main>
    </div>
  );
}
