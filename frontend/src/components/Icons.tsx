// Small line icons (no icon library needed).
import type { ReactNode } from 'react'

type P = { size?: number }
const svg = (size: number, children: ReactNode) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
)

export const ShirtIcon = ({ size = 18 }: P) =>
  svg(size, <path d="M8 3 4 5.5 2.5 10l3 1.2V21h13v-9.8l3-1.2L20 5.5 16 3c-.6 1.4-2.1 2.4-4 2.4S8.6 4.4 8 3Z" />)
export const BuildingIcon = ({ size = 18 }: P) =>
  svg(size, <><path d="M4 21V8l8-5 8 5v13" /><path d="M9 21v-6h6v6" /><path d="M3 21h18" /></>)
export const TagIcon = ({ size = 18 }: P) =>
  svg(size, <><path d="M3 12V4h8l9.5 9.5-8 8L3 12Z" /><circle cx="7.5" cy="8.5" r="1.3" /></>)
export const PlayIcon = ({ size = 16 }: P) => svg(size, <path d="M7 4.5v15l12-7.5-12-7.5Z" />)
export const ResetIcon = ({ size = 16 }: P) =>
  svg(size, <><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" /><path d="M3.5 3.5v5h5" /></>)
export const CheckIcon = ({ size = 16 }: P) => svg(size, <path d="m4.5 12.5 5 5 10-11" />)
export const ArrowIcon = ({ size = 14 }: P) => svg(size, <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>)
export const MailIcon = ({ size = 16 }: P) =>
  svg(size, <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 6.5 8.5 6.5 8.5-6.5" /></>)

export function TicketIcon({ type, size = 18 }: { type: string; size?: number }) {
  if (type === 'rent_notice') return <BuildingIcon size={size} />
  if (type === 'price_override') return <TagIcon size={size} />
  return <ShirtIcon size={size} />
}
