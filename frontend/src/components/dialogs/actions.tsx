import { notifications } from '@mantine/notifications';
import { useUpdateOccurrence } from '../../api/hooks';
import type { ISODate, Occurrence } from '../../api/types';
import { date, days, lateBy } from '../../lib/format';
import { markHit } from '../../lib/hits';

export function toast(text: string, undo?: () => void) {
  const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  notifications.show({
    id,
    withCloseButton: true,
    autoClose: undo ? false : 6000,
    message: (
      <span className="toast-body">
        <span>{text}</span>
        {undo && (
          <button
            type="button"
            className="toast-action"
            onClick={() => {
              notifications.hide(id);
              undo();
            }}
          >
            Отменить
          </button>
        )}
      </span>
    ),
  });
}

export function usePaymentActions() {
  const update = useUpdateOccurrence();

  const markPaid = async (occ: Occurrence, paidDate: ISODate, inCard = false) => {
    await update.mutateAsync({ id: occ.id, status: 'paid', paid_date: paidDate });
    markHit(occ.id);
    if (inCard) {
      toast(`Оплата отмечена: ${date(paidDate)}.`);
      return;
    }
    toast(`Оплата отмечена: «${occ.recurring_payment.name}», ${date(paidDate)}. Исправить дату или снять отметку можно в карточке периода.`, () => {
      update.mutate({ id: occ.id, status: 'unpaid' }, { onSuccess: () => toast('Отметка снята.') });
    });
  };

  const unmark = async (occ: Occurrence, inCard = false) => {
    const was = occ.paid_date;
    await update.mutateAsync({ id: occ.id, status: 'unpaid' });
    toast(
      `Отметка об оплате «${occ.recurring_payment.name}» снята.`,
      inCard || !was ? undefined : () => update.mutate({ id: occ.id, status: 'paid', paid_date: was }, { onSuccess: () => toast('Отметка возвращена.') }),
    );
  };

  const changeDate = async (occ: Occurrence, paidDate: ISODate) => {
    const wasLate = !!occ.paid_date && occ.paid_date > occ.due_date;
    await update.mutateAsync({ id: occ.id, status: 'paid', paid_date: paidDate });
    const late = lateBy(occ.due_date, paidDate);
    toast(`Дата оплаты: ${date(paidDate)}. ${wasLate && late <= 0 ? 'Просрочка снята.' : late > 0 ? `Оплачено с опозданием на ${days(late)}.` : 'Оплачено вовремя.'}`);
  };

  return { markPaid, unmark, changeDate, pending: update.isPending };
}
