"use client";

import dynamic from "next/dynamic";

export const BoundingBoxEditor = dynamic(
  () => import("./BoundingBoxCanvasInner"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[460px] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
        Carregando Editor Visual Konva (Client-Side)...
      </div>
    ),
  }
);
