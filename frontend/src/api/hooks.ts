import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useTeamScope } from '../auth/team';
import { api } from './client';
import type {
  Attachment, AuditLog, Budget, CalendarMonth, Inbox, LinkCode, LoginResponse, Me, NewPayment, NotificationLog,
  Occurrence, OccurrenceDetail, OccurrenceQuery, Page, RecurringPayment, RecurringPaymentDetail, Summary, Team, TeamInput, User, UserInput,
} from './types';

export const qk = {
  me: ['me'] as const,
  occurrences: (q?: OccurrenceQuery) => ['occurrences', q ?? {}] as const,
  occurrence: (id: string) => ['occurrence', id] as const,
  payments: (q?: object) => ['recurring-payments', q ?? {}] as const,
  payment: (id: string, teamId?: string) => ['recurring-payment', id, teamId ?? null] as const,
  summary: (q: object) => ['summary', q] as const,
  calendar: (month: string, teamId?: string) => ['calendar', month, teamId ?? null] as const,
  budgets: (year: number, month: number, teamId?: string) => ['budgets', year, month, teamId ?? null] as const,
  users: (teamId?: string) => ['users', teamId ?? null] as const,
  teams: ['teams'] as const,
  audit: (q: object) => ['audit-logs', q] as const,
  notifications: (q: object) => ['notifications', q] as const,
  attachments: (occId: string) => ['attachments', occId] as const,
  inbox: ['inbox'] as const,
};

// Администратор смотрит одну команду или все: выбранная команда уходит в запросы списков и итогов.
const useTeamId = () => useTeamScope().teamId ?? undefined;

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
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSettled: () => qc.clear(),
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string | null; notify_email: boolean }) => api<User>('/auth/me', { method: 'PATCH', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useOccurrences(q: OccurrenceQuery, enabled = true) {
  // Явная команда в запросе важнее выбранной в шапке: так карточка периода показывает соседние периоды его команды.
  const query = { team_id: useTeamId(), ...q };
  return useQuery({
    queryKey: qk.occurrences(query),
    queryFn: () => api<Page<Occurrence>>('/payment-occurrences', { query: query as never }),
    placeholderData: keepPreviousData,
    enabled,
  });
}

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

export function usePayments(q: { include_deleted?: boolean; q?: string; currency?: string }) {
  const query = { ...q, team_id: useTeamId() };
  return useQuery({
    queryKey: qk.payments(query),
    queryFn: () => api<Page<RecurringPayment>>('/recurring-payments', { query: { ...query, limit: 200 } }),
    placeholderData: keepPreviousData,
  });
}

export function usePayment(id: string) {
  const teamId = useTeamId();
  return useQuery({
    queryKey: qk.payment(id, teamId),
    queryFn: () => api<RecurringPaymentDetail>(`/recurring-payments/${id}`, { query: { team_id: teamId } }),
  });
}

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

export function useSummary(q: { date_from: string; date_to: string; as_of?: string }, enabled = true) {
  const query = { ...q, team_id: useTeamId() };
  return useQuery({
    queryKey: qk.summary(query),
    queryFn: () => api<Summary>('/payments/summary', { query }),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useSummaries(ranges: { date_from: string; date_to: string }[]) {
  const teamId = useTeamId();
  return useQueries({
    queries: ranges.map((q) => {
      const query = { ...q, team_id: teamId };
      return { queryKey: qk.summary(query), queryFn: () => api<Summary>('/payments/summary', { query }) };
    }),
  });
}

export function useCalendar(month: string) {
  const teamId = useTeamId();
  return useQuery({
    queryKey: qk.calendar(month, teamId),
    queryFn: () => api<CalendarMonth>('/payments/calendar', { query: { month, team_id: teamId } }),
    placeholderData: keepPreviousData,
  });
}

export function useBudgets(year: number, month: number) {
  const teamId = useTeamId();
  return useQuery({
    queryKey: qk.budgets(year, month, teamId),
    queryFn: () => api<Budget[]>('/budgets', { query: { year, month, team_id: teamId } }),
  });
}

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

export function useUsers(enabled = true) {
  const teamId = useTeamId();
  return useQuery({
    queryKey: qk.users(teamId),
    queryFn: () => api<Page<User>>('/users', { query: { limit: 200, team_id: teamId } }),
    enabled,
  });
}

export function useSaveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: UserInput & { id?: string }) =>
      id ? api<User>(`/users/${id}`, { method: 'PATCH', body }) : api<User>('/users', { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] });
      qc.invalidateQueries({ queryKey: qk.teams });
      qc.invalidateQueries({ queryKey: ['audit-logs'] });
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/users/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] });
      qc.invalidateQueries({ queryKey: qk.teams });
      qc.invalidateQueries({ queryKey: ['audit-logs'] });
    },
  });
}

export const useTeams = (enabled = true) =>
  useQuery({ queryKey: qk.teams, queryFn: () => api<Page<Team>>('/teams', { query: { limit: 200 } }), enabled });

export function useSaveTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: TeamInput & { id?: string }) =>
      id ? api<Team>(`/teams/${id}`, { method: 'PATCH', body }) : api<Team>('/teams', { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.teams });
      // Новая команда сразу получает общие платежи — периоды и итоги меняются.
      invalidatePayments(qc);
    },
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/teams/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.teams });
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
