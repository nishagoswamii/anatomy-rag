import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AnatomyRAG: cited answers from an anatomy textbook",
  description:
    "A retrieval-augmented chatbot that answers only from OpenStax Anatomy and Physiology 2e and cites the exact passage for every claim.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: browser extensions often add attributes to <html>.
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <Link href="/" className="font-semibold tracking-tight">
            Anatomy<span className="text-teal-700 dark:text-teal-400">RAG</span>
          </Link>
          <nav className="flex gap-4 text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/about" className="hover:text-zinc-900 dark:hover:text-zinc-100">
              How it works
            </Link>
          </nav>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
        <footer className="border-t border-zinc-200 px-4 py-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
          Content from{" "}
          <a
            href="https://openstax.org/details/books/anatomy-and-physiology-2e"
            className="underline"
            target="_blank"
            rel="noreferrer"
          >
            Anatomy and Physiology 2e
          </a>{" "}
          by OpenStax, licensed CC BY-NC-SA 4.0. Access for free at openstax.org. Not affiliated with
          OpenStax.
        </footer>
      </body>
    </html>
  );
}
