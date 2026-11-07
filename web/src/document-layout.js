export function safeLink(url) {
  try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; } catch { return null; }
}
export function parseDocument(value) {
  const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = []; let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (/^```/.test(line)) { const code=[]; i++; while(i<lines.length && !/^```/.test(lines[i])) code.push(lines[i++]); if(i<lines.length)i++; blocks.push({type:'code',text:code.join('\n')}); continue; }
    const heading = line.match(/^(#{1,6})\s+(.+)$/); if(heading) { blocks.push({type:'heading',level:heading[1].length,text:heading[2]}); i++; continue; }
    if(i+1<lines.length && line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i+1])) { const rows=[line]; i+=2; while(i<lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(lines[i++]); blocks.push({type:'table',rows:rows.map(x=>x.replace(/^\s*\||\|\s*$/g,'').split('|').map(y=>y.trim()))}); continue; }
    if(/^\s*[-*+]\s+/.test(line)) { const items=[]; while(i<lines.length && /^\s*[-*+]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*+]\s+/,'')); blocks.push({type:'list',items}); continue; }
    const paragraph=[line]; i++; while(i<lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*[-*+]\s)/.test(lines[i])) paragraph.push(lines[i++]); blocks.push({type:'paragraph',text:paragraph.join('\n')});
  } return blocks;
}
