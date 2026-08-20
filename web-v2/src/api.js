export async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m 前`;
  if (s < 86400) return `${Math.round(s / 3600)}h 前`;
  return `${Math.round(s / 86400)}d 前`;
}

export function fmtVel(v) {
  if (v == null) return "—";
  if (v > 0) return `▲${v}%`;
  if (v < 0) return `▼${Math.abs(v)}%`;
  return "—";
}

export function spanDays(created, updated) {
  if (!created || !updated) return null;
  return Math.max(
    1,
    Math.round((new Date(updated) - new Date(created)) / 86400000),
  );
}
