import { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { PeriodCard } from '../components/dialogs/PeriodCard';

export function OccurrencePage() {
  const { id = '' } = useParams();
  useEffect(() => {
    document.title = 'Период — Invoice Keeper';
  }, []);
  return (
    <div style={{ maxWidth: 860 }}>
      <p className="crumbs"><Link to="/occurrences">Периоды</Link> ›</p>
      <PeriodCard id={id} asPage />
    </div>
  );
}
