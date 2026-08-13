import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  images: {
    // Mídia das modelos: host e bucket únicos do MinIO (MINIO_ENDPOINT do stack). `search` fica
    // FORA de propósito — declará-lo exigiria query exata, e a assinatura V4 (`X-Amz-Date`,
    // `X-Amz-Signature`) muda a cada request; sem ele, qualquer query passa. O `pathname` estreito
    // é o que impede o otimizador de virar proxy de imagem aberto (`/_next/image` não passa pelo
    // gate de auth do proxy.ts).
    remotePatterns: [
      {
        protocol: "https",
        hostname: "minioback.procexai.tech",
        port: "",
        pathname: "/barra-media/**",
      },
    ],
    // A assinatura expira em 900s (api core/storage.py), então a mesma URL nunca reaparece depois
    // disso: guardar o otimizado por mais tempo (default 4h) só acumula entrada morta em disco.
    minimumCacheTTL: 900,
    // Sem teto, o default é metade do disco livre — muito para um cache que é quase todo miss.
    maximumDiskCacheSize: 200_000_000,
  },
};

export default nextConfig;
