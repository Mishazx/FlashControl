export const identityResultLabels: Record<string, string> = {
  SAME: 'Совпадает',
  LIKELY_SAME: 'Скорее совпадает',
  UNKNOWN: 'Неизвестно',
  SERIAL_COLLISION: 'Коллизия серийника',
  CLONE_SUSPECTED: 'Подозрение на клон',
  DIFFERENT: 'Другое устройство',
};

export const confidenceLabels: Record<string, string> = {
  high: 'Высокая',
  likely: 'Вероятная',
  unknown: 'Неизвестно',
};

export const confidenceColumnHint =
  'Насколько система уверена, что это то же физическое устройство, а не похожая флешка с тем же серийником.';

export const identityConfidenceHints: Record<string, string> = {
  high: 'Высокая: железо и разметка совпали на том же компьютере, наблюдения склеены в одно устройство.',
  likely: 'Вероятная: признаки похожи, но автоматически не склеивается — например, то же железо на другом ПК.',
  unknown: 'Неизвестно: первое появление устройства или слишком мало совпадений.',
};

export const decisionConfidenceHints: Record<string, string> = {
  SAME: '95%: то же железо, та же разметка и тот же компьютер.',
  LIKELY_SAME: '80%: то же железо и разметка, но другой компьютер.',
  UNKNOWN: '45%: железо совпало, разметка другая или отсутствует.',
  CLONE_SUSPECTED: '20%: разметка та же, железо другое — возможен клон.',
  SERIAL_COLLISION: '5%: серийник совпал, железо другое.',
  DIFFERENT: '0%: железо не совпало.',
};

export const agentStatusLabels: Record<string, string> = {
  online: 'Онлайн',
  offline: 'Офлайн',
  missing: 'Без агента',
};

export const routeLabels: Record<string, string> = {
  direct: 'Напрямую',
  proxy: 'Через прокси',
  offline: 'Офлайн',
};

export const eventTypeLabels: Record<string, string> = {
  snapshot: 'Снимок',
  connected: 'Подключено',
  disconnected: 'Отключено',
};

export const deviceStatusLabels: Record<string, string> = {
  provisional: 'Промежуточный',
};

export const auditResultLabels: Record<string, string> = {
  true: 'Успешно',
  false: 'Неуспешно',
};

export function translate(value: unknown, labels: Record<string, string>): string {
  const key = value == null ? '' : String(value);
  return labels[key] || key || 'Неизвестно';
}

export function roleLabel(role: string): string {
  return (
    ({ admin: 'Администратор', security: 'Безопасность', auditor: 'Аудитор' } as Record<string, string>)[role] ||
    role
  );
}
