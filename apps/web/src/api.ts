export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`GET ${path}: ${response.status}`)
  }
  return response.json()
}

export async function apiPost(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`POST ${path}: ${response.status}`)
  }
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })
}

export const STATUS_LABELS: Record<string, string> = {
  capturing: 'Capturando',
  queued_transcription: 'Na fila (transcrição)',
  transcribing: 'Transcrevendo',
  queued_analysis: 'Na fila (análise)',
  analyzing: 'Analisando',
  ready: 'Pronto',
  failed: 'Falhou',
}

export const EVENT_LABELS: Record<string, string> = {
  'channel.follow': 'Follow',
  'channel.subscribe': 'Sub',
  'channel.subscription.gift': 'Sub gift',
  'channel.subscription.message': 'Resub',
  'channel.cheer': 'Bits',
  'channel.raid': 'Raid',
  'channel.update': 'Título/categoria',
  'channel.ad_break.begin': 'Anúncios',
}
