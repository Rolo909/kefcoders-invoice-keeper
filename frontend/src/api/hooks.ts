import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { announceAuthChange } from '../auth/sync';
import { api } from './client';
import type {
  Attachment, AuditLog, Budget, CalendarMonth, CalendarSubscription, Inbox, LinkCode, LoginResponse, Me, NewPayment, NotificationLog,
  Occurrence, OccurrenceDetail, OccurrenceQuery, Page, RecurringPayment, RecurringPaymentDetail, Summary, User, UserInput,
} from './types';

export const qk = {
  me: ['me'] as const,
  occurrences: (q?: OccurrenceQuery) => ['occurrences', q ?? {}] as const,
  occurrence: (id: string) => ['occurrence', id] as const,
  payments: (q?: object) => ['recurring-payments', q ?? {}] as const,
  payment: (id: string) => ['recurring-payment', id] as const,
  summary: (q: object) => ['summary', q] as const,
  calendar: (month: string) => ['calendar', month] as const,
  budgets: (year: number, month: number) => ['budgets', year, month] as const,
  users: ['users'] as const,
  audit: (q: object) => ['audit-logs', q] as const,
  notifications: (q: object) => ['notifications', q] as const,
  attachments: (occId: string) => ['attachments', occId] as const,
  inbox: ['inbox'] as const,
};

export function invalidatePayments(qc: QueryClient) {
  for (const key of ['occurrences', 'occurrence', 'recurring-payments', 'recurring-payment', 'summary', 'calendar', 'inbox', 'notifications', 'audit-logs']) {
    qc.invalidateQueries({ queryKey: [key] });
  }
}

export const useMe = () =>
  useQuery({ queryKey: qk.me, queryFn: () => api<Me>('/auth/me'), retry: false, staleTime: 60_000 });

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { login: string; password: string }) => api<LoginResponse>('/auth/login', { method: 'POST', body }),
    onSuccess: () => {
      announceAuthChange();
      return qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      announceAuthChange();
      qc.clear();
    },
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string | null; notify_email: boolean }) => api<User>('/auth/me', { method: 'PATCH', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }),
  });
}

export const useOccurrences = (q: OccurrenceQuery, enabled = true) =>
  useQuery({
    queryKey: qk.occurrences(q),
    queryFn: () => api<Page<Occurrence>>('/payment-occurrences', { query: { ...q } as never }),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useOccurrence = (id: string | null) =>
  useQuery({
    queryKey: qk.occurrence(id ?? ''),
    queryFn: () => api<OccurrenceDetail>(`/payment-occurrences/${id}`),
    enabled: !!id,
  });

export function useUpdateOccurrence() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: 'paid' | 'unpaid'; paid_date?: string | null }) =>
      api<Occurrence>(`/payment-occurrences/${id}`, { method: 'PATCH', body }),
    onSuccess: () => invalidatePayments(qc),
    // Например, 409 already_paid: период успели оплатить — подтягиваем свежие данные, кнопка сменится на отметку.
    onError: () => invalidatePayments(qc),
  });
}

export const usePayments = (q: { include_deleted?: boolean; q?: string; currency?: string }) =>
  useQuery({
    queryKey: qk.payments(q),
    queryFn: () => api<Page<RecurringPayment>>('/recurring-payments', { query: { ...q, limit: 200 } }),
    placeholderData: keepPreviousData,
  });

export const usePayment = (id: string) =>
  useQuery({ queryKey: qk.payment(id), queryFn: () => api<RecurringPaymentDetail>(`/recurring-payments/${id}`) });

export function useCreatePayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewPayment) => api<RecurringPayment>('/recurring-payments', { method: 'POST', body }),
    onSuccess: () => invalidatePayments(qc),
  });
}

export function useStopPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/recurring-payments/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidatePayments(qc),
  });
}

export const useSummary = (q: { date_from: string; date_to: string; as_of?: string }, enabled = true) =>
  useQuery({
    queryKey: qk.summary(q),
    queryFn: () => api<Summary>('/payments/summary', { query: q }),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useSummaries = (ranges: { date_from: string; date_to: string }[]) =>
  useQueries({
    queries: ranges.map((q) => ({ queryKey: qk.summary(q), queryFn: () => api<Summary>('/payments/summary', { query: q }) })),
  });

export const useCalendar = (month: string) =>
  useQuery({
    queryKey: qk.calendar(month),
    queryFn: () => api<CalendarMonth>('/payments/calendar', { query: { month } }),
    placeholderData: keepPreviousData,
  });

export const useBudgets = (year: number, month: number) =>
  useQuery({ queryKey: qk.budgets(year, month), queryFn: () => api<Budget[]>('/budgets', { query: { year, month } }) });

export function useSaveBudgets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Budget[]) => api<Budget[]>('/budgets', { method: 'PUT', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['budgets'] });
      qc.invalidateQueries({ queryKey: ['summary'] });
    },
  });
}

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: qk.users, queryFn: () => api<Page<User>>('/users', { query: { limit: 200 } }), enabled });

export function useSaveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: UserInput & { id?: string }) =>
      id ? api<User>(`/users/${id}`, { method: 'PATCH', body }) : api<User>('/users', { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.users });
      qc.invalidateQueries({ queryKey: ['audit-logs'] });
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/users/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.users });
      qc.invalidateQueries({ queryKey: ['audit-logs'] });
    },
  });
}

export const useAuditLogs = (q: { action?: string; actor_id?: string; date_from?: string; date_to?: string; limit: number; offset: number }) =>
  useQuery({ queryKey: qk.audit(q), queryFn: () => api<Page<AuditLog>>('/audit-logs', { query: q }), placeholderData: keepPreviousData });

export const useNotificationLog = (q: { channel?: string; status?: string; limit: number; offset: number }) =>
  useQuery({ queryKey: qk.notifications(q), queryFn: () => api<Page<NotificationLog>>('/notifications', { query: q }), placeholderData: keepPreviousData });

export function useTestNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ channels: { channel: string; ok: boolean; error: string | null }[] }>('/notifications/test', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}

export const useAttachments = (occId: string | null) =>
  useQuery({ queryKey: qk.attachments(occId ?? ''), queryFn: () => api<Attachment[]>(`/payment-occurrences/${occId}/attachments`), enabled: !!occId });

export function useAddAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ occId, file, url }: { occId: string; file?: File; url?: string }) => {
      if (file) {
        const form = new FormData();
        form.append('file', file);
        return api<Attachment>(`/payment-occurrences/${occId}/attachments`, { method: 'POST', body: form });
      }
      return api<Attachment>(`/payment-occurrences/${occId}/attachments`, { method: 'POST', body: { url } });
    },
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: qk.attachments(v.occId) });
      invalidatePayments(qc);
    },
  });
}

export function useDeleteAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string; occId: string }) => api<void>(`/attachments/${id}`, { method: 'DELETE' }),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: qk.attachments(v.occId) });
      invalidatePayments(qc);
    },
  });
}

export const useInbox = (enabled: boolean) =>
  useQuery({ queryKey: qk.inbox, queryFn: () => api<Inbox>('/inbox'), refetchInterval: 30_000, enabled });

export function useReadInbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | 'all') => (id === 'all' ? api<void>('/inbox/read-all', { method: 'POST' }) : api<void>(`/inbox/${id}/read`, { method: 'POST' })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.inbox }),
  });
}

export const useLinkCode = () => useMutation({ mutationFn: () => api<LinkCode>('/telegram/link-code', { method: 'POST' }) });

/** Ссылка на календарь: повторный вызов отдаёт ту же ссылку. */
export const useCalendarSubscription = () =>
  useMutation({ mutationFn: () => api<CalendarSubscription>('/calendar/subscription', { method: 'POST' }) });

export const useRevokeCalendar = () => useMutation({ mutationFn: () => api<void>('/calendar/subscription', { method: 'DELETE' }) });
