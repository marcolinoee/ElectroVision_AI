"use client";

import dynamic from "next/dynamic";

export const CanvasUnifilar = dynamic(() => import("./CanvasUnifilarInner"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[440px] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
      Carregando Diagrama Unifilar Konva...
    </div>
  ),
});
