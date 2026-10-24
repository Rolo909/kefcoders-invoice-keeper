import { useEffect, useState, type FormEvent } from 'react';
import { Button, Checkbox, Group, Modal, NativeSelect, PasswordInput, SegmentedControl, Stack, Textarea, TextInput } from '@mantine/core';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ApiError } from '../../api/client';
import { useAddAttachment, useCreatePayment, useDeleteAttachment, useDeleteUser, usePayment, useSaveUser, useStopPayment } from '../../api/hooks';
import type { Attachment, Occurrence, RecurringPayment, User } from '../../api/types';
import { useAuth } from '../../auth/context';
import { diffDays } from '../../lib/dates';
import { date, days, money, plural, shortDate } from '../../lib/format';
import { toast, usePaymentActions } from './actions';
import type { DialogState } from './context';

const errText = (e: unknown) => (e instanceof ApiError ? e.detail : 'Не удалось сохранить. Проверьте соединение и попробуйте ещё раз.');

function DateForm({ occ, mode, onClose }: { occ: Occurrence; mode: 'mark' | 'change'; onClose: () => void }) {
  const { today } = useAuth();
  const actions = usePaymentActions();
  const [value, setValue] = useState(mode === 'change' && occ.paid_date ? occ.paid_date : today);
  const [error, setError] = useState('');
  const late = value && value <= today ? diffDays(occ.due_date, value) : null;
  const hint = late === null ? (mode === 'mark' ? 'Оплата в день срока считается вовремя.' : 'Если дата не позже срока, просрочка снимется.')
    : late > 0 ? `Будет: оплачено с опозданием на ${days(late)}.` : 'Будет: оплачено вовремя.';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!value) return setError('Укажите дату оплаты.');
    if (value > today) return setError(`Укажите дату не позже сегодняшней — ${date(today)}.`);
    setError('');
    try {
      if (mode === 'mark') await actions.markPaid(occ, value);
      else await actions.changeDate(occ, value);
      onClose();
    } catch (err) {
      setError(errText(err));
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <p>
          <b>{occ.recurring_payment.name}</b>
          <br />
          <span className="muted">
            {mode === 'mark'
              ? `Срок ${date(occ.due_date)} · ${money(occ.amount, occ.currency)}`
              : `Срок ${date(occ.due_date)} не меняется. Сейчас оплата отмечена ${date(occ.paid_date)}.`}
          </span>
        </p>
        <TextInput
          type="date"
          label={mode === 'mark' ? 'Фактическая дата оплаты' : 'Новая фактическая дата'}
          value={value}
          max={today}
          onChange={(e) => setValue(e.currentTarget.value)}
          description={hint}
          error={error || undefined}
          classNames={{ input: 'mono' }}
          data-autofocus
        />
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="filled" loading={actions.pending}>{mode === 'mark' ? 'Отметить оплату' : 'Сохранить дату'}</Button>
        </Group>
      </Stack>
    </form>
  );
}

function UnmarkBody({ occ, inCard, onClose }: { occ: Occurrence; inCard: boolean; onClose: () => void }) {
  const { today } = useAuth();
  const actions = usePaymentActions();
  const [error, setError] = useState('');
  return (
    <Stack gap="md">
      <p>Фактическая дата {date(occ.paid_date)} удалится, период снова станет неоплаченным.</p>
      {occ.due_date < today && <p className="red">Срок прошёл, поэтому период сразу станет просроченным.</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onClose} data-autofocus>Оставить отметку</Button>
        <Button
          variant="filled"
          color="red"
          loading={actions.pending}
          onClick={async () => {
            try {
              await actions.unmark(occ, inCard);
              onClose();
            } catch (e) {
              setError(errText(e));
            }
          }}
        >
          Снять отметку
        </Button>
      </Group>
    </Stack>
  );
}

function AttachBody({ occ, onClose }: { occ: Occurrence; onClose: () => void }) {
  const add = useAddAttachment();
  const [kind, setKind] = useState<'file' | 'link'>('file');
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (kind === 'file') {
      if (!file) return setError('Выберите файл чека: PDF, PNG, JPG или WebP до 10 МБ.');
      if (!/\.(pdf|png|jpe?g|webp)$/i.test(file.name)) return setError('Подходят PDF, PNG, JPG и WebP. Сохраните чек в одном из этих форматов.');
      if (file.size > 10 * 1024 * 1024) return setError('Файл больше 10 МБ. Сожмите его или прикрепите ссылку на чек.');
    } else if (!/^https?:\/\/\S+\.\S+/.test(url)) {
      return setError('Вставьте ссылку целиком, начиная с https://');
    }
    setError('');
    try {
      await add.mutateAsync(kind === 'file' ? { occId: occ.id, file: file! } : { occId: occ.id, url });
      toast(kind === 'file' ? `Чек ${file!.name} прикреплён.` : 'Ссылка прикреплена.');
      onClose();
    } catch (err) {
      setError(errText(err));
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <p className="muted">{occ.recurring_payment.name}, период {date(occ.due_date)}</p>
        <SegmentedControl
          value={kind}
          onChange={(v) => { setKind(v as 'file' | 'link'); setError(''); }}
          data={[{ value: 'file', label: 'Файл чека' }, { value: 'link', label: 'Ссылка' }]}
          aria-label="Что прикрепить"
          w="fit-content"
        />
        {kind === 'file' ? (
          <label className="file-field">
            <span className="ik-label">Файл</span>
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" onChange={(e) => { setFile(e.currentTarget.files?.[0] ?? null); setError(''); }} />
            <span className="ik-hint">PDF, PNG, JPG или WebP, до 10 МБ.</span>
          </label>
        ) : (
          <TextInput type="url" inputMode="url" label="Ссылка на чек или счёт" placeholder="https://lk.mts.ru/bill/2026-10" value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
        )}
        {error && <p className="ik-error" role="alert">{error}</p>}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="filled" loading={add.isPending}>{kind === 'link' ? 'Прикрепить ссылку' : 'Прикрепить чек'}</Button>
        </Group>
      </Stack>
    </form>
  );
}

function DeleteAttachmentBody({ occ, att, onClose }: { occ: Occurrence; att: Attachment; onClose: () => void }) {
  const del = useDeleteAttachment();
  const [error, setError] = useState('');
  return (
    <Stack gap="md">
      <p>{att.kind === 'link' ? 'Ссылка удалится' : 'Файл удалится'} из периода «{occ.recurring_payment.name}» за {date(occ.due_date)}. Вернуть его будет нельзя — только прикрепить заново.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onClose} data-autofocus>Оставить</Button>
        <Button
          variant="filled"
          color="red"
          loading={del.isPending}
          onClick={async () => {
            try {
              await del.mutateAsync({ id: att.id, occId: occ.id });
              toast(`Вложение «${att.original_name}» удалено.`);
              onClose();
            } catch (e) {
              setError(errText(e));
            }
          }}
        >
          {att.kind === 'link' ? 'Удалить ссылку' : 'Удалить чек'}
        </Button>
      </Group>
    </Stack>
  );
}

const paymentSchema = z
  .object({
    name: z.string().trim().min(1, 'Введите название, например «Аренда офиса».').max(200, 'Название — не длиннее 200 символов.'),
    description: z.string().optional(),
    amount: z.string().refine((v) => {
      const n = v.replace(/\s/g, '').replace(',', '.');
      return /^\d+(\.\d{1,2})?$/.test(n) && Number(n) > 0;
    }, 'Введите сумму больше нуля, не больше двух знаков после запятой: 50000 или 20,50.'),
    currency: z.enum(['RUB', 'USD', 'EUR']),
    period: z.enum(['monthly', 'weekly', 'quarterly', 'yearly']),
    next_due_date: z.string().min(1, 'Укажите дату ближайшей оплаты.'),
    end_date: z.string().optional(),
  })
  .refine((v) => !v.end_date || v.end_date >= v.next_due_date, { path: ['end_date'], message: 'Дата окончания должна быть не раньше даты ближайшей оплаты.' });
type PaymentForm = z.infer<typeof paymentSchema>;

function NewPaymentBody({ onClose }: { onClose: () => void }) {
  const { today } = useAuth();
  const create = useCreatePayment();
  const [error, setError] = useState('');
  const { register, handleSubmit, formState: { errors } } = useForm<PaymentForm>({
    resolver: zodResolver(paymentSchema),
    defaultValues: { name: '', description: '', amount: '', currency: 'RUB', period: 'monthly', next_due_date: '', end_date: '' },
  });

  const submit = handleSubmit(async (v) => {
    setError('');
    try {
      const p = await create.mutateAsync({
        name: v.name.trim(), description: v.description?.trim() || null, amount: Number(v.amount.replace(/\s/g, '').replace(',', '.')).toFixed(2),
        currency: v.currency, period: v.period, next_due_date: v.next_due_date, end_date: v.end_date || null,
      });
      const soon = diffDays(today, v.next_due_date) <= 3 && v.next_due_date >= today;
      toast(`Платёж «${p.name}» создан. Первый срок — ${date(v.next_due_date)}.${soon ? ' До срока меньше 3 дней — напоминание уже ушло в Telegram.' : ''}`);
      onClose();
    } catch (e) {
      setError(errText(e));
    }
  });

  return (
    <form onSubmit={submit} noValidate>
      <div className="form-grid">
        <TextInput className="wide" label="Название" placeholder="Аренда офиса" maxLength={200} autoComplete="off" error={errors.name?.message} {...register('name')} data-autofocus />
        <Textarea className="wide" label="Описание — необязательно" placeholder="Договор № 14/2025, оплата до 26-го числа" autosize minRows={2} {...register('description')} />
        <TextInput label="Сумма" placeholder="50 000,00" inputMode="decimal" autoComplete="off" classNames={{ input: 'mono' }} error={errors.amount?.message} {...register('amount')} />
        <NativeSelect label="Валюта" data={[{ value: 'RUB', label: 'RUB — рубли' }, { value: 'USD', label: 'USD — доллары' }, { value: 'EUR', label: 'EUR — евро' }]} {...register('currency')} />
        <NativeSelect label="Периодичность" data={[{ value: 'monthly', label: 'Ежемесячно' }, { value: 'weekly', label: 'Еженедельно' }, { value: 'quarterly', label: 'Раз в квартал' }, { value: 'yearly', label: 'Раз в год' }]} {...register('period')} />
        <TextInput
          type="date"
          label="Дата ближайшей оплаты"
          classNames={{ input: 'mono' }}
          description="Если в месяце нет такого числа, срок — последний день месяца. До срока меньше 3 дней — напоминание уйдёт сразу."
          error={errors.next_due_date?.message}
          {...register('next_due_date')}
        />
        <TextInput type="date" label="Окончание — необязательно" classNames={{ input: 'mono' }} error={errors.end_date?.message} {...register('end_date')} />
      </div>
      {error && <p className="form-error" role="alert" style={{ marginTop: 16 }}>{error}</p>}
      <Group justify="flex-end" mt="lg">
        <Button variant="subtle" onClick={onClose}>Отмена</Button>
        <Button type="submit" variant="filled" loading={create.isPending}>Создать платёж</Button>
      </Group>
    </form>
  );
}

function StopPaymentBody({ payment, onClose }: { payment: RecurringPayment; onClose: () => void }) {
  const { today } = useAuth();
  const detail = usePayment(payment.id);
  const stop = useStopPayment();
  const [error, setError] = useState('');
  const occs = detail.data?.occurrences ?? [];
  const future = occs.filter((o) => o.due_date > today && !o.paid_date).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const kept = occs.length - future.length;
  return (
    <Stack gap="md">
      <ul className="list-ruled">
        <li>Новые периоды и напоминания больше не появятся.</li>
        <li>{detail.isPending ? 'Считаем будущие периоды…' : future.length ? `Будущие неоплаченные периоды удалятся: ${future.map((o) => date(o.due_date)).join(', ')}.` : 'Будущих неоплаченных периодов нет.'}</li>
        <li>История сохранится: {kept} {plural(kept, 'период', 'периода', 'периодов')} с оплатами и вложениями.</li>
      </ul>
      {error && <p className="form-error" role="alert">{error}</p>}
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onClose} data-autofocus>Не прекращать</Button>
        <Button
          variant="filled"
          color="red"
          loading={stop.isPending}
          onClick={async () => {
            try {
              await stop.mutateAsync(payment.id);
              toast(`Платёж «${payment.name}» прекращён. История оплат сохранена.`);
              onClose();
            } catch (e) {
              setError(errText(e));
            }
          }}
        >
          Прекратить платёж
        </Button>
      </Group>
    </Stack>
  );
}

function UserFormBody({ user, onClose }: { user?: User; onClose: () => void }) {
  const save = useSaveUser();
  const [error, setError] = useState('');
  const schema = z
    .object({
      login: z.string().trim().regex(/^[a-z0-9._-]{3,64}$/i, 'Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний.'),
      full_name: z.string().optional(),
      email: z.string().trim().refine((v) => !v || /^\S+@\S+\.\S+$/.test(v), 'Введите адрес целиком, например name@kefcoders.ru.'),
      password: z.string().refine((v) => (user ? !v || v.length >= 8 : v.length >= 8), user ? 'Новый пароль — не короче 8 символов. Оставьте поле пустым, чтобы не менять.' : 'Пароль — не короче 8 символов.'),
      notify_email: z.boolean(),
    })
    .refine((v) => !v.notify_email || !!v.email, { path: ['email'], message: 'Укажите почту, чтобы присылать на неё напоминания.' });
  type Form = z.infer<typeof schema>;
  const { register, handleSubmit, setError: setFieldError, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: { login: user?.login ?? '', full_name: user?.full_name ?? '', email: user?.email ?? '', password: '', notify_email: user?.notify_email ?? false },
  });

  const submit = handleSubmit(async (v) => {
    setError('');
    try {
      await save.mutateAsync({
        id: user?.id, login: v.login.trim(), full_name: v.full_name?.trim() || null, email: v.email.trim() || null,
        notify_email: v.notify_email, ...(v.password ? { password: v.password } : {}),
      });
      toast(user ? `Изменения пользователя ${v.login} сохранены.` : `Пользователь ${v.login} создан. Передайте ему логин и пароль.`);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'login_taken') setFieldError('login', { message: e.detail });
      else setError(errText(e));
    }
  });

  return (
    <form onSubmit={submit} noValidate>
      <div className="form-grid">
        <TextInput label="Логин" placeholder="ivan.petrov" autoComplete="off" autoCapitalize="off" spellCheck={false} classNames={{ input: 'mono' }} error={errors.login?.message} {...register('login')} data-autofocus />
        <TextInput label="Имя и фамилия — необязательно" placeholder="Иван Петров" autoComplete="off" {...register('full_name')} />
        <TextInput type="email" inputMode="email" label="Почта — необязательно" placeholder="ivan@kefcoders.ru" autoComplete="off" error={errors.email?.message} {...register('email')} />
        <PasswordInput
          label={user ? 'Новый пароль — необязательно' : 'Пароль'}
          autoComplete="new-password"
          description={user ? 'Смена пароля завершит все сессии пользователя.' : 'Не короче 8 символов.'}
          error={errors.password?.message}
          {...register('password')}
        />
        <Checkbox className="wide" label="Присылать напоминания на почту" {...register('notify_email')} />
        {!user && <p className="wide muted small">Новый пользователь получит роль «пользователь». Администратор задаётся только в файле .env.</p>}
      </div>
      {error && <p className="form-error" role="alert" style={{ marginTop: 16 }}>{error}</p>}
      <Group justify="flex-end" mt="lg">
        <Button variant="subtle" onClick={onClose}>Отмена</Button>
        <Button type="submit" variant="filled" loading={save.isPending}>{user ? 'Сохранить изменения' : 'Создать пользователя'}</Button>
      </Group>
    </form>
  );
}

function DeleteUserBody({ user, onClose }: { user: User; onClose: () => void }) {
  const del = useDeleteUser();
  const [error, setError] = useState('');
  return (
    <Stack gap="md">
      <p>{user.full_name ? `${user.full_name} — ` : ''}доступ пропадёт сразу, все сессии завершатся.</p>
      <p className="muted">Отметки об оплате и вложения этого пользователя останутся в истории.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onClose} data-autofocus>Не удалять</Button>
        <Button
          variant="filled"
          color="red"
          loading={del.isPending}
          onClick={async () => {
            try {
              await del.mutateAsync(user.id);
              toast(`Пользователь ${user.login} удалён.`);
              onClose();
            } catch (e) {
              setError(errText(e));
            }
          }}
        >
          Удалить пользователя
        </Button>
      </Group>
    </Stack>
  );
}

function titleOf(d: DialogState) {
  switch (d.type) {
    case 'markPaid': return 'Отметить оплату';
    case 'changeDate': return 'Изменить дату оплаты';
    case 'unmark': return `Снять отметку об оплате «${d.occ.recurring_payment.name}» за ${shortDate(d.occ.due_date)}?`;
    case 'attach': return 'Прикрепить чек или ссылку';
    case 'deleteAttachment': return `${d.att.kind === 'link' ? 'Удалить ссылку' : 'Удалить чек'} «${d.att.original_name}»?`;
    case 'newPayment': return 'Новый регулярный платёж';
    case 'stopPayment': return `Прекратить «${d.payment.name}»?`;
    case 'userForm': return d.user ? `Изменить пользователя ${d.user.login}` : 'Новый пользователь';
    case 'deleteUser': return `Удалить пользователя ${d.user.login}?`;
  }
}

export function Modals({ dialog, inCard, onClose }: { dialog: DialogState | null; inCard: boolean; onClose: () => void }) {
  const [shown, setShown] = useState(dialog);
  useEffect(() => {
    if (dialog) setShown(dialog);
  }, [dialog]);
  const d = dialog ?? shown;
  const wide = d?.type === 'newPayment' || d?.type === 'userForm';
  const side = d?.type === 'markPaid' || d?.type === 'changeDate';
  return (
    <Modal
      opened={!!dialog}
      onClose={onClose}
      title={d ? titleOf(d) : ''}
      size={wide ? 680 : 520}
      zIndex={300}
      centered={!side}
      classNames={side ? { inner: 'ik-modal-side' } : undefined}
    >
      {d?.type === 'markPaid' && <DateForm key={d.occ.id} occ={d.occ} mode="mark" onClose={onClose} />}
      {d?.type === 'changeDate' && <DateForm key={d.occ.id} occ={d.occ} mode="change" onClose={onClose} />}
      {d?.type === 'unmark' && <UnmarkBody occ={d.occ} inCard={inCard} onClose={onClose} />}
      {d?.type === 'attach' && <AttachBody key={d.occ.id} occ={d.occ} onClose={onClose} />}
      {d?.type === 'deleteAttachment' && <DeleteAttachmentBody occ={d.occ} att={d.att} onClose={onClose} />}
      {d?.type === 'newPayment' && <NewPaymentBody onClose={onClose} />}
      {d?.type === 'stopPayment' && <StopPaymentBody payment={d.payment} onClose={onClose} />}
      {d?.type === 'userForm' && <UserFormBody key={d.user?.id ?? 'new'} user={d.user} onClose={onClose} />}
      {d?.type === 'deleteUser' && <DeleteUserBody user={d.user} onClose={onClose} />}
    </Modal>
  );
}

