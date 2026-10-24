import { diffDays, type ISODate } from './dates';

const hits = new Map<string, number>();

export const markHit = (id: string) => hits.set(id, Date.now());
export const isFresh = (id: string) => Date.now() - (hits.get(id) ?? 0) < 1600;

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function stampStyle(id: string, paidDate: ISODate | null, late: boolean, today: ISODate) {
  const h = hash(id);
  const rot = -1.5 - (h % 30) / 10;
  const dx = h % 7;
  const pos = `${h % 60}px ${(h >> 3) % 40}px`;
  const fresh = isFresh(id) || late || (paidDate ? diffDays(paidDate, today) <= 3 : false);
  return {
    transform: `translateX(${dx}px) rotate(${rot.toFixed(1)}deg)`,
    WebkitMaskPosition: pos,
    maskPosition: pos,
    opacity: fresh ? 1 : 0.8,
  };
}
