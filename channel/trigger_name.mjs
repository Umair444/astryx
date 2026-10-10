// The ONE place a trigger name becomes a file path (channel/server.mjs trigger_set, kind python).
// a2 #45063, a4 #45070: the name came straight from the tool call into `new URL(name + '.py', triggers/<AGENT>/)`,
// so '../../hooks/step' resolved to hooks/step.py and '/etc/x' to /etc/x.py: any session holding the astryx MCP could
// overwrite any .py the uid can write, including step.py's guards. Now:
//   · a trailing '.py' is dropped first (the naive caller: painter's 'org_pulse_refresh.py' became '….py.py');
//   · the name must match ^[a-z0-9_]+$ (a python module name; the pulse imports it);
//   · and the resolved file's directory must BE triggers/<AGENT>/, checked on the resolved path, not the string.
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

export const TRIGGER_NAME = /^[a-z0-9_]+$/

/** The file URL a python trigger named `name` is written to, inside `dir` (a directory URL), or throws. */
export function triggerFile(dir, name) {
  const nm = String(name ?? '').trim().replace(/\.py$/, '')
  if (!TRIGGER_NAME.test(nm)) {
    throw new Error(`trigger name must be a python module name matching ^[a-z0-9_]+$ (got ${JSON.stringify(name)})`)
  }
  const file = new URL(`${nm}.py`, dir)
  if (dirname(fileURLToPath(file)) !== fileURLToPath(dir).replace(/\/+$/, '')) {
    throw new Error(`trigger file would land outside ${fileURLToPath(dir)}`)
  }
  return file
}
