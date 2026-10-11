// RETIRED is a declared fact, per (agent, name) (plan-9853 D2, a3 BC-1/BC-2): trigger_rm writes the tombstone
// triggers/<agent>/.retired/<name> for a python trigger, and the pulse's reconcile then never re-enables that (agent,
// name), though the file still defines it (moving the file would retire every OTHER trigger in it). The creators of
// (agent, name), trigger_set and `init.sh --reinstall`, clear it. One writer of the fact (trigger_rm); readers: the
// pulse and init.sh. It rides triggers/ (state.tgz), so it survives a restore and a respawn.
import { mkdir, writeFile, unlink } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { TRIGGER_NAME } from './trigger_name.mjs'

/** The tombstone's file URL under `root` (the triggers/ directory URL) for (agent, name), or throws. */
export function tombstoneFile(root, agent, name) {
  const a = String(agent ?? ''), n = String(name ?? '')
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(a)) throw new Error(`not an agent name: ${JSON.stringify(agent)}`)
  if (!TRIGGER_NAME.test(n)) throw new Error(`not a trigger name: ${JSON.stringify(name)}`)
  return new URL(`${a}/.retired/${n}`, root)
}

export async function retire(root, agent, name) {
  const f = tombstoneFile(root, agent, name)
  await mkdir(new URL('./', f), { recursive: true })
  await writeFile(f, `${new Date().toISOString()} retired by trigger_rm\n`)
  return f
}

export async function clear(root, agent, names) {
  for (const n of names) {
    try { await unlink(tombstoneFile(root, agent, n)) } catch { /* absent, or not a name: nothing to clear */ }
  }
}

/** The names a python trigger file DEFINES, exactly as the pulse registers them: `pulse.py --names <file>` runs the
 *  pulse's own discover (the import closure, so a shim's shipped trigger counts; any decorator layout). trigger_set
 *  clears exactly these (a4 #49496: a source regex missed 40 of 49 real defs and every shim). A file that doesn't load
 *  yields [], and the pulse's once-per-tombstone notice says what is still retired. */
export function definedNames(file, { py, pulse, timeout = 25_000 } = {}) {
  return new Promise((resolve) => {
    execFile(py, [pulse, '--names', file], { timeout }, (err, stdout) => {
      let names = []
      try { names = err ? [] : JSON.parse(stdout) } catch { names = [] }
      resolve(Array.isArray(names) ? names.filter(n => TRIGGER_NAME.test(String(n))) : [])
    })
  })
}
