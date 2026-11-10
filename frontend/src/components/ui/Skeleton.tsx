import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("motion-safe:animate-pulse rounded-sm bg-sunken", className)} />;
}
