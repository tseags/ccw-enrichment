import "@/app/globals.css";
import Link from "next/link";
import type { ReactNode } from "react";

const nav = [
  { href: "/directory", label: "Directory" },
  { href: "/import", label: "Import" },
  { href: "/queue/enrichment", label: "Enrichment Queue" },
  { href: "/queue/review", label: "Review Queue" },
  { href: "/vendors", label: "Vendors" },
  { href: "/exports", label: "Exports" }
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b bg-white">
            <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
              <Link href="/directory" className="mr-4 text-lg font-semibold hover:underline">
                CCW Enrichment Ops
              </Link>
              <nav className="flex gap-3 text-sm">
                {nav.map((item) => (
                  <Link key={item.href} href={item.href} className="rounded px-2 py-1 hover:bg-slate-100">
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
