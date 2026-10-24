import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <div className="empty">
      <span className="stamp big" aria-hidden="true">404</span>
      <h2>Такой страницы нет</h2>
      <p>Возможно, ссылка устарела или в адресе опечатка.</p>
      <Link to="/">Вернуться к сводке</Link>
    </div>
  );
}
