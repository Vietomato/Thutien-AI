// CashPilot logo: a "C" (cash) whose opening holds a forward arrow (the pilot, steering cash flow ahead).
// tone="dark" is for dark backgrounds (white tile), tone="light" for light ones (navy tile).
export function LogoMark({ size = 32, tone = "light" }: { size?: number; tone?: "light" | "dark" }) {
  const tile = tone === "light" ? "#0E0F0C" : "#8ED1FF";
  const arc = tone === "light" ? "#8ED1FF" : "#0E0F0C";
  const arrow = tone === "light" ? "#FFFFFF" : "#0E0F0C";
  return <svg className="logo-mark" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
    <rect width="40" height="40" rx="12" fill={tile} />
    <path d="M26.9 14.2A9 9 0 1 0 26.9 25.8" fill="none" stroke={arc} strokeWidth="4.6" strokeLinecap="round" />
    <path d="M29.4 16.4L35.4 20L29.4 23.6Z" fill={arrow} stroke={arrow} strokeWidth="1.6" strokeLinejoin="round" />
  </svg>;
}

export function Logo({ tone = "light", size = 32 }: { tone?: "light" | "dark"; size?: number }) {
  return <span className={`logo logo-${tone}`} aria-label="CashPilot">
    <LogoMark size={size} tone={tone} />
    <span className="logo-word" style={{ fontSize: Math.round(size * 0.56) }}>Cash<b>Pilot</b></span>
  </span>;
}
