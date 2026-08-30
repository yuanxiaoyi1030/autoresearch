// Purpose: Defines the Chinese local research-console document shell and metadata.
import type {Metadata} from "next";
import type {ReactNode} from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "AutoResearch v0.2 · 科研控制台",
  description: "仅在本机运行、证据可追溯的完整科研工作台。",
  robots: {index: false, follow: false}
};

export default function RootLayout({children}: {children: ReactNode}) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
