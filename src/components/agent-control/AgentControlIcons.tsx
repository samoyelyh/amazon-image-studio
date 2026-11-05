import type { SVGProps } from 'react'

export function SparklesIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="m12 3-1.2 3.2a5.8 5.8 0 0 1-3.5 3.5L4 11l3.3 1.2a5.8 5.8 0 0 1 3.5 3.5L12 19l1.2-3.3a5.8 5.8 0 0 1 3.5-3.5L20 11l-3.3-1.3a5.8 5.8 0 0 1-3.5-3.5L12 3Z" />
    <path d="m5 3-.4 1.1a2 2 0 0 1-1.2 1.2L2 6l1.4.6a2 2 0 0 1 1.2 1.2L5 9l.4-1.2a2 2 0 0 1 1.2-1.2L8 6l-1.4-.7a2 2 0 0 1-1.2-1.2L5 3Z" />
  </svg>
}

export function ArrowUpIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M12 19V5m-6 6 6-6 6 6" />
  </svg>
}

export function PaperclipIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.6-9.6a4 4 0 0 1 5.7 5.7l-9.6 9.6a2 2 0 0 1-2.8-2.8l8.9-8.9" />
  </svg>
}

export function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" />
  </svg>
}

export function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M20 15a3 3 0 0 1-3 3H9l-5 3v-6a3 3 0 0 1-1-2.2V7a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3v8Z" />
  </svg>
}

export function StopIcon(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
    <circle cx="12" cy="12" r="9" /><rect x="9" y="9" width="6" height="6" rx="1" fill="currentColor" stroke="none" />
  </svg>
}
