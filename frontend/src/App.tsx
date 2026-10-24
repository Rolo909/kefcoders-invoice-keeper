import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthProvider';
import { RequireAuth } from './auth/guards';
import { AppLayout } from './components/AppLayout';
import { DialogsProvider } from './components/dialogs/DialogsProvider';
import { AuditPage } from './pages/AuditPage';
import { CalendarPage } from './pages/CalendarPage';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OccurrencePage } from './pages/OccurrencePage';
import { OccurrencesPage } from './pages/OccurrencesPage';
import { PaymentPage } from './pages/PaymentPage';
import { PaymentsPage } from './pages/PaymentsPage';
import { SettingsPage } from './pages/SettingsPage';
import { SummaryPage } from './pages/SummaryPage';
import { UsersPage } from './pages/UsersPage';

export function App() {
  return (
    <AuthProvider>
      <DialogsProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="occurrences" element={<OccurrencesPage />} />
              <Route path="occurrences/:id" element={<OccurrencePage />} />
              <Route path="recurring-payments" element={<PaymentsPage />} />
              <Route path="recurring-payments/:id" element={<PaymentPage />} />
              <Route path="calendar" element={<CalendarPage />} />
              <Route path="summary" element={<SummaryPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="dashboard" element={<Navigate to="/" replace />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </DialogsProvider>
    </AuthProvider>
  );
}
