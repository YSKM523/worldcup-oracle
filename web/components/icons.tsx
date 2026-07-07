import { iso } from "@/lib/wc";

/** Self-hosted SVG country flag, rendered as a uniform rounded chip. */
export function Flag({ name, className = "h-3.5 w-5" }: { name: string; className?: string }) {
  const code = iso(name);
  if (!code)
    // TBD placeholder (e.g. "Group A Winner") — neutral chip keeps layout steady.
    return (
      <span
        aria-hidden
        className={`inline-block rounded-[3px] bg-zinc-800 ring-1 ring-white/10 ${className}`}
      />
    );
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/flags/${code}.svg`}
      alt=""
      aria-hidden
      loading="lazy"
      className={`inline-block rounded-[3px] object-cover ring-1 ring-white/10 ${className}`}
    />
  );
}

type IconProps = { className?: string };

export function CheckIcon({ className = "h-3.5 w-3.5" }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <path
        d="M3.5 8.5l3 3 6-7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function XIcon({ className = "h-3.5 w-3.5" }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function StarIcon({ className = "h-3 w-3" }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden className={className}>
      <path d="M8 1l1.9 4 4.4.6-3.2 3 .8 4.4L8 11l-3.9 2 .8-4.4-3.2-3 4.4-.6z" />
    </svg>
  );
}

/** World Cup trophy mark for the wordmark / favicon. */
export function LogoMark({ className = "h-5 w-5" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={className}>
      {/* handles */}
      <path
        d="M7 5.2H4.3c0 3 1.3 4.3 3.1 4.5M17 5.2h2.7c0 3-1.3 4.3-3.1 4.5"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
      {/* cup bowl */}
      <path d="M6.4 3.6h11.2v4.1a5.6 5.6 0 0 1-11.2 0z" fill="currentColor" />
      {/* globe seam carved out of the cup */}
      <path
        d="M9 5.4c2 1.3 4 1.3 6 0"
        stroke="#08090b"
        strokeWidth="1.1"
        strokeLinecap="round"
      />
      {/* stem + base */}
      <path d="M12 13v3.3" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
      <path d="M9 16.6h6l1 3.4H8z" fill="currentColor" />
    </svg>
  );
}
