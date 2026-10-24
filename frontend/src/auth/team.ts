import { createContext, useContext } from 'react';
import type { Team, TeamBrief } from '../api/types';

export interface TeamScope {
  /** Команда, данные которой смотрит администратор; null — все команды. У пользователя всегда null: сервер сам показывает его команду. */
  teamId: string | null;
  setTeamId: (id: string | null) => void;
  /** Команды для переключателя — только у администратора. */
  teams: Team[];
  /** Выбранная команда администратора или команда пользователя. */
  current: TeamBrief | null;
  /** Администратор смотрит все команды — в строках нужно подписывать, чья это строка. */
  showTeams: boolean;
}

export const TeamScopeContext = createContext<TeamScope | null>(null);

export function useTeamScope() {
  const ctx = useContext(TeamScopeContext);
  if (!ctx) throw new Error('useTeamScope must be used inside TeamScopeProvider');
  return ctx;
}
