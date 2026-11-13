// cog fan-out (owner 11-13: "@lending, @seed work together and do this"): a human message that names two or more
// agents reaches each of them, stamped {team, lead} in delivery (bridges/common.team_stamp, the one stamp every
// surface writes; the FIRST named leads). This turns the stamp into the line each member reads ahead of the message,
// so the lead owns the answer and the helpers don't reply over it. Only the agent's notification carries the line;
// the stored body stays the human's own words. Its own module so tests/test_fanout.py can EXECUTE it.

export function team(row, me) {
  const t = row?.delivery?.team
  const lead = row?.delivery?.lead
  if (!Array.isArray(t) || t.length < 2 || typeof lead !== 'string' || !t.includes(lead) || !t.includes(me)) {
    return null
  }
  const names = t.map((a) => (a === lead ? `${a} (lead)` : a)).join(', ')
  const others = t.filter((a) => a !== me).join(', ')
  const line = me === lead
    ? `[team: ${names}. You LEAD: you own the answer and you reply to the human. ${others} also got this message ` +
      `and will work with you over the wire on this thread; ask them for what is theirs, then send ONE reply.]`
    : `[team: ${names}. ${lead} leads and replies to the human. Work with ${lead} over the wire on this thread: ` +
      `start directly on what is clearly your own domain, or ask ${lead} first if unsure. Do NOT reply to the ` +
      `human unless ${lead} asks you to.]`
  return { members: t.join(','), lead, line }
}
