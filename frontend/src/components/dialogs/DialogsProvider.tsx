import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Drawer } from '@mantine/core';
import { Link, useLocation } from 'react-router-dom';
import { DialogsContext, type DialogState } from './context';
import { Modals } from './Modals';
import { PeriodCard } from './PeriodCard';

export function DialogsProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [periodId, setPeriodId] = useState<string | null>(null);
  const location = useLocation();

  const close = useCallback(() => setDialog(null), []);
  const closePeriod = useCallback(() => setPeriodId(null), []);
  const value = useMemo(
    () => ({ dialog, periodId, open: setDialog, close, openPeriod: setPeriodId, closePeriod }),
    [dialog, periodId, close, closePeriod],
  );
  useEffect(() => {
    setPeriodId(null);
    setDialog(null);
  }, [location.pathname]);

  const inCard = !!periodId || location.pathname.startsWith('/occurrences/');

  return (
    <DialogsContext.Provider value={value}>
      {children}
      <Drawer opened={!!periodId} onClose={closePeriod} title={<span className="sr-only">Карточка периода</span>} zIndex={200}>
        {periodId && (
          <>
            <p style={{ marginBottom: 10 }}>
              <Link className="small" to={`/occurrences/${periodId}`} onClick={closePeriod}>Открыть страницу периода</Link>
            </p>
            <PeriodCard id={periodId} />
          </>
        )}
      </Drawer>
      <Modals dialog={dialog} inCard={inCard} onClose={close} />
    </DialogsContext.Provider>
  );
}
