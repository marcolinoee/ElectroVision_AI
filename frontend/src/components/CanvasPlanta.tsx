"use client";

import dynamic from "next/dynamic";

export const CanvasPlanta = dynamic(() => import("./CanvasPlantaInner"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
      Carregando Calibrador Espacial de Planta Konva...
    </div>
  ),
});
