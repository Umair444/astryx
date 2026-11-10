import { apiSend } from '../../api'
import type { Project } from '../model'

/* What a project's agents are TOLD: the first message of a chat started in a project opens with its context block

     [project: <name>]
     <instructions>
     Project files: [[file:<path>]] (<name>) …
     [/project]

   then the owner's words. The block is for the agents: model.stripEmbeds hides it in the conversation and
   workspace.clean in the list (the SQL cuts it before the preview's clip). Pinned files ride as ordinary [[file:]]
   embeds, so an agent reads them like any attachment; each is EXPORTED first (POST /api/ws/artifacts/<id>/export):
   the path its source still holds, or a snapshot of the head when the owner has edited it since. */

export interface Exported { id: string; name: string; path: string }
export const exportArtifact = (id: string) => apiSend<Exported>('POST', `/ws/artifacts/${encodeURIComponent(id)}/export`)

const clean = (s: string) => s.replace(/[\]\n\r]+/g, ' ').trim().slice(0, 80)

export function contextBlock(p: Project, files: Exported[]): string {
  const brief = p.instructions.trim().replace(/^\[\/project\]$/gm, '(/project)')     // the one line that would close it early
  const lines = [`[project: ${clean(p.name)}]`]
  if (brief) lines.push(brief)
  if (files.length) lines.push(`Project files: ${files.map((f) => `[[file:${f.path}]] (${clean(f.name).replace(/[()]/g, '')})`).join(' ')}`)
  lines.push('[/project]')
  return lines.join('\n') + '\n'
}

/* the block for `p`, its files exported in parallel; a file that can't be exported is left out, never the message */
export async function projectContext(p: Project): Promise<string> {
  if (!p.instructions.trim() && !p.files.length) return ''
  const got = await Promise.all(p.files.map((id) => exportArtifact(id).catch(() => null)))
  return contextBlock(p, got.filter((x): x is Exported => !!x))
}
