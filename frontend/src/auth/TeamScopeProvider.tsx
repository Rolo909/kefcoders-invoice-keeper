import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTeams } from '../api/hooks';
import { useAuth } from './context';
import { TeamScopeContext, type TeamScope } from './team';

const STORAGE_KEY = 'ik-team-scope';

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function TeamScopeProvider({ children }: { children: ReactNode }) {
  const { isAdmin, user } = useAuth();
  const teams = useTeams(isAdmin);
  const [stored, setStored] = useState(readStored);

  const setTeamId = useCallback((id: string | null) => {
    setStored(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // storage unavailable: the choice lives until reload
    }
  }, []);

  const value = useMemo<TeamScope>(() => {
    const list = teams.data?.items ?? [];
    // Пока список команд грузится, верим сохранённому выбору; потом сбрасываем, если команды больше нет.
    const teamId = isAdmin && stored && (!teams.data || list.some((t) => t.id === stored)) ? stored : null;
    const picked = list.find((t) => t.id === teamId);
    return {
      teamId,
      setTeamId,
      teams: list,
      current: isAdmin ? (picked ? { id: picked.id, name: picked.name } : null) : user?.team ?? null,
      showTeams: isAdmin && teamId === null,
    };
  }, [isAdmin, stored, teams.data, user, setTeamId]);

  return <TeamScopeContext.Provider value={value}>{children}</TeamScopeContext.Provider>;
}
