// Formats the time the data was last read from Odoo ("14:32", or "12/11 14:32" when it is not from today).
const two = (n: number) => String(n).padStart(2, "0");

export function formatUpdated(iso: string | undefined | null, now: Date = new Date()): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const time = `${two(when.getHours())}:${two(when.getMinutes())}`;
  const sameDay = when.getFullYear() === now.getFullYear() && when.getMonth() === now.getMonth() && when.getDate() === now.getDate();
  return sameDay ? time : `${two(when.getDate())}/${two(when.getMonth() + 1)} ${time}`;
}
