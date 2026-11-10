import type { CongestionTier, TrendPoint } from "@/lib/types";

const TIER_STROKE: Record<CongestionTier, string> = {
  Low: "#4ADE80",
  Medium: "#FBBF24",
  High: "#FB923C",
  Critical: "#F87171",
};

interface SparklineProps {
  points: TrendPoint[];
  width?: number;
  height?: number;
  className?: string;
  label: string;
}

/** Ships-waiting over time, coloured by the latest congestion tier. Always drawn left-to-right (time axis). */
export function Sparkline({ points, width = 120, height = 32, className, label }: SparklineProps) {
  const last = points[points.length - 1];
  if (points.length < 2 || !last) return null;

  const max = Math.max(...points.map((p) => p.queue), 1);
  const pad = 3; // keep the end-point dot inside the viewBox
  const stepX = (width - pad) / (points.length - 1);
  const y = (q: number) => height - pad - (q / max) * (height - 2 * pad);
  const line = points.map((p, i) => `${(i * stepX).toFixed(1)},${y(p.queue).toFixed(1)}`).join(" ");
  const stroke = TIER_STROKE[last.tier];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={className}
      role="img"
      aria-label={label}
      style={{ direction: "ltr" }}
    >
      <polygon points={`0,${height} ${line} ${width - pad},${height}`} fill={stroke} opacity={0.12} />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={width - pad} cy={y(last.queue)} r={2.5} fill={stroke} />
    </svg>
  );
}
