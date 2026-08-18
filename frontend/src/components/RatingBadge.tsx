import { fmtNum } from '../utils/format';

/** 蓝色圆形评级徽章：评级字母 + 评分/满分 */
export default function RatingBadge({ rating, score }: { rating: string; score: number }) {
  return (
    <div className="rating-badge">
      <span className="rating">{rating}</span>
      <span className="score mono">{fmtNum(score, 0)} / 100</span>
    </div>
  );
}
