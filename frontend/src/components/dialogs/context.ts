import { createContext, useContext } from 'react';
import type { Attachment, Occurrence, RecurringPayment, Team, User } from '../../api/types';

export type DialogState =
  | { type: 'markPaid'; occ: Occurrence }
  | { type: 'changeDate'; occ: Occurrence }
  | { type: 'unmark'; occ: Occurrence }
  | { type: 'attach'; occ: Occurrence }
  | { type: 'deleteAttachment'; occ: Occurrence; att: Attachment }
  | { type: 'newPayment' }
  | { type: 'stopPayment'; payment: RecurringPayment }
  | { type: 'userForm'; user?: User }
  | { type: 'deleteUser'; user: User }
  | { type: 'teamForm'; team?: Team }
  | { type: 'deleteTeam'; team: Team };

export interface DialogsApi {
  dialog: DialogState | null;
  periodId: string | null;
  open: (d: DialogState) => void;
  close: () => void;
  openPeriod: (id: string) => void;
  closePeriod: () => void;
}

export const DialogsContext = createContext<DialogsApi | null>(null);

export function useDialogs() {
  const ctx = useContext(DialogsContext);
  if (!ctx) throw new Error('useDialogs must be used inside DialogsProvider');
  return ctx;
}
