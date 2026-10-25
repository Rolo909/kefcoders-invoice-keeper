/**
 * Вход в панель — одна cookie на весь сайт, общая для всех вкладок браузера. Если в одной вкладке войти
 * под другим пользователем или выйти, остальные вкладки уже работают от его имени или без входа.
 * Чтобы они не показывали устаревшее (и не отмечали оплату не от того человека), сообщаем им об этом
 * через localStorage — событие storage приходит во все другие вкладки сайта.
 */
const KEY = 'ik-auth-changed';

export function announceAuthChange() {
  try {
    localStorage.setItem(KEY, String(Date.now()));
  } catch {
    // хранилище недоступно (приватный режим) — вкладки обновятся при следующем запросе
  }
}

export function onAuthChangedElsewhere(handler: () => void) {
  const listener = (event: StorageEvent) => {
    if (event.key === KEY) handler();
  };
  window.addEventListener('storage', listener);
  return () => window.removeEventListener('storage', listener);
}
