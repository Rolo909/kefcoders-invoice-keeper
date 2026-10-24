import { createContext, useContext } from 'react';
import type { ISODate, Me, User } from '../api/types';

export interface AuthState {
  me: Me | undefined;
  user: User | undefined;
  isAdmin: boolean;
  today: ISODate;
  loading: boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

export const useToday = () => useAuth().today;
