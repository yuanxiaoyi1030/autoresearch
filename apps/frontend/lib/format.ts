// Purpose: Safely formats unknown persisted records without inventing missing frontend state.
import type {ApiRecord} from "./types";

export function record(value: unknown): ApiRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as ApiRecord : {};
}

export function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function records(value: unknown): ApiRecord[] {
  return Array.isArray(value) ? value.filter(item => item !== null && typeof item === "object" && !Array.isArray(item)) as ApiRecord[] : [];
}

export function text(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function shortId(value: unknown): string {
  const raw = text(value);
  return raw.length > 24 ? `${raw.slice(0, 10)}…${raw.slice(-8)}` : raw;
}

export function dateTime(value: unknown): string {
  if (typeof value !== "string") return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
  }).format(date);
}

export function titleCase(value: unknown): string {
  return text(value).replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

export function numeric(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function identifier(item: ApiRecord, keys: string[]): string {
  for (const key of keys) if (typeof item[key] === "string") return String(item[key]);
  return "record";
}
