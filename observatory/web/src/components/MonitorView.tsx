import { useEffect, useState } from 'react'
import { ScrollArea, SegmentedControl, Table } from '@mantine/core'
import { api } from '../api'
import type { SysInfo, Proc } from '../types'

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const u = ['B', 'K', 'M', 'G', 'T']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)}${u[i]}`
}

function fmtDur(s: number): string {
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`
}

const hue = (p: number) => (p >= 90 ? '#f87171' : p >= 70 ? '#fbbf24' : '#34d399')

function Bar({ pct, label, sub }: { pct: number; label: string; sub?: string }) {
  return (
    <div className="mb-2">
      <div className="flex justify-between text-[11px] mb-0.5">
        <span className="text-ink-dim truncate">{label}</span>
        <span className="font-mono text-ink-mute">{sub ?? `${pct.toFixed(0)}%`}</span>
      </div>
      <div className="h-1.5 rounded-full bg-deck overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%`, background: hue(pct) }}
        />
      </div>
    </div>
  )
}

function Card({ title, aside, children }: { title: string; aside?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-deck-3/40 p-3">
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-dim">{title}</div>
        {aside && <div className="text-[10px] font-mono text-ink-mute">{aside}</div>}
      </div>
      {children}
    </div>
  )
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between text-[11px] py-0.5">
      <span className="text-ink-mute">{k}</span>
      <span className="text-ink-dim font-mono truncate ml-2">{v}</span>
    </div>
  )
}

export default function MonitorView() {
  const [sys, setSys] = useState<SysInfo | null>(null)
  const [procs, setProcs] = useState<Proc[]>([])
  const [psort, setPsort] = useState('cpu')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const s = await api<SysInfo>('/system')
        if (live) {
          setSys(s)
          setErr(null)
        }
      } catch (e) {
        if (live) setErr(String(e))
      }
    }
    tick()
    const t = setInterval(tick, 2000)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [])

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const p = await api<Proc[]>(`/system/processes?sort=${psort}&limit=40`)
        if (live) setProcs(p)
      } catch {
        /* ignore */
      }
    }
    tick()
    const t = setInterval(tick, 3000)
    return () => {
      live = false
      clearInterval(t)
    }
  }, [psort])

  if (err && !sys)
    return <div className="p-4 text-sm text-ink-mute">monitor unavailable — {err}</div>
  if (!sys) return <div className="p-4 text-sm text-ink-mute">reading system…</div>

  const s = sys.specs
  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 px-4 py-2 border-b border-line flex items-baseline gap-2">
        <span className="font-semibold text-ink">Monitor</span>
        <span className="text-xs text-ink-mute font-mono">
          {s.hostname} · {s.os} · up {fmtDur(sys.uptime)}
        </span>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-4 grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
          <Card title="CPU" aside={sys.cpu.freq_mhz ? `${(sys.cpu.freq_mhz / 1000).toFixed(2)} GHz` : undefined}>
            <div className="flex items-end gap-2 mb-2">
              <span className="text-2xl font-bold" style={{ color: hue(sys.cpu.percent) }}>
                {sys.cpu.percent.toFixed(0)}%
              </span>
              <span className="text-[10px] text-ink-mute mb-1 font-mono">
                load {sys.cpu.load.map((l) => l.toFixed(2)).join(' ')}
              </span>
            </div>
            <div className="flex gap-1 h-10 items-end">
              {sys.cpu.per_core.map((c, i) => (
                <div key={i} className="flex-1 bg-deck rounded-sm overflow-hidden flex items-end" title={`core ${i}: ${c.toFixed(0)}%`}>
                  <div className="w-full transition-all duration-500" style={{ height: `${c}%`, background: hue(c) }} />
                </div>
              ))}
            </div>
          </Card>

          <Card title="Memory" aside={`${fmtBytes(sys.mem.used)} / ${fmtBytes(sys.mem.total)}`}>
            <Bar pct={sys.mem.percent} label="RAM" sub={`${sys.mem.percent.toFixed(0)}% · ${fmtBytes(sys.mem.available)} free`} />
            {sys.mem.swap_total > 0 && (
              <Bar pct={sys.mem.swap_percent} label="Swap" sub={`${fmtBytes(sys.mem.swap_used)} / ${fmtBytes(sys.mem.swap_total)}`} />
            )}
          </Card>

          <Card title="Disks" aside={`${sys.disks.length} mounts`}>
            {sys.disks.map((d) => (
              <Bar key={d.mount} pct={d.percent} label={`${d.mount} (${d.fstype})`} sub={`${fmtBytes(d.used)} / ${fmtBytes(d.total)}`} />
            ))}
          </Card>

          <Card title="GPU">
            {sys.gpu.length === 0 && <div className="text-[11px] text-ink-mute">none detected</div>}
            {sys.gpu.map((g, i) => (
              <div key={i} className="mb-2">
                <div className="text-[11px] text-ink-dim truncate mb-1">{g.name}</div>
                {g.util != null ? (
                  <>
                    <Bar pct={g.util} label="util" />
                    {g.mem_total ? <Bar pct={(g.mem_used! / g.mem_total) * 100} label="vram" sub={`${fmtBytes(g.mem_used)} / ${fmtBytes(g.mem_total)}`} /> : null}
                    {g.temp != null && <Stat k="temp" v={`${g.temp}°C`} />}
                  </>
                ) : (
                  <div className="text-[10px] text-ink-mute font-mono">integrated · no live metrics</div>
                )}
              </div>
            ))}
          </Card>

          <Card title="Network" aside={sys.wifi.iface ?? undefined}>
            <Stat k="↑ sent" v={fmtBytes(sys.net.sent)} />
            <Stat k="↓ recv" v={fmtBytes(sys.net.recv)} />
            {sys.wifi.iface && (
              <>
                <Bar pct={sys.wifi.quality ?? 0} label={`wifi ${sys.wifi.iface}`} sub={sys.wifi.signal_dbm != null ? `${sys.wifi.signal_dbm} dBm` : undefined} />
              </>
            )}
          </Card>

          <Card title="Sensors">
            <Stat k="cpu" v={s.cpu} />
            <Stat k="cores / threads" v={`${s.cores} / ${s.threads}`} />
            <Stat k="ram" v={fmtBytes(s.ram_total)} />
            {sys.temps.slice(0, 8).map((t, i) => (
              <Stat key={i} k={t.label} v={`${t.current.toFixed(0)}°C`} />
            ))}
          </Card>
        </div>

        <div className="px-4 pb-4">
          <div className="rounded-lg border border-line bg-deck-3/40">
            <div className="flex items-center justify-between px-3 py-2 border-b border-line">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-dim">Processes</div>
              <SegmentedControl
                size="xs"
                value={psort}
                onChange={setPsort}
                data={[
                  { label: 'by CPU', value: 'cpu' },
                  { label: 'by MEM', value: 'mem' },
                ]}
              />
            </div>
            <Table verticalSpacing={4} horizontalSpacing="sm" className="text-[12px]">
              <Table.Thead>
                <Table.Tr className="text-ink-mute">
                  <Table.Th style={{ width: 70 }}>PID</Table.Th>
                  <Table.Th>Name</Table.Th>
                  <Table.Th>User</Table.Th>
                  <Table.Th style={{ width: 70, textAlign: 'right' }}>CPU%</Table.Th>
                  <Table.Th style={{ width: 70, textAlign: 'right' }}>MEM%</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {procs.map((p) => (
                  <Table.Tr key={p.pid}>
                    <Table.Td className="font-mono text-ink-mute">{p.pid}</Table.Td>
                    <Table.Td className="text-ink-dim truncate">{p.name}</Table.Td>
                    <Table.Td className="text-ink-mute">{p.user}</Table.Td>
                    <Table.Td className="font-mono text-right" style={{ color: hue(p.cpu) }}>{p.cpu.toFixed(1)}</Table.Td>
                    <Table.Td className="font-mono text-right" style={{ color: hue(p.mem) }}>{p.mem.toFixed(1)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
