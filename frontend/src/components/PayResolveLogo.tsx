interface PayResolveLogoProps {
  compact?: boolean;
  inverse?: boolean;
  subtitle?: string;
}

export default function PayResolveLogo({ compact = false, inverse = false, subtitle = 'Recovery intelligence' }: PayResolveLogoProps) {
  const ink = inverse ? '#ffffff' : '#10233f';
  const accent = inverse ? '#ffffff' : '#2563d8';

  return (
    <div className="flex items-center gap-2.5" aria-label="PayResolve">
      <svg className={compact ? 'h-8 w-8' : 'h-10 w-10'} viewBox="0 0 40 40" fill="none" role="img" aria-label="PayResolve mark">
        <rect width="40" height="40" rx="11" fill={inverse ? 'rgba(255,255,255,0.16)' : '#eaf2ff'} />
        <path d="M10 20h14" stroke={accent} strokeWidth="3" strokeLinecap="round" />
        <path d="m19 13 7 7-7 7" stroke={accent} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 12v16" stroke={ink} strokeWidth="2" strokeLinecap="round" opacity=".45" />
      </svg>
      {!compact && <span><span className="block text-[17px] font-extrabold tracking-[-0.04em]" style={{ color: ink }}>PayResolve</span><span className="block text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: inverse ? 'rgba(255,255,255,.7)' : '#6c7d93' }}>{subtitle}</span></span>}
    </div>
  );
}
