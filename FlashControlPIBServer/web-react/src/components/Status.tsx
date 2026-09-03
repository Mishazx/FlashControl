export function Loading() {
  return (
    <div className="loading">
      <div>
        <div className="spinner" />
        <p>Загрузка данных…</p>
      </div>
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="panel empty">
      <strong>Не удалось загрузить данные</strong>
      <p>{message}</p>
    </div>
  );
}
