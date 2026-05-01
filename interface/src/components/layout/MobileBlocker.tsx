"use client"

export function MobileBlocker() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8 lg:hidden">
      <div className="text-center">
        <h1 className="mb-4 font-serif text-[40px] font-medium leading-[48px] text-gold-500">
          Barra Vips
        </h1>
        <p className="text-sm text-text-primary">
          O painel está disponível apenas em desktop.
          <br />
          Use o grupo de Coordenação por modelo no celular.
        </p>
      </div>
    </div>
  )
}
