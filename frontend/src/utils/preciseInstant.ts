/** Normalize timezone without truncating a server's fractional-second cutoff. */
export function preciseInstant(value: string): string {
  const iso = new Date(value).toISOString()
  const fraction = /\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1]
  return fraction && fraction.length > 3 ? iso.replace(/\.\d{3}Z$/, `.${fraction}Z`) : iso
}
