export const tehranTime = (value: string) =>
  new Date(value).toLocaleString("fa-IR", { timeZone: "Asia/Tehran" });
export function tehranLocalInput(date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)!.value;
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

// Tehran has a fixed UTC+03:30 offset for the operational dates supported here.
export const tehranInputISO = (value: string) =>
  new Date(`${value}:00+03:30`).toISOString();
