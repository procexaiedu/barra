import Link from "next/link";

export default function Pagina() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="space-y-4 text-center">
        <h1 className="text-3xl font-semibold">Barra Vips</h1>
        <p className="text-muted-foreground">Central inteligente de atendimento.</p>
        <Link href="/login" className="underline">
          Entrar
        </Link>
      </div>
    </main>
  );
}
