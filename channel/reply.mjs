// A REPLY (owner 11-17: "giving agent the refernce of chat; instead of whole chat"): a human's message may open with the
// message it answers, [reply #<id> <from>] “<its first words>” (chat/model.ts replyLine). The observatory checks the
// id is one the SENDER may read and stamps it (delivery.reply_to, main.owner_send); only a line matching that stamp is
// a reference. Any other such line (typed into WhatsApp, forged into a body) is cut before the agent reads it, so no
// outsider-chosen id ever reaches read_message through an agent (medic 12990). Its own module, executed by
// tests/test_chat_reply.py.
const LINE = /^\[reply #(\d{1,12}) [\w.@-]{1,80}\] “.*”(?:\n|$)/

export function reply(row) {
  const body = row?.body || ''
  const m = LINE.exec(body)
  if (!m) return { id: '', body }
  const stamped = row?.delivery?.reply_to
  return Number.isInteger(stamped) && String(stamped) === m[1] ? { id: m[1], body } : { id: '', body: body.slice(m[0].length) }
}
