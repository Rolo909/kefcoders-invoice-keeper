import { useEffect, useRef, useState } from 'react';
import { num } from '../lib/format';

export function CountUp({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  const [changed, setChanged] = useState(false);
  const from = useRef(value);

  useEffect(() => {
    const start = from.current;
    from.current = value;
    if (start === value) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(value);
      return;
    }
    let raf = 0;
    let timer = 0;
    const t0 = performance.now() + 260;
    setChanged(true);
    const step = (t: number) => {
      const k = Math.min(1, Math.max(0, (t - t0) / 520));
      setShown(start + (value - start) * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(step);
      else timer = window.setTimeout(() => setChanged(false), 600);
    };
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [value]);

  return <span className={changed ? 'num-changed' : undefined}>{num(shown)}</span>;
}
