const STRONG = new Set(['S+', 'S', 'A+', 'A']);
const WEAK = new Set(['C', 'D']);

function tone(rating: string): 'strong' | 'neutral' | 'weak' {
  if (STRONG.has(rating)) return 'strong';
  if (WEAK.has(rating)) return 'weak';
  return 'neutral';
}

/** 紧凑评级字母徽章：列表页用，无评级显示 — */
export default function RatingTag({ rating }: { rating: string | null }) {
  if (!rating) return <span className="rating-tag rating-tag-none">—</span>;
  return <span className={`rating-tag rating-tag-${tone(rating)}`}>{rating}</span>;
}
