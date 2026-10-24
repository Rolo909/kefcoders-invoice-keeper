import type { ISODate, Period } from '../lib/dates';

export type Currency = 'RUB' | 'USD' | 'EUR';
export type Role = 'admin' | 'user';
export type OccurrenceStatus = 'paid' | 'unpaid';
export type OccurrenceState = 'paid' | 'paid_late' | 'overdue' | 'due_soon' | 'upcoming';
export type Channel = 'telegram' | 'email' | 'webhook' | 'inapp';
export type NotificationKind = 'before_due' | 'overdue';
export type { Period, ISODate };

export interface UserBrief {
  id: string;
  login: string;
  full_name: string | null;
}

export interface TeamBrief {
  id: string;
  name: string;
}

export interface Team extends TeamBrief {
  telegram_chat_id: string | null;
  members_count: number;
  created_at: string;
}

export interface User extends UserBrief {
  email: string | null;
  role: Role;
  is_system: boolean;
  team: TeamBrief | null;
  telegram_linked: boolean;
  notify_email: boolean;
  created_at: string;
}

export interface Me {
  user: User;
  server_today: ISODate;
  timezone: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: User;
}

export interface PaymentBrief {
  id: string;
  name: string;
  period: Period;
  is_deleted: boolean;
}

export interface Occurrence {
  id: string;
  recurring_payment_id: string;
  recurring_payment: PaymentBrief;
  team: TeamBrief;
  seq: number;
  due_date: ISODate;
  amount: string;
  currency: Currency;
  status: OccurrenceStatus;
  paid_date: ISODate | null;
  paid_by: UserBrief | null;
  paid_marked_at: string | null;
  note: string | null;
  is_overdue: boolean;
  state: OccurrenceState;
  days_overdue: number;
  attachments_count: number;
  last_reminder_at: string | null;
}

export interface AuditLog {
  id: string;
  at: string;
  actor: UserBrief | null;
  actor_login: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, string | number | boolean | null>;
  ip: string | null;
}

export interface NotificationLog {
  id: string;
  occurrence_id: string;
  payment_name: string;
  due_date: ISODate;
  team: TeamBrief | null;
  channel: Channel;
  kind: NotificationKind;
  status: 'pending' | 'sent' | 'failed';
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface OccurrenceDetail extends Occurrence {
  history: AuditLog[];
  reminders: NotificationLog[];
}

export interface RecurringPayment {
  id: string;
  name: string;
  description: string | null;
  amount: string;
  currency: Currency;
  period: Period;
  first_due_date: ISODate;
  end_date: ISODate | null;
  team: TeamBrief | null;
  is_active: boolean;
  deleted_at: string | null;
  created_by: UserBrief;
  created_at: string;
  next_occurrence: Occurrence | null;
}

export interface RecurringPaymentDetail extends RecurringPayment {
  occurrences: Occurrence[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CurrencyTotal {
  currency: Currency;
  planned: string;
  paid: string;
  unpaid: string;
  overdue: string;
  paid_late: string;
  count_total: number;
  count_paid: number;
  count_overdue: number;
  budget: string | null;
  budget_left: string | null;
}

export interface Summary {
  period: { from: ISODate; to: ISODate };
  as_of: ISODate;
  totals: CurrencyTotal[];
}

export interface PlannedItem {
  recurring_payment_id: string;
  team: TeamBrief;
  name: string;
  due_date: ISODate;
  amount: string;
  currency: Currency;
}

export interface CalendarDay {
  date: ISODate;
  occurrences: Occurrence[];
  planned: PlannedItem[];
}

export interface CalendarMonth {
  month: string;
  days: CalendarDay[];
}

export interface Budget {
  team_id: string;
  currency: Currency;
  period_type: 'month' | 'year';
  year: number;
  month: number | null;
  amount: string;
}

export interface Attachment {
  id: string;
  occurrence_id: string;
  kind: 'file' | 'link';
  url: string | null;
  original_name: string;
  content_type: string | null;
  size: number | null;
  uploaded_by: UserBrief;
  created_at: string;
}

export interface InboxItem {
  id: string;
  occurrence_id: string;
  team: TeamBrief;
  kind: NotificationKind;
  created_at: string;
  read: boolean;
  payment_name: string;
  amount: string;
  currency: Currency;
  due_date: ISODate;
  occurrence_state: OccurrenceState;
  paid_date: ISODate | null;
  payment_deleted: boolean;
}

export interface Inbox {
  items: InboxItem[];
  unread_count: number;
}

export interface LinkCode {
  code: string;
  expires_at: string;
}

export interface OccurrenceQuery {
  status?: OccurrenceStatus;
  overdue?: boolean;
  currency?: Currency[];
  date_from?: ISODate;
  date_to?: ISODate;
  recurring_payment_id?: string;
  team_id?: string;
  sort?: 'due_date' | '-due_date' | 'amount' | '-amount' | 'days_overdue' | '-days_overdue';
  limit?: number;
  offset?: number;
}

export interface NewPayment {
  name: string;
  description?: string | null;
  amount: string;
  currency: Currency;
  period: Period;
  next_due_date: ISODate;
  end_date?: ISODate | null;
  team_id: string | null;
}

export interface UserInput {
  login: string;
  full_name?: string | null;
  email?: string | null;
  password?: string;
  notify_email?: boolean;
  team_id?: string;
}

export interface TeamInput {
  name: string;
  telegram_chat_id: string | null;
}
